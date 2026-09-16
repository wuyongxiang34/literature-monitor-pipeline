from __future__ import annotations

from collections import Counter
from typing import Any

from .models import Paper


def _best_link(paper: Paper) -> str:
    if paper.doi:
        return f"https://doi.org/{paper.doi}"
    return paper.url or paper.pdf_url or "Not available"


def build_digest(
    run_date: str,
    profile_id: str,
    profile_name: str,
    field: str,
    selected: list[Paper],
    *,
    retrieved: int,
    deduplicated: int,
    new_count: int,
    source_status: dict[str, str],
) -> str:
    source_line = "；".join(f"{source}: {status}" for source, status in source_status.items())
    keyword_counts = Counter(term for paper in selected for term in paper.matched_terms)
    trend = "、".join(term for term, _ in keyword_counts.most_common(5)) or "暂无足够数据"
    lines = [
        f"# {run_date} {profile_name} 文献日报",
        "",
        f"- 研究主题：{profile_name} (`{profile_id}`)",
        f"- 研究方向：{field}",
        f"- 候选记录：{retrieved}",
        f"- 去重后：{deduplicated}",
        f"- 本次新增：{new_count}",
        f"- 最终精选：{len(selected)}",
        f"- 数据源状态：{source_line}",
        "",
        "## 今日研究趋势",
        "",
        f"入选文献的主要主题信号：{trend}。",
        "",
    ]
    if not selected:
        if new_count == 0:
            empty_message = "本次检索记录均已存在于数据库中，因此没有新增文献需要重复精选。"
        else:
            empty_message = "本次新增记录中没有达到主题门槛的文献。"
        lines.extend(["## 今日精选", "", empty_message, ""])
        return "\n".join(lines)

    lines.extend(["## 今日精选", ""])
    for rank, paper in enumerate(selected, 1):
        authors = ", ".join(paper.authors[:3])
        if len(paper.authors) > 3:
            authors += " et al."
        lines.extend(
            [
                f"### 🏅 #{rank} | {paper.title}",
                "",
                (
                    f"{paper.journal or 'Unknown source'}, {paper.publication_date or 'Unknown date'}"
                    f" | {authors or 'Unknown author'} | ⭐ {paper.score_total / 10:.1f}/10"
                    f" | 分流：{paper.classification}"
                ),
                f"DOI: {paper.doi or 'Not available'} | WoS ID: {paper.wos_id or 'Not available'}",
                f"Reading: {paper.reading_depth} | Index status: {paper.sci_status}",
                "",
                f"💡 一句话：{paper.title}",
                "",
                f"🔬 方法：{_method_summary(paper)}",
                "",
                f"📊 关键结果：{_result_summary(paper)}",
                "",
                f"🧭 点评：{paper.score_rationale}",
                "",
                f"📎 {_best_link(paper)}",
                "",
                "━━━━━━━━━━━━━━━━━━━━",
                "",
            ]
        )
    return "\n".join(lines)


def _method_summary(paper: Paper) -> str:
    if not paper.abstract:
        return "仅获得元数据，需阅读全文确认研究设计与分析方法。"
    sentences = [sentence.strip() for sentence in paper.abstract.replace("\n", " ").split(".") if sentence.strip()]
    method_markers = ("method", "model", "survey", "experiment", "analysis", "assessment", "framework")
    for sentence in sentences:
        if any(marker in sentence.casefold() for marker in method_markers):
            return sentence[:400] + ("…" if len(sentence) > 400 else "")
    return "摘要未明确标注方法句，需全文核验。"


def _result_summary(paper: Paper) -> str:
    if not paper.abstract:
        return "元数据未提供摘要，无法可靠提取结果。"
    sentences = [sentence.strip() for sentence in paper.abstract.replace("\n", " ").split(".") if sentence.strip()]
    result_markers = ("result", "found", "show", "indicat", "increase", "decrease", "associated")
    for sentence in sentences:
        if any(marker in sentence.casefold() for marker in result_markers):
            return sentence[:500] + ("…" if len(sentence) > 500 else "")
    return "摘要存在，但自动流程未识别到可安全引用的明确结果句。"
