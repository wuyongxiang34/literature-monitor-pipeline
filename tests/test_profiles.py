from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from literature_pipeline.config import load_config
from literature_pipeline.profiles import (
    ProfileError,
    build_guided_wos,
    build_portable_queries,
    configure_interactively,
    resolve_profile_id,
    save_local_profile,
    set_active_profile,
    validate_advanced_wos,
    validate_profile_document,
    validate_profile_id,
)


def profile_document(**query_overrides):
    query = {
        "mode": "guided",
        "groups": [
            {"name": "climate", "terms": ["climate change", "warming*"]},
            {"name": "health", "terms": ["human health", "disease*"]},
        ],
        "exclude": ["animal model"],
        "advanced_wos": "",
        "portable_queries": [],
        "max_generated_queries": 12,
    }
    query.update(query_overrides)
    return {
        "schema_version": 1,
        "profile": {"id": "climate_health", "name": "Climate and health"},
        "query": query,
        "selection": {"final_selection_count": 5, "lookback_days": 14},
    }


class GuidedQueryTests(unittest.TestCase):
    def test_compiles_groups_phrases_exclusions_and_wildcards(self):
        query = build_guided_wos(profile_document())
        self.assertEqual(
            query,
            'TS=(("climate change" OR warming*) AND ("human health" OR disease*)) '
            'NOT TS=("animal model")',
        )

    def test_portable_query_order_and_cap_are_stable(self):
        document = profile_document(max_generated_queries=3)
        self.assertEqual(
            build_portable_queries(document),
            [
                '"climate change" AND "human health"',
                '"climate change" AND disease',
                'warming AND "human health"',
            ],
        )

    def test_rejects_short_topic_wildcard(self):
        document = profile_document()
        document["query"]["groups"][0]["terms"] = ["ab*"]
        with self.assertRaisesRegex(ProfileError, "至少需要 3 个字符"):
            validate_profile_document(document)


class AdvancedQueryTests(unittest.TestCase):
    def test_accepts_balanced_advanced_query(self):
        value = 'TS=(climat* NEAR/5 health) AND PY=(2025 OR 2026)'
        self.assertEqual(validate_advanced_wos(value), value)

    def test_rejects_invalid_near_distance(self):
        for value in ("TS=(climate NEAR/five health)", "TS=(climate NEAR/ health)"):
            with self.subTest(value=value), self.assertRaisesRegex(ProfileError, "NEAR"):
                validate_advanced_wos(value)

    def test_rejects_same_in_topic_search(self):
        with self.assertRaisesRegex(ProfileError, "SAME"):
            validate_advanced_wos("TS=(climate SAME health)")

    def test_rejects_duplicate_year_conditions(self):
        with self.assertRaisesRegex(ProfileError, "多个 PY"):
            validate_advanced_wos("TS=(climate) AND PY=2025 AND PY=2026")

    def test_complex_advanced_query_requires_portable_queries(self):
        document = profile_document(
            mode="advanced",
            advanced_wos='TI=("climate change") AND TS=(health)',
        )
        with self.assertRaisesRegex(ProfileError, "portable_queries"):
            validate_profile_document(document, ["wos", "crossref"])
        document["query"]["portable_queries"] = ['"climate change" AND health']
        validate_profile_document(document, ["wos", "crossref"])


class ProfileStorageTests(unittest.TestCase):
    def test_profile_id_rejects_paths_and_windows_names(self):
        for value in ("../secret", "My Topic", "con", "x" * 49):
            with self.subTest(value=value), self.assertRaises(ProfileError):
                validate_profile_id(value)

    def test_resolution_precedence_is_explicit_environment_then_active(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config" / "settings.yaml"
            config.parent.mkdir(parents=True)
            document = profile_document()
            save_local_profile(config, document)
            set_active_profile(config, "climate_health")
            environment_document = profile_document()
            environment_document["profile"] = {"id": "env_topic", "name": "Environment"}
            save_local_profile(config, environment_document)
            self.assertEqual(resolve_profile_id(config), "climate_health")
            with patch.dict("os.environ", {"LITERATURE_PROFILE": "env_topic"}):
                self.assertEqual(resolve_profile_id(config), "env_topic")
                self.assertEqual(resolve_profile_id(config, "climate_health"), "climate_health")

    def test_saved_profile_is_valid_yaml(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config" / "settings.yaml"
            config.parent.mkdir(parents=True)
            path = save_local_profile(config, profile_document())
            parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["profile"]["id"], "climate_health")

    def test_legacy_query_config_remains_loadable_with_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config" / "settings.yaml"
            config_path.parent.mkdir(parents=True)
            legacy = {
                "research_profile": {"name": "Legacy Topic", "field": "Legacy Topic"},
                "search": {
                    "candidate_pool_size": 10,
                    "final_selection_count": 2,
                    "lookback_days": 7,
                    "queries": ["climate AND health"],
                    "wos_query": "TS=(climate AND health)",
                    "sources": ["crossref"],
                },
                "scoring": {
                    "topic_gate": 1,
                    "weights": {
                        "topic": 35,
                        "method": 20,
                        "journal": 15,
                        "network": 10,
                        "applied": 10,
                        "archival": 10,
                    },
                },
                "delivery": {"channel": "local"},
                "paths": {
                    "root": "data",
                    "database": "data/literature.db",
                    "excel_export": "data/export.xlsx",
                },
            }
            config_path.write_text(yaml.safe_dump(legacy), encoding="utf-8")
            with self.assertWarns(FutureWarning):
                config = load_config(config_path)
            self.assertEqual(config["research_profile"]["id"], "legacy_topic")
            self.assertEqual(config["search"]["queries"], ["climate AND health"])

    def test_wizard_uses_90_day_default_and_explains_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config" / "settings.yaml"
            config.parent.mkdir(parents=True)
            answers = iter(
                [
                    "seed_island",
                    "Island seed traits",
                    "",
                    "",
                    "seed traits",
                    "seed trait; seed functional trait",
                    "islands",
                    "island; insular",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "n",
                ]
            )
            output: list[str] = []
            path = configure_interactively(
                config, input_fn=lambda _: next(answers), output_fn=output.append
            )
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(document["selection"]["first_run_lookback_days"], 90)
            self.assertEqual(document["selection"]["lookback_days"], 14)
            self.assertTrue(any("不同概念组之间用 AND" in line for line in output))

    def test_wizard_update_preserves_output_and_scoring(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config" / "settings.yaml"
            config.parent.mkdir(parents=True)
            original = profile_document()
            original["selection"]["first_run_lookback_days"] = 90
            original["output"] = {"root": "existing/data"}
            original["scoring"] = {"topic_gate": 7, "method_terms": ["survey"]}
            save_local_profile(config, original)
            answers = iter(
                [
                    "climate_health",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "y",
                    "n",
                ]
            )
            path = configure_interactively(
                config, input_fn=lambda _: next(answers), output_fn=lambda _: None
            )
            updated = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(updated["output"], original["output"])
            self.assertEqual(updated["scoring"], original["scoring"])


if __name__ == "__main__":
    unittest.main()
