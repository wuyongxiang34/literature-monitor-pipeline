from __future__ import annotations

import html
import re
import unicodedata

from .models import Paper


DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.I)


def normalize_doi(value: str | None) -> str:
    text = html.unescape(value or "").strip().lower()
    text = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", text)
    match = DOI_RE.search(text)
    return match.group(0).rstrip(".,;:)") if match else ""


def normalize_arxiv(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"^(?:https?://arxiv\.org/(?:abs|pdf)/|arxiv:)", "", text)
    return text.removesuffix(".pdf")


def normalize_openalex(value: str | None) -> str:
    return re.sub(r"^https?://openalex\.org/", "", (value or "").strip(), flags=re.I).lower()


def normalize_title(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def stable_keys(paper: Paper) -> list[str]:
    keys: list[str] = []
    if normalize_doi(paper.doi):
        keys.append(f"doi:{normalize_doi(paper.doi)}")
    if normalize_arxiv(paper.arxiv_id):
        keys.append(f"arxiv:{normalize_arxiv(paper.arxiv_id)}")
    if normalize_openalex(paper.openalex_id):
        keys.append(f"openalex:{normalize_openalex(paper.openalex_id)}")
    if paper.wos_id.strip():
        keys.append(f"wos:{paper.wos_id.strip().casefold()}")
    title = normalize_title(paper.title)
    if title:
        keys.append(f"title:{title}")
    return keys


def canonical_key(paper: Paper) -> str:
    keys = stable_keys(paper)
    return keys[0] if keys else "title:untitled"


def _prefer_text(left: str, right: str) -> str:
    return right if len(right or "") > len(left or "") else left


def merge_papers(left: Paper, right: Paper) -> Paper:
    merged = Paper.from_dict(left.as_dict())
    merged.title = _prefer_text(left.title, right.title)
    merged.abstract = _prefer_text(left.abstract, right.abstract)
    for field in (
        "journal", "publication_date", "doi", "arxiv_id", "openalex_id",
        "semantic_scholar_id", "wos_id", "url", "pdf_url", "document_type",
        "corresponding_author", "corresponding_author_email", "abstract_cn",
    ):
        if not getattr(merged, field) and getattr(right, field):
            setattr(merged, field, getattr(right, field))
    for field in ("authors", "institutions", "keywords", "sources"):
        values = list(dict.fromkeys([*getattr(left, field), *getattr(right, field)]))
        setattr(merged, field, values)
    merged.citation_count = max(left.citation_count, right.citation_count)
    status_rank = {"Unverified": 0, "Indexed": 1, "Confirmed": 2}
    left_rank = next(
        (rank for prefix, rank in status_rank.items() if left.sci_status.startswith(prefix)),
        0,
    )
    right_rank = next(
        (rank for prefix, rank in status_rank.items() if right.sci_status.startswith(prefix)),
        0,
    )
    if right_rank > left_rank:
        merged.sci_status = right.sci_status
    merged.reading_depth = "Abstract only" if merged.abstract else "Metadata only"
    return merged


def deduplicate(papers: list[Paper]) -> tuple[list[Paper], int]:
    records: list[Paper] = []
    key_to_position: dict[str, int] = {}
    duplicates = 0
    for paper in papers:
        matching = next((key_to_position[key] for key in stable_keys(paper) if key in key_to_position), None)
        if matching is None:
            position = len(records)
            records.append(paper)
        else:
            duplicates += 1
            position = matching
            records[position] = merge_papers(records[position], paper)
        for key in stable_keys(records[position]):
            key_to_position[key] = position
    return records, duplicates
