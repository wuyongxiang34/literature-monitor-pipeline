from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from literature_pipeline.cli import build_parser, main


class CliTests(unittest.TestCase):
    def test_run_lookback_override_is_applied_in_memory(self):
        config = {"marker": "original"}
        summary = {"status": "SUCCESS"}
        with (
            patch("literature_pipeline.cli.load_config", return_value=config),
            patch("literature_pipeline.cli.run_pipeline", return_value=summary) as run,
            patch("builtins.print"),
        ):
            result = main(
                [
                    "--config",
                    str(Path("config/settings.yaml")),
                    "--profile",
                    "island",
                    "run",
                    "--lookback-days",
                    "365",
                    "--no-delivery",
                ]
            )
        self.assertEqual(result, 0)
        self.assertEqual(run.call_args.args[0]["_lookback_override"], 365)

    def test_run_rejects_non_positive_lookback(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["run", "--lookback-days", "0"])


if __name__ == "__main__":
    unittest.main()
