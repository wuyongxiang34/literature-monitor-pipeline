from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from literature_pipeline.cli import _configure_console_output
from literature_pipeline.models import Paper
from literature_pipeline.sources import (
    SOURCE_FUNCTIONS,
    SourceAuthenticationError,
    SourceAuthorizationError,
    SourceConnectionError,
    _request,
    collect_sources,
    search_openalex,
    search_pubmed,
    search_sciencedirect,
)


class PubMedFallbackTests(unittest.TestCase):
    def test_uses_ncbi_when_europe_pmc_is_unavailable(self):
        fallback = Paper(
            title="Ecosystem services and human well-being",
            sources=["pubmed", "europe_pmc"],
        )
        with (
            patch(
                "literature_pipeline.sources._search_europe_pmc",
                side_effect=OSError("temporary Europe PMC failure"),
            ),
            patch(
                "literature_pipeline.sources._search_pubmed_ncbi",
                return_value=[fallback],
            ) as ncbi,
        ):
            papers = search_pubmed("ecosystem services", "2026-07-01", "2026-07-26", 10, 30)
        self.assertEqual(papers, [fallback])
        ncbi.assert_called_once()


class SourceResilienceTests(unittest.TestCase):
    def test_console_output_uses_safe_encoding_errors(self):
        class Stream:
            def __init__(self):
                self.options = None

            def reconfigure(self, **kwargs):
                self.options = kwargs

        stdout = Stream()
        stderr = Stream()
        with (
            patch("literature_pipeline.cli.sys.stdout", stdout),
            patch("literature_pipeline.cli.sys.stderr", stderr),
        ):
            _configure_console_output()
        self.assertEqual(stdout.options, {"errors": "backslashreplace"})
        self.assertEqual(stderr.options, {"errors": "backslashreplace"})

    def test_requests_bypass_system_proxy_by_default(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return b"ok"

        with (
            patch.dict("os.environ", {"LITERATURE_USE_SYSTEM_PROXY": "false"}),
            patch("literature_pipeline.sources.urllib.request.build_opener") as build,
        ):
            build.return_value.open.return_value = Response()
            self.assertEqual(_request("https://example.org"), b"ok")
        build.assert_called_once()
        build.return_value.open.assert_called_once()

    def test_openalex_api_key_is_sent_as_query_parameter(self):
        with patch(
            "literature_pipeline.sources._json",
            return_value={"results": []},
        ) as request:
            search_openalex("ecosystem services", "2026-07-01", "2026-07-31", 10, 30, "oa-key")
        self.assertIn("api_key=oa-key", request.call_args.args[0])

    def test_openalex_without_api_key_is_explicitly_skipped(self):
        config = {
            "search": {
                "sources": ["openalex"],
                "queries": ["ecosystem services"],
                "per_source_limit": 10,
                "request_timeout_seconds": 5,
            }
        }
        with patch.dict("os.environ", {"OPENALEX_API_KEY": ""}):
            papers, status = collect_sources(config, "2026-07-01", "2026-07-31")
        self.assertEqual(papers, [])
        self.assertEqual(status["openalex"], "skipped: missing OPENALEX_API_KEY")

    def test_connection_failure_stops_remaining_queries_for_source(self):
        calls: list[tuple] = []

        def unavailable(*args):
            calls.append(args)
            raise SourceConnectionError("proxy connection refused")

        config = {
            "search": {
                "sources": ["openalex"],
                "queries": ["first", "second", "third"],
                "per_source_limit": 30,
                "request_timeout_seconds": 5,
            }
        }
        with (
            patch.dict(SOURCE_FUNCTIONS, {"openalex": unavailable}),
            patch.dict("os.environ", {"OPENALEX_API_KEY": "oa-key"}),
        ):
            papers, status = collect_sources(config, "2026-07-01", "2026-07-31")

        self.assertEqual(papers, [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][-1], "oa-key")
        self.assertIn("2 queries skipped", status["openalex"])

    def test_authentication_failure_stops_remaining_queries(self):
        calls: list[tuple] = []

        def rejected(*args):
            calls.append(args)
            raise SourceAuthenticationError("HTTP 401")

        config = {
            "search": {
                "sources": ["sciencedirect"],
                "queries": ["first", "second", "third"],
                "per_source_limit": 30,
                "request_timeout_seconds": 5,
            }
        }
        with (
            patch.dict(SOURCE_FUNCTIONS, {"sciencedirect": rejected}),
            patch.dict("os.environ", {"ELSEVIER_API_KEY": "els-key"}),
        ):
            papers, status = collect_sources(config, "2026-07-01", "2026-07-31")
        self.assertEqual(papers, [])
        self.assertEqual(len(calls), 1)
        self.assertIn("authentication failed", status["sciencedirect"])
        self.assertIn("2 queries skipped", status["sciencedirect"])

    def test_sciencedirect_uses_official_put_api_and_exact_date_filter(self):
        response = {
            "results": [
                {
                    "title": "Ecosystem services and human well-being",
                    "authors": [{"name": "Ada Example"}],
                    "doi": "10.1016/j.example.2026.1",
                    "publicationDate": "2026-07-21",
                    "sourceTitle": "Ecosystem Services",
                    "uri": "https://www.sciencedirect.com/science/article/pii/S123",
                },
                {
                    "title": "Older article",
                    "publicationDate": "2026-06-30",
                },
            ]
        }
        with patch(
            "literature_pipeline.sources._request",
            return_value=json.dumps(response).encode("utf-8"),
        ) as request:
            papers = search_sciencedirect(
                '"ecosystem services" AND "human well-being"',
                "2026-07-01",
                "2026-07-31",
                15,
                30,
                "test-api-key",
            )

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].authors, ["Ada Example"])
        self.assertEqual(
            papers[0].keywords,
            ["ecosystem services", "human well-being"],
        )
        self.assertTrue(papers[0].sci_status.startswith("Indexed (ScienceDirect"))
        call = request.call_args
        self.assertEqual(call.kwargs["method"], "PUT")
        self.assertEqual(call.kwargs["headers"]["X-ELS-APIKey"], "test-api-key")
        body = json.loads(call.kwargs["data"].decode("utf-8"))
        self.assertEqual(body["display"]["show"], 25)

    def test_sciencedirect_enriches_from_article_retrieval_first(self):
        search_response = {
            "results": [
                {
                    "title": "Ecosystem services and human well-being",
                    "doi": "10.1016/j.example.2026.1",
                    "publicationDate": "2026-07-21",
                }
            ]
        }
        article_response = {
            "full-text-retrieval-response": {
                "coredata": {"dc:description": "<p>Article abstract text.</p>"}
            }
        }

        def response_for(url, **kwargs):
            if "/content/search/sciencedirect" in url:
                return json.dumps(search_response).encode("utf-8")
            if "/content/article/doi/" in url:
                return json.dumps(article_response).encode("utf-8")
            self.fail("Scopus fallback should not run when Article Retrieval succeeds")

        with patch("literature_pipeline.sources._request", side_effect=response_for):
            papers = search_sciencedirect(
                '"ecosystem services" AND "human well-being"',
                "2026-07-01",
                "2026-07-31",
                15,
                30,
                "test-api-key",
                enrich_abstracts=True,
                retrieval_state={"remaining": 10},
            )

        self.assertEqual(papers[0].abstract, "Article abstract text.")
        self.assertEqual(papers[0].reading_depth, "Abstract only")

    def test_sciencedirect_falls_back_to_scopus_abstract_retrieval(self):
        search_response = {
            "results": [
                {
                    "title": "Ecosystem services and human well-being",
                    "doi": "10.1016/j.example.2026.1",
                    "publicationDate": "2026-07-21",
                }
            ]
        }
        scopus_response = {
            "abstracts-retrieval-response": {
                "coredata": {"dc:description": "Scopus abstract text."}
            }
        }
        calls = []

        def response_for(url, **kwargs):
            calls.append(url)
            if "/content/search/sciencedirect" in url:
                return json.dumps(search_response).encode("utf-8")
            if "/content/article/doi/" in url:
                raise SourceAuthorizationError("HTTP 403")
            return json.dumps(scopus_response).encode("utf-8")

        with patch("literature_pipeline.sources._request", side_effect=response_for):
            papers = search_sciencedirect(
                '"ecosystem services" AND "human well-being"',
                "2026-07-01",
                "2026-07-31",
                15,
                30,
                "test-api-key",
                enrich_abstracts=True,
                retrieval_state={"remaining": 10},
            )

        self.assertEqual(papers[0].abstract, "Scopus abstract text.")
        self.assertTrue(any("/content/article/doi/" in url for url in calls))
        self.assertTrue(any("/content/abstract/doi/" in url for url in calls))

    def test_sciencedirect_keeps_metadata_when_both_retrieval_apis_are_blocked(self):
        search_response = {
            "results": [
                {
                    "title": "Ecosystem services and human well-being",
                    "doi": "10.1016/j.example.2026.1",
                    "publicationDate": "2026-07-21",
                }
            ]
        }
        state = {"remaining": 10}

        def response_for(url, **kwargs):
            if "/content/search/sciencedirect" in url:
                return json.dumps(search_response).encode("utf-8")
            if "/content/article/doi/" in url:
                raise SourceAuthorizationError("HTTP 403")
            raise SourceAuthenticationError("HTTP 401")

        with patch("literature_pipeline.sources._request", side_effect=response_for):
            papers = search_sciencedirect(
                '"ecosystem services" AND "human well-being"',
                "2026-07-01",
                "2026-07-31",
                15,
                30,
                "test-api-key",
                enrich_abstracts=True,
                retrieval_state=state,
            )

        self.assertEqual(papers[0].abstract, "")
        self.assertEqual(papers[0].reading_depth, "Metadata only")
        self.assertTrue(state["article_disabled"])
        self.assertTrue(state["scopus_disabled"])

    def test_sciencedirect_without_api_key_is_explicitly_skipped(self):
        config = {
            "search": {
                "sources": ["sciencedirect"],
                "queries": ['"ecosystem services" AND "human well-being"'],
                "per_source_limit": 25,
                "request_timeout_seconds": 5,
            }
        }
        with patch.dict("os.environ", {"ELSEVIER_API_KEY": ""}):
            papers, status = collect_sources(config, "2026-07-01", "2026-07-31")
        self.assertEqual(papers, [])
        self.assertEqual(status["sciencedirect"], "skipped: missing ELSEVIER_API_KEY")


if __name__ == "__main__":
    unittest.main()
