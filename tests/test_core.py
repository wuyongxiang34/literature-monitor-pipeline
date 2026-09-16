from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from literature_pipeline.config import load_config
from literature_pipeline.digest import build_digest
from literature_pipeline.models import Paper
from literature_pipeline.normalize import deduplicate, normalize_doi
from literature_pipeline.scoring import score_and_select, score_paper, validate_scores
from literature_pipeline.storage import LiteratureDatabase


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class NormalizeTests(unittest.TestCase):
    def test_normalize_doi(self):
        self.assertEqual(
            normalize_doi("https://doi.org/10.1016/J.ECOLIND.2026.100001."),
            "10.1016/j.ecolind.2026.100001",
        )

    def test_deduplicate_merges_richer_metadata(self):
        first = Paper(title="Ecosystem Services and Well-Being", doi="10.1/example", sources=["crossref"])
        second = Paper(
            title="Ecosystem Services and Well-Being",
            doi="https://doi.org/10.1/example",
            abstract="A detailed abstract.",
            sources=["openalex"],
        )
        unique, duplicate_count = deduplicate([first, second])
        self.assertEqual(duplicate_count, 1)
        self.assertEqual(len(unique), 1)
        self.assertEqual(unique[0].abstract, "A detailed abstract.")
        self.assertEqual(set(unique[0].sources), {"crossref", "openalex"})


class ScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config(PROJECT_ROOT / "config" / "settings.yaml")

    def test_scores_are_capped_and_total_is_recalculated(self):
        paper = Paper(
            title="Ecosystem services and human well-being through policy and management",
            abstract=(
                "We use a structural equation model and GIS survey analysis. "
                "Results show strong associations with quality of life."
            ),
            journal="Ecosystem Services",
        )
        score_paper(paper, self.config)
        validate_scores([paper], self.config)
        self.assertEqual(paper.score_total, sum(paper.scores.values()))
        self.assertLessEqual(paper.score_total, 100)
        self.assertGreaterEqual(paper.scores["topic"], self.config["scoring"]["topic_gate"])

    def test_both_required_concept_groups_must_be_present(self):
        only_es = Paper(
            title="Mapping ecosystem services with GIS",
            abstract="We assess regulating and provisioning services.",
        )
        scored, selected = score_and_select([only_es], self.config)
        self.assertEqual(scored, [])
        self.assertEqual(selected, [])

    def test_full_text_query_terms_can_satisfy_sciencedirect_topic_gate(self):
        paper = Paper(
            title="A publisher-platform result",
            keywords=["ecosystem services", "human well-being"],
            sources=["sciencedirect"],
        )
        scored, _ = score_and_select([paper], self.config)
        self.assertEqual(scored, [paper])


class DatabaseTests(unittest.TestCase):
    def test_unique_doi_updates_instead_of_duplicating(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "literature.db"
            with LiteratureDatabase(path) as database:
                first = Paper(
                    title="A paper",
                    doi="10.1000/example",
                    sources=["crossref"],
                    sci_status="Unverified",
                )
                second = Paper(
                    title="A paper with richer title",
                    doi="https://doi.org/10.1000/example",
                    abstract="Richer metadata.",
                    sources=["wos"],
                    sci_status="Confirmed (SCI-EXPANDED)",
                )
                _, was_new_first = database.upsert_paper(first, "run1", "2026-07-26")
                _, was_new_second = database.upsert_paper(second, "run2", "2026-07-27")
                count = database.connection.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
                status = database.connection.execute("SELECT sci_status FROM papers").fetchone()[0]
            self.assertTrue(was_new_first)
            self.assertFalse(was_new_second)
            self.assertEqual(count, 1)
            self.assertTrue(status.startswith("Confirmed"))


class DigestTests(unittest.TestCase):
    def test_no_new_records_is_not_reported_as_topic_rejection(self):
        digest = build_digest(
            "2026-07-31",
            "es_hwb",
            "生态系统服务与人类福祉",
            "生态系统服务与人类福祉",
            [],
            retrieved=100,
            deduplicated=90,
            new_count=0,
            source_status={"openalex": "ok: 10 records"},
        )
        self.assertIn("均已存在于数据库", digest)
        self.assertNotIn("没有达到主题门槛的新文献", digest)


if __name__ == "__main__":
    unittest.main()
