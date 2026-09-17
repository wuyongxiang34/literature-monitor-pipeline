from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from literature_pipeline.doctor import collect_diagnostics, print_diagnostics


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DoctorTests(unittest.TestCase):
    def test_reports_credential_presence_without_printing_secret(self):
        sentinel = "DO_NOT_PRINT_SENTINEL"
        with patch.dict("os.environ", {"OPENALEX_API_KEY": sentinel}, clear=False):
            result = collect_diagnostics(
                PROJECT_ROOT / "config" / "settings.yaml", "es_hwb"
            )
            output = io.StringIO()
            with redirect_stdout(output):
                print_diagnostics(
                    PROJECT_ROOT / "config" / "settings.yaml", "es_hwb"
                )
        self.assertTrue(result["credentials"]["OpenAlex"])
        self.assertNotIn(sentinel, output.getvalue())
        self.assertIn("OpenAlex 凭据：已配置", output.getvalue())


if __name__ == "__main__":
    unittest.main()
