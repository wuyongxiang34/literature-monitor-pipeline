from __future__ import annotations

import argparse
import datetime as dt
import html
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import load_config, resolve_project_path


@dataclass
class ReportCard:
    rank: str
    title: str
    meta: str = ""
    identifiers: str = ""
    reading: str = ""
    link: str = ""
    details: list[tuple[str, str, str]] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)


@dataclass
class ParsedReport:
    title: str
    metadata: list[tuple[str, str]]
    trend: str
    cards: list[ReportCard]
    empty_message: str = ""


@dataclass(frozen=True)
class ReportLink:
    report_date: str
    selected: str
    href: str


DETAIL_MARKERS = {
    "💡": ("一句话", "idea"),
    "🔬": ("方法", "method"),
    "📊": ("关键结果", "result"),
    "🧭": ("点评", "comment"),
}


def _split_label(value: str) -> tuple[str, str]:
    for separator in ("：", ":"):
        if separator in value:
            key, text = value.split(separator, 1)
            return key.strip(), text.strip()
    return "", value.strip()


def parse_report(markdown_text: str) -> ParsedReport:
    title = "今日文献"
    metadata: list[tuple[str, str]] = []
    trend_lines: list[str] = []
    cards: list[ReportCard] = []
    empty_lines: list[str] = []
    section = ""
    current: ReportCard | None = None

    for raw in markdown_text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# "):
            title = line[2:].strip()
            continue
        if line.startswith("## "):
            section = line[3:].strip()
            current = None
            continue
        if line.startswith("### "):
            heading = line[4:].strip()
            left, separator, card_title = heading.partition("|")
            rank_match = re.search(r"#(\d+)", left)
            current = ReportCard(
                rank=rank_match.group(1) if rank_match else str(len(cards) + 1),
                title=(card_title if separator else heading).strip(),
            )
            cards.append(current)
            continue
        if line.startswith("- ") and not section:
            metadata.append(_split_label(line[2:]))
            continue
        if "研究趋势" in section:
            trend_lines.append(line)
            continue
        if "精选" not in section:
            continue
        if current is None:
            empty_lines.append(line)
            continue
        if set(line) <= {"━", "-", "_"}:
            continue
        if line.startswith("DOI:"):
            current.identifiers = line
            continue
        if line.startswith("Reading:"):
            current.reading = line
            continue
        if line.startswith(("http://", "https://")):
            current.link = line
            continue
        if line.startswith("📎"):
            current.link = line[1:].strip()
            continue
        marker = next((item for item in DETAIL_MARKERS if line.startswith(item)), "")
        if marker:
            label, css_name = DETAIL_MARKERS[marker]
            content = line[len(marker) :].strip()
            parsed_label, content = _split_label(content)
            current.details.append((parsed_label or label, content, css_name))
            continue
        if not current.meta:
            current.meta = line
        else:
            current.extra.append(line)

    return ParsedReport(
        title=title,
        metadata=metadata,
        trend=" ".join(trend_lines),
        cards=cards,
        empty_message=" ".join(empty_lines),
    )


def _inline(value: str) -> str:
    safe = html.escape(value, quote=True)
    safe = re.sub(
        r"&lt;ce:italic&gt;(.*?)&lt;/ce:italic&gt;",
        r"<em>\1</em>",
        safe,
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"(https?://[^\s&lt;]+)",
        r'<a href="\1" target="_blank" rel="noreferrer">\1</a>',
        safe,
    )


def _number(value: str) -> str:
    match = re.search(r"\d[\d,]*", value)
    return match.group(0) if match else value


def _report_date(parsed: ParsedReport, report_path: Path) -> str:
    date_match = re.search(r"\d{4}-\d{2}-\d{2}", parsed.title)
    if date_match:
        return date_match.group(0)
    path_match = re.search(r"\d{4}-\d{2}-\d{2}", report_path.as_posix())
    return path_match.group(0) if path_match else report_path.stem


def _selected_count(parsed: ParsedReport) -> str:
    value = next((value for key, value in parsed.metadata if "最终精选" in key), "0")
    return _number(value)


def _history_links(items: list[ReportLink]) -> str:
    if not items:
        return ""
    links = "".join(
        (
            f'<a class="history-item" href="{html.escape(item.href, quote=True)}" '
            f'title="查看 {html.escape(item.report_date)} 日报">'
            f'<span>{html.escape(item.report_date[5:])}</span>'
            f'<strong>精选 {html.escape(item.selected)}</strong></a>'
        )
        for item in items
    )
    return f'<nav class="history-nav" aria-label="往期日报">{links}</nav>'


def _source_badges(metadata: list[tuple[str, str]]) -> str:
    source_value = next(
        (
            value
            for key, value in metadata
            if "数据源" in key or ("sciencedirect:" in value and "crossref:" in value)
        ),
        "",
    )
    badges: list[str] = []
    for item in re.split(r"；|;(?=\s*[A-Za-z_][A-Za-z0-9_]*\s*:)", source_value):
        if ":" not in item:
            continue
        name, status = (part.strip() for part in item.split(":", 1))
        state = "ok" if status.startswith("ok") else "skip" if status.startswith("skipped") else "error"
        short_status = status.replace(" records", "").replace("missing ", "")
        badges.append(
            f'<span class="source {state}"><b>{html.escape(name)}</b> {html.escape(short_status)}</span>'
        )
    return "".join(badges)


def _metric_cards(metadata: list[tuple[str, str]]) -> str:
    wanted = ("候选记录", "去重后", "本次新增", "最终精选")
    labels = {"候选记录": "候选", "去重后": "去重", "本次新增": "新增", "最终精选": "精选"}
    values = {key: value for key, value in metadata}
    cards = []
    for key in wanted:
        value = values.get(key, "—")
        cards.append(
            f'<div class="metric"><span>{labels[key]}</span><strong>{html.escape(_number(value))}</strong></div>'
        )
    return "".join(cards)


def _article_cards(cards: list[ReportCard], empty_message: str) -> str:
    if not cards:
        message = empty_message or "今天没有新增精选文献，数据库已经是最新状态。"
        return f'<div class="empty"><div class="empty-icon">✓</div><p>{_inline(message)}</p></div>'
    output: list[str] = []
    detail_icons = {"idea": "◎", "method": "◇", "result": "↗", "comment": "✦"}
    for card in cards:
        details = "".join(
            (
                f'<div class="detail {css_name}"><span class="detail-icon">{detail_icons[css_name]}</span>'
                f'<div><b>{html.escape(label)}</b><p>{_inline(content)}</p></div></div>'
            )
            for label, content, css_name in card.details
        )
        link = card.link
        title = _inline(card.title)
        if link:
            title = f'<a href="{html.escape(link, quote=True)}" target="_blank" rel="noreferrer">{title}</a>'
        footer_parts = [item for item in (card.identifiers, card.reading) if item]
        footer = "".join(f'<span>{_inline(item)}</span>' for item in footer_parts)
        output.append(
            f"""
            <article class="paper-card">
              <div class="paper-head"><span class="rank">#{html.escape(card.rank)}</span><h2>{title}</h2></div>
              <p class="paper-meta">{_inline(card.meta)}</p>
              <div class="details">{details}</div>
              <div class="paper-foot">{footer}</div>
            </article>
            """
        )
    return "".join(output)


def build_html(
    parsed: ParsedReport,
    report_path: Path,
    history_items: list[ReportLink] | None = None,
) -> str:
    report_date = _report_date(parsed, report_path)
    field_value = next((value for key, value in parsed.metadata if "研究方向" in key), "ES × HWB")
    updated = dt.datetime.fromtimestamp(report_path.stat().st_mtime).strftime("%H:%M")
    trend = parsed.trend or "今天暂无新的主题趋势信号。"
    folder_url = report_path.parent.as_uri()
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html.escape(report_date)} 今日文献</title>
  <style>
    :root {{ color-scheme: light; --ink:#17231d; --muted:#65736b; --green:#206b4f; --mint:#dfeee6; --paper:#ffffff; --line:#dfe7e2; --bg:#f2f5f1; --warm:#f4ead8; }}
    * {{ box-sizing:border-box; }}
    html {{ background:var(--bg); }}
    body {{ margin:0; color:var(--ink); background:linear-gradient(145deg,#eef4ef 0%,#f7f4ed 100%); font-family:"Segoe UI","Microsoft YaHei UI",system-ui,sans-serif; font-size:14px; }}
    a {{ color:inherit; text-decoration:none; }}
    .shell {{ min-height:100vh; padding:18px 18px 28px; }}
    .topbar {{ position:sticky; top:0; z-index:5; margin:-18px -18px 14px; padding:16px 18px 12px; background:rgba(245,248,244,.93); backdrop-filter:blur(14px); border-bottom:1px solid rgba(32,107,79,.12); }}
    .brand-row {{ display:grid; grid-template-columns:max-content minmax(0,1fr) max-content; align-items:center; gap:16px; }}
    .brand {{ display:flex; align-items:center; gap:10px; min-width:max-content; }}
    .mark {{ width:12px; height:28px; border-radius:8px; background:linear-gradient(180deg,#2d8b67,#153f31); box-shadow:0 4px 12px rgba(32,107,79,.25); }}
    .eyebrow {{ color:var(--green); font-size:11px; font-weight:750; letter-spacing:.14em; text-transform:uppercase; }}
    h1 {{ margin:1px 0 0; font-family:Georgia,"Songti SC",serif; font-size:23px; line-height:1.15; font-weight:650; }}
    .history-nav {{ display:flex; justify-content:center; gap:10px; min-width:0; overflow-x:auto; padding:2px 3px 4px; scrollbar-width:thin; scrollbar-color:#bdd2c6 transparent; }}
    .history-item {{ display:flex; flex:1 1 120px; align-items:center; justify-content:space-between; gap:9px; min-width:112px; max-width:175px; padding:8px 11px; border:1px solid rgba(32,107,79,.16); border-radius:11px; background:rgba(255,255,255,.78); color:var(--green); box-shadow:0 3px 12px rgba(25,51,39,.05); transition:transform .15s ease,border-color .15s ease,box-shadow .15s ease; }}
    .history-item:hover {{ transform:translateY(-1px); border-color:#7eb398; box-shadow:0 5px 15px rgba(25,82,58,.11); }}
    .history-item span {{ color:#314a3f; font:650 13px Georgia,serif; }}
    .history-item strong {{ white-space:nowrap; color:var(--muted); font-size:10px; font-weight:650; }}
    .actions {{ display:flex; gap:7px; }}
    .icon-btn {{ display:grid; place-items:center; width:32px; height:32px; border:1px solid var(--line); border-radius:10px; background:#fff; color:var(--green); cursor:pointer; font-size:16px; box-shadow:0 2px 8px rgba(25,51,39,.05); }}
    .subtitle {{ margin:8px 0 0 22px; color:var(--muted); font-size:12px; }}
    .metrics {{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-bottom:12px; }}
    .metric {{ padding:11px 8px 9px; border:1px solid rgba(32,107,79,.10); border-radius:13px; background:rgba(255,255,255,.82); text-align:center; box-shadow:0 5px 18px rgba(26,58,42,.05); }}
    .metric span {{ display:block; color:var(--muted); font-size:11px; }}
    .metric strong {{ display:block; margin-top:3px; color:var(--green); font-family:Georgia,serif; font-size:22px; }}
    .trend {{ margin:0 0 12px; padding:13px 14px; border-radius:14px; background:linear-gradient(135deg,#214d3d,#2b7457); color:white; box-shadow:0 8px 22px rgba(30,84,62,.17); }}
    .trend b {{ display:block; margin-bottom:4px; color:#bfe4d2; font-size:11px; letter-spacing:.08em; }}
    .trend p {{ margin:0; line-height:1.55; }}
    .sources {{ display:flex; flex-wrap:wrap; gap:5px; margin-bottom:14px; }}
    .source {{ padding:4px 7px; border:1px solid var(--line); border-radius:999px; background:rgba(255,255,255,.7); color:var(--muted); font-size:10px; }}
    .source.ok {{ border-color:#bcdcc9; color:#276447; background:#eef8f1; }}
    .source.error {{ border-color:#ebc3bc; color:#9b4438; background:#fff1ee; }}
    .section-title {{ display:flex; align-items:center; gap:8px; margin:16px 1px 9px; font-weight:750; }}
    .section-title:after {{ content:""; height:1px; flex:1; background:var(--line); }}
    .paper-card {{ margin:0 0 12px; padding:15px; border:1px solid var(--line); border-radius:17px; background:rgba(255,255,255,.93); box-shadow:0 8px 24px rgba(32,61,47,.07); }}
    .paper-head {{ display:flex; align-items:flex-start; gap:9px; }}
    .rank {{ flex:0 0 auto; padding:4px 7px; border-radius:8px; background:var(--mint); color:var(--green); font:700 11px Georgia,serif; }}
    .paper-card h2 {{ margin:0; font-family:Georgia,"Songti SC",serif; font-size:16px; line-height:1.4; font-weight:650; }}
    .paper-card h2 a:hover {{ color:var(--green); }}
    .paper-meta {{ margin:8px 0 11px; color:var(--muted); font-size:11.5px; line-height:1.5; }}
    .detail {{ display:flex; gap:9px; padding:9px 0; border-top:1px solid #edf1ee; }}
    .detail-icon {{ display:grid; place-items:center; width:22px; height:22px; flex:0 0 22px; border-radius:7px; color:var(--green); background:#edf6f0; font-size:12px; }}
    .detail b {{ color:#496057; font-size:11px; }}
    .detail p {{ margin:2px 0 0; line-height:1.55; }}
    .detail.result .detail-icon {{ background:var(--warm); color:#8a5a16; }}
    .paper-foot {{ display:flex; flex-direction:column; gap:4px; margin-top:9px; padding-top:9px; border-top:1px dashed var(--line); color:#718078; font-size:10px; word-break:break-word; }}
    .paper-foot a {{ color:var(--green); }}
    .empty {{ padding:32px 18px; border:1px dashed #bfd0c5; border-radius:17px; background:rgba(255,255,255,.7); text-align:center; color:var(--muted); }}
    .empty-icon {{ display:grid; place-items:center; width:38px; height:38px; margin:0 auto 10px; border-radius:50%; background:var(--mint); color:var(--green); font-size:20px; }}
    .footer {{ display:flex; justify-content:space-between; gap:10px; margin:18px 2px 0; color:#829087; font-size:10px; }}
    .footer a {{ color:var(--green); }}
    @media (max-width:760px) {{
      .brand-row {{ grid-template-columns:minmax(0,1fr) max-content; gap:8px 10px; }}
      .brand {{ grid-column:1; grid-row:1; }}
      .actions {{ grid-column:2; grid-row:1; }}
      .history-nav {{ grid-column:1 / -1; grid-row:2; justify-content:flex-start; margin-top:3px; }}
      .history-item {{ flex:1 1 104px; min-width:104px; }}
    }}
    @media (max-width:430px) {{ .shell {{ padding:14px; }} .topbar {{ margin:-14px -14px 12px; padding:14px; }} .metrics {{ gap:5px; }} .metric strong {{ font-size:19px; }} }}
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div class="brand-row">
        <div class="brand"><span class="mark"></span><div><div class="eyebrow">Daily Research Brief</div><h1>{html.escape(report_date)} 文献速览</h1></div></div>
        {_history_links(history_items or [])}
        <div class="actions"><button class="icon-btn" onclick="location.reload()" title="读取最新内容">↻</button><a class="icon-btn" href="{html.escape(folder_url, quote=True)}" title="报告目录">⌂</a></div>
      </div>
      <p class="subtitle">{_inline(field_value)} · 更新于 {html.escape(updated)}</p>
    </header>
    <section class="metrics">{_metric_cards(parsed.metadata)}</section>
    <section class="trend"><b>TODAY'S SIGNAL</b><p>{_inline(trend)}</p></section>
    <section class="sources">{_source_badges(parsed.metadata)}</section>
    <div class="section-title">今日精选</div>
    <section>{_article_cards(parsed.cards, parsed.empty_message)}</section>
    <footer class="footer"><span>检索完成后更新 · 打开时读取最新内容</span><a href="{html.escape(folder_url, quote=True)}">{html.escape(report_path.name)}</a></footer>
  </main>
</body>
</html>
"""


def _write_html(output_path: Path, content: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(output_path)


def _data_root_for_report(report_path: Path) -> Path | None:
    return next((parent.parent for parent in report_path.parents if parent.name == "papers"), None)


def _report_sort_key(report_path: Path) -> tuple[str, float]:
    date_match = re.search(r"\d{4}-\d{2}-\d{2}", report_path.as_posix())
    return (date_match.group(0) if date_match else "", report_path.stat().st_mtime)


def list_recent_reports(data_root: Path, limit: int = 5) -> list[Path]:
    reports = [item.resolve() for item in data_root.glob("papers/*/*/*/report/Daily_Report.md")]
    return sorted(reports, key=_report_sort_key, reverse=True)[: max(1, limit)]


def render_widget(report_path: Path, output_path: Path, history_limit: int = 4) -> Path:
    report_path = report_path.resolve()
    if not report_path.is_file() or report_path.suffix.casefold() != ".md":
        raise FileNotFoundError(f"Markdown report not found: {report_path}")
    output_path = output_path.resolve()
    data_root = _data_root_for_report(report_path)
    recent_reports = list_recent_reports(data_root, history_limit + 1) if data_root else [report_path]
    if report_path not in recent_reports:
        recent_reports = [report_path, *recent_reports[:history_limit]]

    parsed_reports = {
        item: parse_report(item.read_text(encoding="utf-8-sig")) for item in recent_reports
    }
    archive_dir = output_path.parent / "reports"
    targets = {
        item: (
            output_path
            if item == report_path
            else archive_dir / f"{_report_date(parsed_reports[item], item)}.html"
        )
        for item in recent_reports
    }

    for item in recent_reports:
        navigation = [
            ReportLink(
                report_date=_report_date(parsed_reports[other], other),
                selected=_selected_count(parsed_reports[other]),
                href=targets[other].as_uri(),
            )
            for other in recent_reports
            if other != item
        ][:history_limit]
        _write_html(targets[item], build_html(parsed_reports[item], item, navigation))
    return output_path


def find_latest_report(data_root: Path) -> Path:
    reports = list_recent_reports(data_root, 1)
    if not reports:
        raise FileNotFoundError(f"No Daily_Report.md found below {data_root}")
    return reports[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the latest literature Markdown report as a desktop card.")
    parser.add_argument("--config", type=Path, default=Path("config/settings.yaml"))
    parser.add_argument("--profile", help="研究主题 ID")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    config = load_config(args.config, profile_id=args.profile)
    data_root = resolve_project_path(config, config["paths"]["root"])
    report_path = args.report.resolve() if args.report else find_latest_report(data_root)
    widget_config = config.get("desktop_widget") or {}
    configured_output = widget_config.get(
        "output", f"Literature_Monitor_Data/{config['research_profile']['id']}/desktop_widget/latest.html"
    )
    output_path = args.output.resolve() if args.output else resolve_project_path(config, configured_output)
    history_limit = int(widget_config.get("history_reports", 4))
    print(render_widget(report_path, output_path, history_limit=history_limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
