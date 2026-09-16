from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from literature_pipeline.desktop_widget import find_latest_report, parse_report, render_widget


SAMPLE_REPORT = """# 2026-08-23 ES–HWB 文献日报

- 研究方向：生态系统服务与人类福祉
- 候选记录：131
- 去重后：105
- 本次新增：1
- 最终精选：1
- 数据源状态：sciencedirect: ok: 14 records；openalex: skipped: missing key；wos: ok: 30 WoS Core records (Starter API; 114 matched)

## 今日研究趋势

入选文献的主要主题信号：ecosystem services、human well-being。

## 今日精选

### 🏅 #1 | Adaptive traits of <ce:italic>Solanum</ce:italic>

Journal for Nature Conservation, 2026-08-23 | A. Author | ⭐ 5.3/10
DOI: 10.1016/example | WoS ID: Not available
Reading: Metadata only | Index status: Indexed

💡 一句话：A useful paper.

🔬 方法：Survey and model.

📊 关键结果：Results show a positive association.

🧭 点评：Matches both core concept groups.

📎 https://doi.org/10.1016/example
"""


class DesktopWidgetTests(unittest.TestCase):
    def test_parses_report_cards(self):
        parsed = parse_report(SAMPLE_REPORT)
        self.assertEqual(parsed.cards[0].rank, "1")
        self.assertIn("Solanum", parsed.cards[0].title)
        self.assertEqual(parsed.cards[0].link, "https://doi.org/10.1016/example")

    def test_renders_markdown_as_styled_html(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "papers/2026/08/2026-08-23_ES_HWB/report/Daily_Report.md"
            report.parent.mkdir(parents=True)
            report.write_text(SAMPLE_REPORT, encoding="utf-8")
            older_report = root / "papers/2026/08/2026-08-22_ES_HWB/report/Daily_Report.md"
            older_report.parent.mkdir(parents=True)
            older_report.write_text(
                SAMPLE_REPORT.replace("2026-08-23", "2026-08-22").replace(
                    "最终精选：1", "最终精选：3"
                ),
                encoding="utf-8",
            )
            output = root / "desktop_widget/latest.html"
            render_widget(report, output)
            content = output.read_text(encoding="utf-8")
            self.assertIn('class="paper-card"', content)
            self.assertIn("<em>Solanum</em>", content)
            self.assertNotIn("<ce:italic>", content)
            self.assertNotIn('http-equiv="refresh"', content)
            self.assertNotIn("setInterval", content)
            self.assertIn("打开时读取最新内容", content)
            self.assertIn("Starter API; 114 matched", content)
            self.assertIn('class="history-nav"', content)
            self.assertIn("08-22", content)
            self.assertIn("精选 3", content)
            archive_page = output.parent / "reports/2026-08-22.html"
            self.assertTrue(archive_page.is_file())
            archive_content = archive_page.read_text(encoding="utf-8")
            self.assertIn("2026-08-22 文献速览", archive_content)
            self.assertIn("08-23", archive_content)
            self.assertEqual(find_latest_report(root), report)


if __name__ == "__main__":
    unittest.main()
