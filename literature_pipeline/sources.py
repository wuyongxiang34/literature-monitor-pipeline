from __future__ import annotations

import datetime as dt
import html
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

from . import __version__
from .models import Paper
from .normalize import normalize_arxiv, normalize_doi, normalize_openalex


LOGGER = logging.getLogger(__name__)
ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


class SourceConnectionError(RuntimeError):
    """Raised after a source cannot be reached despite request retries."""


class SourceAuthenticationError(RuntimeError):
    """Raised when a source rejects the supplied API credentials."""


class SourceAuthorizationError(RuntimeError):
    """Raised when credentials are valid but lack access to a source."""


class SourceRateLimitError(RuntimeError):
    """Raised when a source remains rate limited after retries."""


def _request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
    attempts: int = 3,
    data: bytes | None = None,
    method: str | None = None,
) -> bytes:
    request_headers = {
        "Accept": "application/json, application/atom+xml;q=0.9",
        "User-Agent": f"LiteratureMonitorPipeline/{__version__}",
        **(headers or {}),
    }
    error: Exception | None = None
    use_system_proxy = os.getenv("LITERATURE_USE_SYSTEM_PROXY", "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    opener = None if use_system_proxy else urllib.request.build_opener(
        urllib.request.ProxyHandler({})
    )
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                url,
                headers=request_headers,
                data=data,
                method=method,
            )
            response_context = (
                urllib.request.urlopen(request, timeout=timeout)
                if opener is None
                else opener.open(request, timeout=timeout)
            )
            with response_context as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            error = exc
            if exc.code == 401:
                raise SourceAuthenticationError(
                    f"请求认证失败：{url}；HTTP 401，请检查 API Key 是否已激活"
                ) from exc
            if exc.code == 403:
                raise SourceAuthorizationError(
                    f"请求未获授权：{url}；HTTP 403，请检查接口权限或用量限制"
                ) from exc
            if exc.code not in {408, 425, 429, 500, 502, 503, 504}:
                raise RuntimeError(f"请求失败：{url}；HTTP {exc.code}") from exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            error = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    if isinstance(error, urllib.error.HTTPError):
        if error.code == 429:
            raise SourceRateLimitError(
                f"请求达到用量限制：{url}；HTTP 429"
            ) from error
        raise RuntimeError(f"请求失败：{url}；HTTP {error.code}") from error
    raise SourceConnectionError(f"请求失败：{url}；{error}") from error


def _json(url: str, **kwargs: Any) -> dict[str, Any]:
    return json.loads(_request(url, **kwargs).decode("utf-8"))


def _date_parts(value: dict[str, Any]) -> str:
    parts = value.get("date-parts") or []
    if not parts or not parts[0]:
        return ""
    return "-".join(f"{part:02d}" if index else f"{part:04d}" for index, part in enumerate(parts[0][:3]))


def _clean_abstract(value: str | None) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(value or ""))
    return " ".join(text.split())


def search_crossref(query: str, start: str, end: str, limit: int, timeout: int) -> list[Paper]:
    params = urllib.parse.urlencode(
        {
            "query.bibliographic": query,
            "filter": f"from-pub-date:{start},until-pub-date:{end},type:journal-article",
            "rows": limit,
        }
    )
    items = _json(f"https://api.crossref.org/works?{params}", timeout=timeout)["message"]["items"]
    papers: list[Paper] = []
    for item in items:
        authors = [
            " ".join(part for part in (author.get("given"), author.get("family")) if part)
            for author in item.get("author", [])
        ]
        links = item.get("link") or []
        pdf_url = next(
            (link.get("URL", "") for link in links if "pdf" in link.get("content-type", "").casefold()),
            "",
        )
        pub_date = (
            _date_parts(item.get("published-online") or {})
            or _date_parts(item.get("published-print") or {})
            or _date_parts(item.get("published") or {})
        )
        papers.append(
            Paper(
                title=(item.get("title") or [""])[0],
                abstract=_clean_abstract(item.get("abstract")),
                authors=authors,
                journal=(item.get("container-title") or [""])[0],
                publication_date=pub_date,
                doi=normalize_doi(item.get("DOI")),
                url=item.get("URL", ""),
                pdf_url=pdf_url,
                keywords=item.get("subject") or [],
                document_type=item.get("type") or "article",
                citation_count=int(item.get("is-referenced-by-count") or 0),
                sources=["crossref"],
                reading_depth="Abstract only" if item.get("abstract") else "Metadata only",
            )
        )
    return papers


def _invert_abstract(index: dict[str, list[int]] | None) -> str:
    words = [(position, word) for word, positions in (index or {}).items() for position in positions]
    return " ".join(word for _, word in sorted(words))


def search_openalex(
    query: str, start: str, end: str, limit: int, timeout: int, api_key: str
) -> list[Paper]:
    params = {
        "search": query,
        "filter": f"from_publication_date:{start},to_publication_date:{end}",
        "per-page": min(limit, 200),
        "select": (
            "id,doi,title,display_name,publication_date,authorships,primary_location,"
            "best_oa_location,open_access,abstract_inverted_index,type,cited_by_count,keywords"
        ),
    }
    params["api_key"] = api_key
    items = _json(
        "https://api.openalex.org/works?" + urllib.parse.urlencode(params), timeout=timeout
    ).get("results", [])
    papers: list[Paper] = []
    for item in items:
        authorships = item.get("authorships") or []
        authors = [
            authorship.get("author", {}).get("display_name", "")
            for authorship in authorships
            if authorship.get("author")
        ]
        institutions = [
            institution.get("display_name", "")
            for authorship in authorships
            for institution in (authorship.get("institutions") or [])
            if institution.get("display_name")
        ]
        location = item.get("primary_location") or {}
        source = location.get("source") or {}
        best_oa = item.get("best_oa_location") or {}
        abstract = _invert_abstract(item.get("abstract_inverted_index"))
        papers.append(
            Paper(
                title=item.get("title") or item.get("display_name") or "",
                abstract=abstract,
                authors=authors,
                journal=source.get("display_name") or "",
                publication_date=item.get("publication_date") or "",
                doi=normalize_doi(item.get("doi")),
                openalex_id=normalize_openalex(item.get("id")),
                url=item.get("doi") or item.get("id") or "",
                pdf_url=best_oa.get("pdf_url") or "",
                institutions=list(dict.fromkeys(institutions)),
                keywords=[
                    keyword.get("display_name", "")
                    for keyword in (item.get("keywords") or [])
                    if keyword.get("display_name")
                ],
                document_type=item.get("type") or "article",
                citation_count=int(item.get("cited_by_count") or 0),
                sources=["openalex"],
                reading_depth="Abstract only" if abstract else "Metadata only",
            )
        )
    return papers


def _sciencedirect_result_count(limit: int) -> int:
    return next((value for value in (10, 25, 50, 100) if value >= limit), 100)


def _sciencedirect_query_terms(query: str) -> list[str]:
    phrases = re.findall(r'"([^"]+)"', query)
    if phrases:
        return list(dict.fromkeys(phrase.strip() for phrase in phrases if phrase.strip()))
    return [
        token
        for token in re.findall(r"[A-Za-z][A-Za-z-]+", query)
        if token.upper() not in {"AND", "OR", "NOT"}
    ]


def _elsevier_headers(api_key: str, inst_token: str = "") -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "X-ELS-APIKey": api_key,
    }
    if inst_token:
        headers["X-ELS-Insttoken"] = inst_token
    return headers


def _retrieval_abstract(data: dict[str, Any], root_name: str) -> str:
    root = data.get(root_name) or {}
    coredata = root.get("coredata") or {}
    value = coredata.get("dc:description") or ""
    if isinstance(value, dict):
        value = value.get("$") or value.get("_") or ""
    return _clean_abstract(str(value))


def retrieve_elsevier_abstract(
    doi: str,
    timeout: int,
    api_key: str,
    inst_token: str = "",
    state: dict[str, Any] | None = None,
) -> str:
    """Retrieve an abstract by DOI with article -> Scopus -> empty fallback."""
    doi = normalize_doi(doi)
    if not doi:
        return ""
    state = state if state is not None else {}
    headers = _elsevier_headers(api_key, inst_token)
    encoded_doi = urllib.parse.quote(doi, safe="/")
    attempts = (
        (
            "article",
            f"https://api.elsevier.com/content/article/doi/{encoded_doi}?view=META_ABS",
            "full-text-retrieval-response",
        ),
        (
            "scopus",
            f"https://api.elsevier.com/content/abstract/doi/{encoded_doi}?view=META_ABS",
            "abstracts-retrieval-response",
        ),
    )
    for provider, url, root_name in attempts:
        if state.get(f"{provider}_disabled", False):
            continue
        try:
            data = _json(url, headers=headers, timeout=timeout, attempts=1)
            abstract = _retrieval_abstract(data, root_name)
            if abstract:
                return abstract
        except (SourceAuthenticationError, SourceAuthorizationError) as exc:
            state[f"{provider}_disabled"] = True
            if not state.get(f"{provider}_warning_logged", False):
                LOGGER.info("Elsevier %s 摘要接口不可用，本次运行停止重试：%s", provider, exc)
                state[f"{provider}_warning_logged"] = True
        except (SourceConnectionError, SourceRateLimitError, RuntimeError) as exc:
            if not state.get(f"{provider}_warning_logged", False):
                LOGGER.info("Elsevier %s 摘要接口暂不可用：%s", provider, exc)
                state[f"{provider}_warning_logged"] = True
    return ""


def search_sciencedirect(
    query: str,
    start: str,
    end: str,
    limit: int,
    timeout: int,
    api_key: str,
    inst_token: str = "",
    *,
    enrich_abstracts: bool = False,
    retrieval_state: dict[str, Any] | None = None,
) -> list[Paper]:
    payload = {
        "qs": query,
        "date": f"{start[:4]}-{end[:4]}",
        "display": {
            "offset": 0,
            "show": _sciencedirect_result_count(limit),
            "sortBy": "date",
        },
    }
    headers = _elsevier_headers(api_key, inst_token)
    headers["Content-Type"] = "application/json"
    response = json.loads(
        _request(
            "https://api.elsevier.com/content/search/sciencedirect",
            headers=headers,
            timeout=timeout,
            data=json.dumps(payload).encode("utf-8"),
            method="PUT",
        ).decode("utf-8")
    )
    query_terms = _sciencedirect_query_terms(query)
    papers: list[Paper] = []
    for item in (response.get("results") or [])[:limit]:
        publication_date = str(item.get("publicationDate") or "")[:10]
        if publication_date and not start <= publication_date <= end:
            continue
        author_items = item.get("authors") or []
        if isinstance(author_items, dict):
            author_items = [author_items]
        authors = [
            str(author.get("name") or "").strip()
            for author in author_items
            if isinstance(author, dict) and author.get("name")
        ]
        doi = normalize_doi(item.get("doi"))
        abstract = ""
        if enrich_abstracts and doi:
            state = retrieval_state if retrieval_state is not None else {}
            remaining = int(state.get("remaining", 1))
            if remaining > 0:
                state["remaining"] = remaining - 1
                abstract = retrieve_elsevier_abstract(
                    doi,
                    timeout,
                    api_key,
                    inst_token,
                    state,
                )
        papers.append(
            Paper(
                title=item.get("title") or "",
                abstract=abstract,
                authors=authors,
                journal=item.get("sourceTitle") or "",
                publication_date=publication_date,
                doi=doi,
                url=item.get("uri") or "",
                keywords=query_terms,
                document_type="article_or_chapter",
                sources=["sciencedirect"],
                reading_depth="Abstract only" if abstract else "Metadata only",
                sci_status="Indexed (ScienceDirect; not SCI evidence)",
            )
        )
    return papers


def search_arxiv(query: str, start: str, end: str, limit: int, timeout: int) -> list[Paper]:
    arxiv_query = " AND ".join(f'all:"{part.strip()}"' for part in query.split(" AND "))
    params = urllib.parse.urlencode(
        {"search_query": arxiv_query, "start": 0, "max_results": limit, "sortBy": "submittedDate", "sortOrder": "descending"}
    )
    root = ET.fromstring(_request(f"https://export.arxiv.org/api/query?{params}", timeout=timeout))
    start_date, end_date = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    papers: list[Paper] = []
    for entry in root.findall("atom:entry", ARXIV_NS):
        published = (entry.findtext("atom:published", default="", namespaces=ARXIV_NS) or "")[:10]
        if published:
            date_value = dt.date.fromisoformat(published)
            if not start_date <= date_value <= end_date:
                continue
        entry_url = entry.findtext("atom:id", default="", namespaces=ARXIV_NS)
        pdf_url = next(
            (
                link.attrib.get("href", "")
                for link in entry.findall("atom:link", ARXIV_NS)
                if link.attrib.get("title") == "pdf"
            ),
            "",
        )
        doi = entry.findtext("arxiv:doi", default="", namespaces=ARXIV_NS)
        authors = [
            author.findtext("atom:name", default="", namespaces=ARXIV_NS)
            for author in entry.findall("atom:author", ARXIV_NS)
        ]
        papers.append(
            Paper(
                title=" ".join((entry.findtext("atom:title", default="", namespaces=ARXIV_NS)).split()),
                abstract=" ".join((entry.findtext("atom:summary", default="", namespaces=ARXIV_NS)).split()),
                authors=authors,
                journal="arXiv",
                publication_date=published,
                doi=normalize_doi(doi),
                arxiv_id=normalize_arxiv(entry_url),
                url=entry_url,
                pdf_url=pdf_url,
                sources=["arxiv"],
                reading_depth="Abstract only",
            )
        )
    return papers


def search_semantic_scholar(
    query: str, start: str, end: str, limit: int, timeout: int, api_key: str
) -> list[Paper]:
    fields = (
        "paperId,title,abstract,authors,venue,publicationDate,externalIds,url,openAccessPdf,"
        "fieldsOfStudy,citationCount,publicationTypes"
    )
    params = urllib.parse.urlencode({"query": query, "limit": min(limit, 100), "fields": fields})
    data = _json(
        "https://api.semanticscholar.org/graph/v1/paper/search?" + params,
        timeout=timeout,
        headers={"x-api-key": api_key},
    ).get("data", [])
    papers: list[Paper] = []
    for item in data:
        publication_date = item.get("publicationDate") or ""
        if publication_date and not start <= publication_date[:10] <= end:
            continue
        ids = item.get("externalIds") or {}
        pdf = item.get("openAccessPdf") or {}
        papers.append(
            Paper(
                title=item.get("title") or "",
                abstract=item.get("abstract") or "",
                authors=[author.get("name", "") for author in item.get("authors") or []],
                journal=item.get("venue") or "",
                publication_date=publication_date[:10],
                doi=normalize_doi(ids.get("DOI")),
                arxiv_id=normalize_arxiv(ids.get("ArXiv")),
                semantic_scholar_id=item.get("paperId") or "",
                url=item.get("url") or "",
                pdf_url=pdf.get("url") or "",
                keywords=item.get("fieldsOfStudy") or [],
                document_type=(item.get("publicationTypes") or ["article"])[0],
                citation_count=int(item.get("citationCount") or 0),
                sources=["semantic_scholar"],
                reading_depth="Abstract only" if item.get("abstract") else "Metadata only",
            )
        )
    return papers


def _search_pubmed_ncbi(
    query: str, start: str, end: str, limit: int, timeout: int
) -> list[Paper]:
    term = f'({query}) AND ("{start}"[Date - Publication] : "{end}"[Date - Publication])'
    search_params = urllib.parse.urlencode(
        {"db": "pubmed", "term": term, "retmax": limit, "retmode": "json", "sort": "pub date"}
    )
    ids = (
        _json(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + search_params,
            timeout=timeout,
        )
        .get("esearchresult", {})
        .get("idlist", [])
    )
    if not ids:
        return []
    fetch_params = urllib.parse.urlencode({"db": "pubmed", "id": ",".join(ids), "retmode": "xml"})
    root = ET.fromstring(
        _request(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + fetch_params,
            timeout=timeout,
        )
    )
    papers: list[Paper] = []
    for article in root.findall(".//PubmedArticle"):
        citation = article.find("MedlineCitation")
        article_node = citation.find("Article") if citation is not None else None
        if article_node is None:
            continue
        title = " ".join("".join(article_node.find("ArticleTitle").itertext()).split()) if article_node.find("ArticleTitle") is not None else ""
        abstract = " ".join(
            " ".join("".join(node.itertext()).split())
            for node in article_node.findall(".//Abstract/AbstractText")
        )
        authors = []
        for author in article_node.findall(".//AuthorList/Author"):
            name = " ".join(
                part
                for part in (
                    author.findtext("ForeName", default=""),
                    author.findtext("LastName", default=""),
                )
                if part
            )
            if name:
                authors.append(name)
        journal_node = article_node.find("Journal")
        journal = journal_node.findtext("Title", default="") if journal_node is not None else ""
        date_node = article_node.find("ArticleDate")
        if date_node is not None:
            publication_date = "-".join(
                filter(
                    None,
                    [
                        date_node.findtext("Year", default=""),
                        date_node.findtext("Month", default="").zfill(2),
                        date_node.findtext("Day", default="").zfill(2),
                    ],
                )
            )
        else:
            publication_date = article_node.findtext(".//JournalIssue/PubDate/Year", default="")
        doi = ""
        for article_id in article.findall(".//PubmedData/ArticleIdList/ArticleId"):
            if article_id.attrib.get("IdType") == "doi":
                doi = normalize_doi(article_id.text)
                break
        pmid = citation.findtext("PMID", default="") if citation is not None else ""
        papers.append(
            Paper(
                title=title,
                abstract=abstract,
                authors=authors,
                journal=journal,
                publication_date=publication_date,
                doi=doi,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
                document_type="article",
                sources=["pubmed"],
                reading_depth="Abstract only" if abstract else "Metadata only",
            )
        )
    return papers


def _search_europe_pmc(
    query: str, start: str, end: str, limit: int, timeout: int
) -> list[Paper]:
    epmc_query = f"({query}) AND FIRST_PDATE:[{start} TO {end}] AND SRC:MED"
    params = urllib.parse.urlencode(
        {
            "query": epmc_query,
            "format": "json",
            "resultType": "core",
            "pageSize": min(limit, 100),
        }
    )
    items = _json(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + params,
        timeout=timeout,
    ).get("resultList", {}).get("result", [])
    papers: list[Paper] = []
    for item in items:
        author_string = item.get("authorString") or ""
        authors = [part.strip() for part in author_string.rstrip(".").split(",") if part.strip()]
        pmid = item.get("pmid") or (item.get("id") if item.get("source") == "MED" else "")
        abstract = item.get("abstractText") or ""
        publication_types = (item.get("pubTypeList") or {}).get("pubType") or ["article"]
        papers.append(
            Paper(
                title=item.get("title") or "",
                abstract=abstract,
                authors=authors,
                journal=item.get("journalTitle") or "",
                publication_date=(
                    item.get("firstPublicationDate")
                    or item.get("electronicPublicationDate")
                    or str(item.get("pubYear") or "")
                ),
                doi=normalize_doi(item.get("doi")),
                url=(
                    f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
                    if pmid
                    else f"https://europepmc.org/article/{item.get('source', '')}/{item.get('id', '')}"
                ),
                document_type=publication_types[0],
                citation_count=int(item.get("citedByCount") or 0),
                sources=["pubmed", "europe_pmc"],
                reading_depth="Abstract only" if abstract else "Metadata only",
            )
        )
    return papers


def search_pubmed(query: str, start: str, end: str, limit: int, timeout: int) -> list[Paper]:
    try:
        return _search_europe_pmc(query, start, end, limit, timeout)
    except Exception as exc:
        LOGGER.info("Europe PMC 暂不可用，切换 NCBI PubMed：%s", exc)
        return _search_pubmed_ncbi(query, start, end, limit, timeout)


SOURCE_FUNCTIONS = {
    "crossref": search_crossref,
    "openalex": search_openalex,
    "sciencedirect": search_sciencedirect,
    "arxiv": search_arxiv,
    "semantic_scholar": search_semantic_scholar,
    "pubmed": search_pubmed,
}


def collect_sources(config: dict[str, Any], start: str, end: str) -> tuple[list[Paper], dict[str, str]]:
    search = config["search"]
    enabled = search.get("sources") or []
    queries = search["queries"]
    per_source_limit = max(1, int(search.get("per_source_limit", 50)) // max(1, len(queries)))
    timeout = int(search.get("request_timeout_seconds", 30))
    papers: list[Paper] = []
    source_status: dict[str, str] = {}
    sciencedirect_config = config.get("sciencedirect") or {}
    sciencedirect_retrieval_state: dict[str, Any] = {
        "remaining": max(0, int(sciencedirect_config.get("abstract_enrichment_limit", 30)))
    }
    for source in enabled:
        function = SOURCE_FUNCTIONS.get(source)
        if not function:
            source_status[source] = "skipped: unsupported source"
            continue
        api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
        if source == "semantic_scholar" and not api_key:
            source_status[source] = "skipped: missing SEMANTIC_SCHOLAR_API_KEY"
            continue
        elsevier_api_key = os.getenv("ELSEVIER_API_KEY", "").strip()
        if source == "sciencedirect" and not elsevier_api_key:
            source_status[source] = "skipped: missing ELSEVIER_API_KEY"
            continue
        openalex_api_key = os.getenv("OPENALEX_API_KEY", "").strip()
        if source == "openalex" and not openalex_api_key:
            source_status[source] = "skipped: missing OPENALEX_API_KEY"
            continue
        count_before = len(papers)
        errors: list[str] = []
        failure_kind = ""
        skipped_queries = 0
        for query_index, query in enumerate(queries):
            try:
                if source == "openalex":
                    found = function(
                        query,
                        start,
                        end,
                        per_source_limit,
                        timeout,
                        openalex_api_key,
                    )
                elif source == "sciencedirect" and function is search_sciencedirect:
                    found = function(
                        query,
                        start,
                        end,
                        per_source_limit,
                        timeout,
                        elsevier_api_key,
                        os.getenv("ELSEVIER_INST_TOKEN", "").strip(),
                        enrich_abstracts=bool(
                            sciencedirect_config.get("abstract_enrichment", True)
                        ),
                        retrieval_state=sciencedirect_retrieval_state,
                    )
                elif source == "sciencedirect":
                    found = function(
                        query,
                        start,
                        end,
                        per_source_limit,
                        timeout,
                        elsevier_api_key,
                        os.getenv("ELSEVIER_INST_TOKEN", "").strip(),
                    )
                elif source == "semantic_scholar":
                    found = function(query, start, end, per_source_limit, timeout, api_key)
                else:
                    found = function(query, start, end, per_source_limit, timeout)
                papers.extend(found)
            except SourceAuthenticationError as exc:
                errors.append(str(exc))
                failure_kind = "authentication failed"
                skipped_queries = len(queries) - query_index - 1
                LOGGER.warning(
                    "%s 认证失败，跳过其余 %s 个查询：%s",
                    source,
                    skipped_queries,
                    exc,
                )
                break
            except SourceAuthorizationError as exc:
                errors.append(str(exc))
                failure_kind = "authorization failed"
                skipped_queries = len(queries) - query_index - 1
                LOGGER.warning(
                    "%s 未获授权，跳过其余 %s 个查询：%s",
                    source,
                    skipped_queries,
                    exc,
                )
                break
            except SourceRateLimitError as exc:
                errors.append(str(exc))
                failure_kind = "rate limit exceeded"
                skipped_queries = len(queries) - query_index - 1
                LOGGER.warning(
                    "%s 达到用量限制，跳过其余 %s 个查询：%s",
                    source,
                    skipped_queries,
                    exc,
                )
                break
            except SourceConnectionError as exc:
                errors.append(str(exc))
                failure_kind = "connection failed after retries"
                skipped_queries = len(queries) - query_index - 1
                LOGGER.warning(
                    "%s 连接失败，跳过其余 %s 个查询：%s",
                    source,
                    skipped_queries,
                    exc,
                )
                break
            except Exception as exc:  # source-level graceful degradation
                errors.append(str(exc))
                LOGGER.warning("%s 查询失败：%s", source, exc)
        added = len(papers) - count_before
        if added or not errors:
            source_status[source] = f"ok: {added} records"
            if errors:
                source_status[source] += f"; {len(errors)} query errors"
            if skipped_queries:
                source_status[source] += f"; {skipped_queries} queries skipped"
        elif failure_kind:
            source_status[source] = (
                f"error: {failure_kind}; {skipped_queries} queries skipped"
            )
        else:
            source_status[source] = f"error: all {len(errors)} queries failed"
    return papers, source_status
