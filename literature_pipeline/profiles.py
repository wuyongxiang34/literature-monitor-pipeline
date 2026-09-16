from __future__ import annotations

import itertools
import os
import re
from pathlib import Path
from typing import Any, Callable

import yaml


PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
NON_WOS_SOURCES = {
    "arxiv", "crossref", "openalex", "pubmed", "sciencedirect", "semantic_scholar"
}
FIELD_TAG_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,5})\s*=", re.I)
OPERATOR_RE = re.compile(r"\b(?:AND|OR|NOT|NEAR(?:/\d+)?|SAME)\b", re.I)
WILDCARD_RE = re.compile(r"[*?$]")


class ProfileError(ValueError):
    """Raised when a research profile is missing or invalid."""


def profile_directories(config_path: Path) -> tuple[Path, Path]:
    root = config_path.resolve().parent / "profiles"
    return root / "local", root / "examples"


def active_profile_path(config_path: Path) -> Path:
    return config_path.resolve().parent / "active_profile.yaml"


def validate_profile_id(profile_id: str) -> str:
    value = str(profile_id or "").strip()
    if not PROFILE_ID_RE.fullmatch(value):
        raise ProfileError("profile.id 只能包含小写字母、数字、-、_，长度为 1-48")
    if value.casefold() in WINDOWS_RESERVED:
        raise ProfileError(f"profile.id 不能使用 Windows 保留名称：{value}")
    return value


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            value = yaml.safe_load(handle) or {}
    except OSError as exc:
        raise ProfileError(f"无法读取研究主题：{path}；{exc}") from exc
    if not isinstance(value, dict):
        raise ProfileError(f"研究主题必须是 YAML 映射：{path}")
    return value


def find_profile_path(config_path: Path, profile_id: str) -> Path:
    profile_id = validate_profile_id(profile_id)
    local_dir, example_dir = profile_directories(config_path)
    for directory in (local_dir, example_dir):
        candidate = directory / f"{profile_id}.yaml"
        if candidate.is_file():
            return candidate
    raise ProfileError(
        f"未找到研究主题 {profile_id!r}。请运行：python run.py configure-search"
    )


def list_profiles(config_path: Path) -> list[dict[str, str]]:
    local_dir, example_dir = profile_directories(config_path)
    found: dict[str, dict[str, str]] = {}
    for source, directory in (("example", example_dir), ("local", local_dir)):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.yaml")):
            try:
                document = _read_yaml(path)
                profile = document.get("profile") or {}
                profile_id = validate_profile_id(profile.get("id") or path.stem)
                found[profile_id] = {
                    "id": profile_id,
                    "name": str(profile.get("name") or profile_id),
                    "source": source,
                    "path": str(path),
                }
            except ProfileError:
                continue
    return sorted(found.values(), key=lambda item: item["id"])


def resolve_profile_id(config_path: Path, explicit: str | None = None) -> str:
    if explicit:
        return validate_profile_id(explicit)
    environment = os.getenv("LITERATURE_PROFILE", "").strip()
    if environment:
        return validate_profile_id(environment)
    active_path = active_profile_path(config_path)
    if active_path.is_file():
        active = _read_yaml(active_path)
        return validate_profile_id(active.get("active_profile") or "")
    raise ProfileError(
        "尚未选择研究主题。请运行 python run.py configure-search，"
        "或使用 --profile <profile_id>。"
    )


def _balanced(value: str, left: str, right: str) -> bool:
    depth = 0
    quoted = False
    escaped = False
    for character in value:
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == '"':
            quoted = not quoted
            continue
        if quoted:
            continue
        if character == left:
            depth += 1
        elif character == right:
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and not quoted


def _validate_wildcards(term: str) -> None:
    text = term.strip().strip('"')
    if not text:
        raise ProfileError("检索词不能为空")
    if re.search(r"[/@#.,:;!][*?$]", text):
        raise ProfileError(f"通配符不能紧跟标点或特殊字符：{term}")
    for match in WILDCARD_RE.finditer(text):
        before = re.search(r"([\w-]+)$", text[: match.start()], flags=re.UNICODE)
        after = re.match(r"([\w-]+)", text[match.end() :], flags=re.UNICODE)
        if match.start() == 0:
            if not after or len(after.group(1).replace("-", "")) < 3:
                raise ProfileError(f"左截词通配符后至少需要 3 个字符：{term}")
        elif not before or len(before.group(1).replace("-", "")) < 3:
            raise ProfileError(f"Topic/Title 通配符前至少需要 3 个字符：{term}")


def validate_term(term: str) -> str:
    value = str(term or "").strip()
    if not value:
        raise ProfileError("检索词不能为空")
    if any(ord(character) < 32 for character in value):
        raise ProfileError("检索词不能包含控制字符")
    if value.count('"') % 2:
        raise ProfileError(f"检索词引号未闭合：{value}")
    if OPERATOR_RE.fullmatch(value):
        raise ProfileError(f"引导模式的检索词不能是运算符：{value}")
    _validate_wildcards(value)
    return value


def _wos_term(term: str) -> str:
    value = validate_term(term)
    if value.startswith('"') and value.endswith('"'):
        return value
    return f'"{value}"' if re.search(r"\s", value) else value


def _portable_term(term: str) -> str:
    value = WILDCARD_RE.sub("", validate_term(term)).strip().strip('"')
    return f'"{value}"' if re.search(r"\s", value) else value


def validate_advanced_wos(query: str) -> str:
    value = str(query or "").strip()
    if not value:
        raise ProfileError("advanced 模式必须填写 query.advanced_wos")
    if not _balanced(value, "(", ")"):
        raise ProfileError("WoS 检索式的括号或双引号未闭合")
    invalid_near = re.search(r"\bNEAR/(?!\d+\b)([^\s()]*)", value, flags=re.I)
    if invalid_near:
        raise ProfileError("NEAR 距离必须写为非负整数，例如 NEAR/5")
    if re.search(r"\bTS\s*=\s*\([^)]*\bSAME\b", value, flags=re.I):
        raise ProfileError("SAME 用于地址检索，不能用于 TS Topic 表达式")
    if len(re.findall(r"\bPY\s*=", value, flags=re.I)) > 1:
        raise ProfileError("WoS 检索式不能包含多个 PY 年份条件")
    for token in re.findall(r"(?<![\w])[*?$][\w-]+|[\w-]+[*?$]", value):
        _validate_wildcards(token)
    return value


def _groups(document: dict[str, Any]) -> list[dict[str, Any]]:
    query = document.get("query") or {}
    raw_groups = query.get("groups") or []
    if not isinstance(raw_groups, list) or not raw_groups:
        raise ProfileError("query.groups 至少需要一个概念组")
    groups: list[dict[str, Any]] = []
    for index, raw_group in enumerate(raw_groups, 1):
        if not isinstance(raw_group, dict):
            raise ProfileError(f"query.groups[{index}] 必须包含 name 和 terms")
        name = str(raw_group.get("name") or "").strip()
        terms = raw_group.get("terms") or []
        if not name or not isinstance(terms, list) or not terms:
            raise ProfileError(f"query.groups[{index}] 的 name 和 terms 不能为空")
        groups.append({"name": name, "terms": [validate_term(term) for term in terms]})
    return groups


def build_guided_wos(document: dict[str, Any]) -> str:
    groups = _groups(document)
    clauses = ["(" + " OR ".join(_wos_term(term) for term in group["terms"]) + ")" for group in groups]
    result = "TS=(" + " AND ".join(clauses) + ")"
    excludes = [validate_term(term) for term in (document.get("query") or {}).get("exclude", [])]
    if excludes:
        result += " NOT TS=(" + " OR ".join(_wos_term(term) for term in excludes) + ")"
    return result


def build_portable_queries(document: dict[str, Any]) -> list[str]:
    query = document.get("query") or {}
    explicit = query.get("portable_queries") or []
    if explicit:
        if not isinstance(explicit, list):
            raise ProfileError("query.portable_queries 必须是列表")
        return [str(item).strip() for item in explicit if str(item).strip()]
    groups = _groups(document)
    maximum = int(query.get("max_generated_queries", 12))
    if not 1 <= maximum <= 100:
        raise ProfileError("query.max_generated_queries 必须在 1-100 之间")
    combinations = itertools.product(*(group["terms"] for group in groups))
    return [
        " AND ".join(_portable_term(term) for term in combination)
        for combination in itertools.islice(combinations, maximum)
    ]


def validate_profile_document(
    document: dict[str, Any], enabled_sources: list[str] | None = None
) -> dict[str, Any]:
    if int(document.get("schema_version", 0)) != 1:
        raise ProfileError("schema_version 必须为 1")
    profile = document.get("profile") or {}
    validate_profile_id(profile.get("id") or "")
    if not str(profile.get("name") or "").strip():
        raise ProfileError("profile.name 不能为空")
    mode = str((document.get("query") or {}).get("mode") or "guided").casefold()
    if mode not in {"guided", "advanced"}:
        raise ProfileError("query.mode 仅支持 guided 或 advanced")
    _groups(document)
    if mode == "guided":
        build_guided_wos(document)
    else:
        advanced = validate_advanced_wos((document.get("query") or {}).get("advanced_wos") or "")
        tags = {tag.upper() for tag in FIELD_TAG_RE.findall(advanced)}
        complex_query = bool(tags - {"TS", "PY"}) or bool(re.search(r"\b(?:NEAR(?:/\d+)?|SAME)\b", advanced, re.I))
        non_wos_enabled = bool(set(enabled_sources or []) & NON_WOS_SOURCES)
        if complex_query and non_wos_enabled and not (document.get("query") or {}).get("portable_queries"):
            raise ProfileError(
                "高级 WoS 检索式包含非 TS/PY 字段或近邻运算；启用非 WoS 来源时必须填写 portable_queries"
            )
    build_portable_queries(document)
    selection = document.get("selection") or {}
    for key, default in (
        ("final_selection_count", 5),
        ("first_run_lookback_days", 30),
        ("lookback_days", 14),
    ):
        if int(selection.get(key, default)) < 1:
            raise ProfileError(f"selection.{key} 必须大于 0")
    return document


def profile_overlay(document: dict[str, Any], enabled_sources: list[str]) -> dict[str, Any]:
    validate_profile_document(document, enabled_sources)
    profile = document["profile"]
    profile_id = validate_profile_id(profile["id"])
    query = document["query"]
    groups = _groups(document)
    mode = str(query.get("mode") or "guided").casefold()
    wos_query = build_guided_wos(document) if mode == "guided" else validate_advanced_wos(query.get("advanced_wos") or "")
    portable_queries = build_portable_queries(document)
    selection = document.get("selection") or {}
    output = document.get("output") or {}
    data_root = str(output.get("root") or f"Literature_Monitor_Data/{profile_id}")
    flattened_terms = [WILDCARD_RE.sub("", term).strip('" ') for group in groups for term in group["terms"]]
    excludes = [WILDCARD_RE.sub("", validate_term(term)).strip('" ') for term in query.get("exclude", [])]
    overlay: dict[str, Any] = {
        "research_profile": {
            "id": profile_id,
            "name": str(profile["name"]).strip(),
            "field": str(profile.get("description") or profile["name"]).strip(),
        },
        "search": {
            "queries": portable_queries,
            "wos_query": wos_query,
            "final_selection_count": int(selection.get("final_selection_count", 5)),
            "first_run_lookback_days": int(selection.get("first_run_lookback_days", 30)),
            "lookback_days": int(selection.get("lookback_days", 14)),
        },
        "keywords": {
            "required_concept_groups": [
                [WILDCARD_RE.sub("", term).strip('" ') for term in group["terms"]]
                for group in groups
            ],
            "include": flattened_terms,
            "exclude": excludes,
        },
        "paths": {
            "root": data_root,
            "database": f"{data_root}/database/literature.db",
            "excel_export": f"{data_root}/exports/{profile_id}_master.xlsx",
        },
        "archive": {"root": f"{data_root}/archive/raw/{profile_id}"},
        "desktop_widget": {"output": f"{data_root}/desktop_widget/latest.html"},
        "wos": {
            "profile_dir": f"{data_root}/browser/wos_profile",
            "inbox_dir": str(output.get("wos_inbox") or f"{data_root}/inbox/wos"),
        },
        "profile_query": {
            "mode": mode,
            "groups": groups,
            "exclude": query.get("exclude") or [],
            "wos_query": wos_query,
            "portable_queries": portable_queries,
        },
    }
    if document.get("scoring"):
        overlay["scoring"] = document["scoring"]
    return overlay


def load_profile(config_path: Path, profile_id: str) -> tuple[dict[str, Any], Path]:
    path = find_profile_path(config_path, profile_id)
    return _read_yaml(path), path


def save_local_profile(config_path: Path, document: dict[str, Any], *, overwrite: bool = False) -> Path:
    validate_profile_document(document)
    profile_id = validate_profile_id(document["profile"]["id"])
    local_dir, _ = profile_directories(config_path)
    local_dir.mkdir(parents=True, exist_ok=True)
    target = local_dir / f"{profile_id}.yaml"
    if target.exists() and not overwrite:
        raise ProfileError(f"研究主题已存在：{profile_id}")
    temporary = target.with_suffix(".yaml.tmp")
    temporary.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    os.replace(temporary, target)
    return target


def set_active_profile(config_path: Path, profile_id: str) -> Path:
    find_profile_path(config_path, profile_id)
    path = active_profile_path(config_path)
    temporary = path.with_suffix(".yaml.tmp")
    temporary.write_text(
        yaml.safe_dump({"active_profile": profile_id}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path


def configure_interactively(
    config_path: Path,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> Path:
    output_fn("创建或更新研究主题。多个同义词请用分号分隔。")
    profile_id = validate_profile_id(input_fn("主题 ID（小写英文/数字/-/_）：").strip())
    name = input_fn("主题名称：").strip()
    if not name:
        raise ProfileError("主题名称不能为空")
    description = input_fn("主题描述（可留空）：").strip() or name
    mode = (input_fn("模式 guided/advanced [guided]：").strip() or "guided").casefold()
    groups: list[dict[str, Any]] = []
    while True:
        group_name = input_fn("概念组名称（完成时直接回车）：").strip()
        if not group_name:
            break
        terms = [item.strip() for item in input_fn("该组检索词（用 ; 分隔）：").split(";") if item.strip()]
        groups.append({"name": group_name, "terms": terms})
    excludes = [item.strip() for item in input_fn("排除词（用 ; 分隔，可留空）：").split(";") if item.strip()]
    advanced_wos = ""
    portable: list[str] = []
    if mode == "advanced":
        advanced_wos = input_fn("完整 WoS 高级检索式：").strip()
        portable = [item.strip() for item in input_fn("非 WoS 检索式（用 ; 分隔，可留空）：").split(";") if item.strip()]
    document: dict[str, Any] = {
        "schema_version": 1,
        "profile": {"id": profile_id, "name": name, "description": description},
        "query": {
            "mode": mode,
            "groups": groups,
            "exclude": excludes,
            "advanced_wos": advanced_wos,
            "portable_queries": portable,
            "max_generated_queries": 12,
        },
        "selection": {
            "final_selection_count": 5,
            "first_run_lookback_days": 30,
            "lookback_days": 14,
        },
        "scoring": {"topic_gate": 10, "method_terms": [], "applied_terms": [], "journal_tiers": {}},
    }
    target = profile_directories(config_path)[0] / f"{profile_id}.yaml"
    overwrite = False
    if target.exists():
        overwrite = input_fn(f"主题 {profile_id} 已存在，确认覆盖？[y/N]：").strip().casefold() == "y"
        if not overwrite:
            raise ProfileError("已取消更新")
    path = save_local_profile(config_path, document, overwrite=overwrite)
    if input_fn("设为当前活动主题？[Y/n]：").strip().casefold() not in {"n", "no"}:
        set_active_profile(config_path, profile_id)
    output_fn(f"已保存：{path}")
    output_fn(f"WoS：{build_guided_wos(document) if mode == 'guided' else advanced_wos}")
    output_fn("非 WoS：" + " | ".join(build_portable_queries(document)))
    return path
