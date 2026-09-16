from __future__ import annotations

import os
import urllib.parse
import unittest
from unittest.mock import patch

from literature_pipeline.wos import search_wos


def _config() -> dict:
    return {
        "wos": {
            "enabled": True,
            "mode": "api",
            "api_type": "starter",
            "api_url": "https://api.clarivate.com/apis/wos-starter/v1",
            "api_key_env": "WEBOFSCIENCE_API_KEY",
            "database": "WOS",
            "sort_field": "LD+D",
            "use_modified_time_span": True,
        },
        "search": {
            "wos_query": 'TS=("ecosystem services" AND "human well-being")',
            "candidate_pool_size": 30,
            "request_timeout_seconds": 30,
        },
    }


class WosStarterApiTests(unittest.TestCase):
    def test_supports_legacy_misspelled_environment_variable_and_maps_records(self):
        response = {
            "metadata": {"total": 1},
            "hits": [
                {
                    "uid": "WOS:001234567800001",
                    "title": "Ecosystem services and human well-being",
                    "types": ["Article"],
                    "source": {
                        "sourceTitle": "Ecosystem Services",
                        "publishYear": 2026,
                        "publishMonth": "SEP",
                    },
                    "names": {"authors": [{"displayName": "Ada Researcher"}]},
                    "identifiers": {"doi": "10.1000/example"},
                    "keywords": {
                        "authorKeywords": ["ecosystem services", "human well-being"]
                    },
                    "links": {"record": "https://www.webofscience.com/example"},
                    "citations": [{"db": "WOS", "count": 12}],
                }
            ],
        }
        captured = {}

        def fake_json(url, **kwargs):
            captured["url"] = url
            captured["headers"] = kwargs["headers"]
            return response

        with (
            patch.dict(
                os.environ,
                {"WEBOFSCIENCE_API_KEY": "", "WEBOFSCIENDE_API_KEY": "legacy-key"},
            ),
            patch("literature_pipeline.wos._json", side_effect=fake_json),
        ):
            papers, status = search_wos(_config(), "2026-08-31", "2026-09-13")

        self.assertTrue(status.startswith("ok: 1"))
        self.assertEqual(papers[0].wos_id, "WOS:001234567800001")
        self.assertEqual(papers[0].doi, "10.1000/example")
        self.assertEqual(papers[0].publication_date, "2026-09")
        self.assertEqual(papers[0].citation_count, 12)
        self.assertTrue(papers[0].sci_status.startswith("Confirmed"))
        self.assertNotIn("legacy-key", captured["url"])
        self.assertEqual(captured["headers"]["X-ApiKey"], "legacy-key")
        query = urllib.parse.parse_qs(urllib.parse.urlparse(captured["url"]).query)
        self.assertEqual(query["modifiedTimeSpan"], ["2026-08-31+2026-09-13"])
        self.assertIn("PY=(2026)", query["q"][0])

    def test_missing_key_is_skipped_without_request(self):
        config = _config()
        config["wos"]["api_key_env"] = "CUSTOM_WOS_KEY"
        with patch.dict(
            os.environ,
            {
                "CUSTOM_WOS_KEY": "",
                "WEBOFSCIENCE_API_KEY": "",
                "WEBOFSCIENDE_API_KEY": "",
            },
        ):
            papers, status = search_wos(config, "2026-08-31", "2026-09-13")
        self.assertEqual(papers, [])
        self.assertTrue(status.startswith("skipped: missing"))


if __name__ == "__main__":
    unittest.main()
