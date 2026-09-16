from __future__ import annotations

import re
from typing import Any

from .models import Paper


CLASSIFICATIONS = (
    (80, "A_核心主线"),
    (70, "B_章节支撑"),
    (60, "C_工程背景"),
    (50, "D_方法借鉴"),
    (0, "E_暂存低优先"),
)


def _contains(text: str, term: str) -> bool:
    return term.casefold() in text.casefold()


def _count_terms(text: str, terms: list[str]) -> tuple[int, list[str]]:
    matched = [term for term in terms if term and _contains(text, term)]
    return len(matched), matched


def _scaled(count: int, saturation: int, cap: int) -> int:
    if count <= 0 or cap <= 0:
        return 0
    return min(cap, round(cap * min(1.0, count / max(1, saturation))))


def _journal_score(paper: Paper, config: dict[str, Any], cap: int) -> int:
    rules = (config.get("scoring") or {}).get("journal_tiers") or {}
    journal = paper.journal.casefold()
    if any(name.casefold() in journal for name in rules.get("tier_1", []) if name):
        return cap
    if any(name.casefold() in journal for name in rules.get("tier_2", []) if name):
        return round(cap * 0.8)
    if paper.journal:
        return round(cap * 0.5)
    return round(cap * 0.2) if "arxiv" in paper.sources else 0


def _classification(total: int) -> str:
    return next(label for threshold, label in CLASSIFICATIONS if total >= threshold)


def _required_groups_satisfied(text: str, groups: list[list[str]]) -> bool:
    return all(any(_contains(text, term) for term in group if term) for group in groups)


def score_paper(paper: Paper, config: dict[str, Any]) -> Paper:
    scoring = config["scoring"]
    weights = {key: int(value) for key, value in scoring["weights"].items()}
    keywords = config.get("keywords") or {}
    text = " ".join(
        [paper.title, paper.abstract, paper.journal, *paper.keywords, *paper.institutions]
    )

    include_count, include_terms = _count_terms(text, keywords.get("include", []))
    core_groups = keywords.get("required_concept_groups", [])
    group_hits = 0
    for group in core_groups:
        if any(_contains(text, term) for term in group):
            group_hits += 1
    if core_groups:
        topic_ratio = group_hits / len(core_groups)
        topic = round(weights["topic"] * topic_ratio)
        topic = min(weights["topic"], topic + _scaled(include_count, 5, round(weights["topic"] * 0.2)))
    else:
        topic = _scaled(include_count, 4, weights["topic"])

    method_count, _ = _count_terms(text, scoring.get("method_terms", []))
    method = _scaled(method_count, 4, weights["method"])
    if paper.abstract and method == 0:
        method = round(weights["method"] * 0.2)

    journal = _journal_score(paper, config, weights["journal"])

    tracked = config.get("important_authors_or_orgs") or []
    network_count, _ = _count_terms(text + " " + " ".join(paper.authors), tracked)
    network = _scaled(network_count, 2, weights["network"])

    applied_count, _ = _count_terms(text, scoring.get("applied_terms", []))
    applied = _scaled(applied_count, 3, weights["applied"])

    archival = 0
    if paper.document_type.casefold() in {"review", "systematic-review", "meta-analysis"}:
        archival += round(weights["archival"] * 0.6)
    if len(paper.abstract) >= 500:
        archival += round(weights["archival"] * 0.25)
    if paper.citation_count >= 20:
        archival += round(weights["archival"] * 0.25)
    archival = min(weights["archival"], archival)

    paper.matched_terms = include_terms
    paper.scores = {
        "topic": min(weights["topic"], topic),
        "method": min(weights["method"], method),
        "journal": min(weights["journal"], journal),
        "network": min(weights["network"], network),
        "applied": min(weights["applied"], applied),
        "archival": min(weights["archival"], archival),
    }
    paper.score_total = sum(paper.scores.values())
    paper.classification = _classification(paper.score_total)
    paper.reading_depth = "Abstract only" if paper.abstract else "Metadata only"
    paper.score_rationale = (
        f"主题命中 {len(include_terms)} 个关键词、{group_hits}/{len(core_groups) or 1} 个核心概念组；"
        f"方法信号 {method_count} 个；网络信号 {network_count} 个；应用信号 {applied_count} 个。"
    )
    return paper


def score_and_select(papers: list[Paper], config: dict[str, Any]) -> tuple[list[Paper], list[Paper]]:
    excludes = [term.casefold() for term in (config.get("keywords") or {}).get("exclude", [])]
    required_groups = (config.get("keywords") or {}).get("required_concept_groups", [])
    gate = int(config["scoring"].get("topic_gate", 10))
    scored: list[Paper] = []
    for paper in papers:
        corpus = " ".join([paper.title, paper.abstract, *paper.keywords]).casefold()
        if any(term and term in corpus for term in excludes):
            continue
        if required_groups and not _required_groups_satisfied(corpus, required_groups):
            continue
        score_paper(paper, config)
        if paper.scores["topic"] >= gate:
            scored.append(paper)
    scored.sort(key=lambda item: (item.score_total, item.publication_date), reverse=True)
    limit = int(config["search"]["final_selection_count"])
    return scored, scored[:limit]


def validate_scores(papers: list[Paper], config: dict[str, Any]) -> None:
    weights = config["scoring"]["weights"]
    for paper in papers:
        for dimension, cap in weights.items():
            value = paper.scores.get(dimension)
            if value is None or not 0 <= value <= int(cap):
                raise ValueError(f"{paper.title}: {dimension} 评分 {value} 超出 0-{cap}")
        if paper.score_total != sum(paper.scores.values()):
            raise ValueError(f"{paper.title}: 总分与六维分数之和不一致")
