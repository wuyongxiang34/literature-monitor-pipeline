from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from literature_pipeline.wos_import import load_wos_export


class WosImportTests(unittest.TestCase):
    def test_xlsx_with_sci_expanded_evidence_is_confirmed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "savedrecs.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(
                [
                    "Article Title",
                    "Authors",
                    "DOI",
                    "UT (Unique WOS ID)",
                    "Web of Science Index",
                    "Abstract",
                ]
            )
            sheet.append(
                [
                    "Ecosystem services and human well-being",
                    "Smith, J.; Wang, L.",
                    "10.1000/example",
                    "WOS:000000001",
                    "Science Citation Index Expanded (SCI-EXPANDED)",
                    "A study abstract.",
                ]
            )
            workbook.save(path)

            papers = load_wos_export(path)
            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0].wos_id, "WOS:000000001")
            self.assertTrue(papers[0].sci_status.startswith("Confirmed"))

    def test_missing_index_evidence_remains_unverified(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "savedrecs.csv"
            path.write_text(
                "Article Title,DOI,UT (Unique WOS ID)\n"
                "A relevant paper,10.1000/example,WOS:000000002\n",
                encoding="utf-8",
            )
            papers = load_wos_export(path)
            self.assertEqual(len(papers), 1)
            self.assertTrue(papers[0].sci_status.startswith("Unverified"))

    def test_plain_text_full_record_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "savedrecs.txt"
            path.write_text(
                "\n".join(
                    [
                        "FN Clarivate Web of Science",
                        "VR 1.0",
                        "PT J",
                        "AU Smith, J",
                        "TI Ecosystem services and human well-being",
                        "SO Ecosystem Services",
                        "PY 2026",
                        "DI 10.1000/example3",
                        "UT WOS:000000003",
                        "WE Science Citation Index Expanded (SCI-EXPANDED)",
                        "ER",
                        "EF",
                    ]
                ),
                encoding="utf-8",
            )
            papers = load_wos_export(path)
            self.assertEqual(len(papers), 1)
            self.assertTrue(papers[0].sci_status.startswith("Confirmed"))


if __name__ == "__main__":
    unittest.main()
