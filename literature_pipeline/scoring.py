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
WILDCARD_RE = re.compile(r"[*?$]")


def _term_matches(text: str, term: str) -> bool:
    value = str(term or "").strip().strip('"').casefold()
    corpus = text.casefold()
    if not value:
        return False
    if not WILDCARD_RE.search(value):
        return value in corpus
    pattern: list[str] = []
    for character in value:
        if character == "*":
            pattern.append(r"\S*")
        elif character == "?":
            pattern.append(r"\S")
        elif character == "$":
            pattern.append(r"\S?")
        else:
            pattern.append(re.escape(character))
    return re.search("".join(pattern), corpus) is not None


def _count_terms(text: str, terms: list[str]) -> tuple[int, list[str]]:
    matched = [term for term in terms if _term_matches(text, term)]
    return len(matched), matched


def _concept_groups(config: dict[str, Any]) -> list[tuple[str, list[str]]]:
    profile_groups = (config.get("profile_query") or {}).get("groups") or []
    if profile_groups:
        return [
            (
                str(group.get("name") or f"概念组 {index}"),
                [str(term) for term in (group.get("terms") or []) if str(term).strip()],
            )
            for index, group in enumerate(profile_groups, 1)
        ]
    legacy_groups = (config.get("keywords") or {}).get("required_concept_groups", [])
    return [
        (f"概念组 {index}", [str(term) for term in group if str(term).strip()])
        for index, group in enumerate(legacy_groups, 1)
    ]


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
    return all(any(_term_matches(text, term) for term in group) for group in groups)


def score_paper(paper: Paper, config: dict[str, Any]) -> Paper:
    scoring = config["scoring"]
    weights = {key: int(value) for key, value in scoring["weights"].items()}
    keywords = config.get("keywords") or {}
    text = " ".join(
        [paper.title, paper.abstract, paper.journal, *paper.keywords, *paper.institutions]
    )

    include_count, include_terms = _count_terms(text, keywords.get("include", []))
    core_groups = _concept_groups(config)
    group_hits = sum(
        any(_term_matches(text, term) for term in terms) for _, terms in core_groups
    )
    if core_groups:
        topic_ratio = group_hits / len(core_groups)
        topic = round(weights["topic"] * topic_ratio)
        topic = min(
            weights["topic"],
            topic + _scaled(include_count, 5, round(weights["topic"] * 0.2)),
        )
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


def score_and_select_detailed(
    papers: list[Paper], config: dict[str, Any]
) -> tuple[list[Paper], list[Paper], dict[str, Any], list[dict[str, Any]]]:
    excludes = [
        str(term) for term in (config.get("keywords") or {}).get("exclude", []) if str(term).strip()
    ]
    groups = _concept_groups(config)
    gate = int(config["scoring"].get("topic_gate", 10))
    summary: dict[str, Any] = {
        "excluded_by_terms": 0,
        "missing_concept_groups": {name: 0 for name, _ in groups},
        "below_topic_gate": 0,
    }
    scored: list[Paper] = []
    rejected: list[dict[str, Any]] = []

    for paper in papers:
        corpus = " ".join([paper.title, paper.abstract, *paper.keywords])
        exclude_hits = [term for term in excludes if _term_matches(corpus, term)]
        if exclude_hits:
            summary["excluded_by_terms"] += 1
            rejected.append(
                {
                    "reason": "excluded_by_terms",
                    "matched_exclude_terms": exclude_hits,
                    "missing_concept_groups": [],
                    "paper": paper.as_dict(),
                }
            )
            continue

        missing_groups = [
            name
            for name, terms in groups
            if not any(_term_matches(corpus, term) for term in terms)
        ]
        if missing_groups:
            for name in missing_groups:
                summary["missing_concept_groups"][name] += 1
            rejected.append(
                {
                    "reason": "missing_concept_groups",
                    "matched_exclude_terms": [],
                    "missing_concept_groups": missing_groups,
                    "paper": paper.as_dict(),
                }
            )
            continue

        score_paper(paper, config)
        if paper.scores["topic"] < gate:
            summary["below_topic_gate"] += 1
            rejected.append(
                {
                    "reason": "below_topic_gate",
                    "matched_exclude_terms": [],
                    "missing_concept_groups": [],
                    "topic_score": paper.scores["topic"],
                    "topic_gate": gate,
                    "paper": paper.as_dict(),
                }
            )
            continue
        scored.append(paper)

    scored.sort(key=lambda item: (item.score_total, item.publication_date), reverse=True)
    limit = int(config["search"]["final_selection_count"])
    summary["eligible"] = len(scored)
    summary["rejected"] = len(rejected)
    return scored, scored[:limit], summary, rejected


def score_and_select(papers: list[Paper], config: dict[str, Any]) -> tuple[list[Paper], list[Paper]]:
    scored, selected, _, _ = score_and_select_detailed(papers, config)
    return scored, selected


def validate_scores(papers: list[Paper], config: dict[str, Any]) -> None:
    weights = config["scoring"]["weights"]
    for paper in papers:
        for dimension, cap in weights.items():
            value = paper.scores.get(dimension)
            if value is None or not 0 <= value <= int(cap):
                raise ValueError(f"{paper.title}: {dimension} 评分 {value} 超出 0-{cap}")
        if paper.score_total != sum(paper.scores.values()):
            raise ValueError(f"{paper.title}: 总分与六维分数之和不一致")
