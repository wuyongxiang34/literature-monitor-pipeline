from __future__ import annotations

import os
import re
import warnings
from pathlib import Path
from typing import Any

import yaml

from .profiles import ProfileError, active_profile_path, load_profile, profile_overlay, resolve_profile_id


ENV_PATTERN = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
REQUIRED_WEIGHTS = ("topic", "method", "journal", "network", "applied", "archival")


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return ENV_PATTERN.sub(lambda match: os.getenv(match.group(1), ""), value)
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    return value


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def load_config(
    path: Path,
    *,
    profile_id: str | None = None,
    require_profile: bool = True,
) -> dict[str, Any]:
    path = path.resolve()
    load_dotenv(path.parent.parent / ".env")
    with path.open("r", encoding="utf-8-sig") as handle:
        config = yaml.safe_load(handle) or {}
    includes = config.pop("include", [])
    merged: dict[str, Any] = {}
    for include in includes:
        include_path = path.parent / include
        with include_path.open("r", encoding="utf-8-sig") as handle:
            merged = _deep_merge(merged, yaml.safe_load(handle) or {})
    config = _expand_env(_deep_merge(merged, config))
    profile_path: Path | None = None
    if require_profile:
        try:
            resolved_profile = resolve_profile_id(path, profile_id)
            profile_document, profile_path = load_profile(path, resolved_profile)
            enabled_sources = list((config.get("search") or {}).get("sources") or [])
            config = _deep_merge(config, profile_overlay(profile_document, enabled_sources))
        except ProfileError:
            search = config.get("search") or {}
            legacy_allowed = (
                not profile_id
                and not os.getenv("LITERATURE_PROFILE", "").strip()
                and not active_profile_path(path).exists()
                and search.get("queries")
                and search.get("wos_query")
            )
            if not legacy_allowed:
                raise
            warnings.warn(
                "旧版 search.queries/search.wos_query 配置将在下一版本移除；"
                "请运行 configure-search 迁移为研究主题。",
                FutureWarning,
                stacklevel=2,
            )
            profile = config.setdefault("research_profile", {})
            legacy_name = str(profile.get("name") or "legacy").strip()
            profile.setdefault("id", re.sub(r"[^a-z0-9_-]+", "_", legacy_name.casefold()).strip("_") or "legacy")
            profile.setdefault("name", str(profile.get("field") or "Legacy research profile"))
    config["_config_path"] = str(path)
    config["_project_root"] = str(path.parent.parent)
    config["_profile_path"] = str(profile_path) if profile_path else ""
    validate_config(config, require_search=require_profile)
    return config


def _deep_merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def validate_config(config: dict[str, Any], *, require_search: bool = True) -> None:
    errors: list[str] = []
    profile = config.get("research_profile") or {}
    if require_search and not profile.get("field"):
        errors.append("research_profile.field 不能为空")

    search = config.get("search") or {}
    if int(search.get("candidate_pool_size", 0)) < 1:
        errors.append("search.candidate_pool_size 必须大于 0")
    if int(search.get("final_selection_count", 0)) < 1:
        errors.append("search.final_selection_count 必须大于 0")
    if int(search.get("lookback_days", 0)) < 1:
        errors.append("search.lookback_days 必须大于 0")
    if require_search and not search.get("queries"):
        errors.append("search.queries 至少需要一项")
    if require_search and not search.get("wos_query"):
        errors.append("search.wos_query 不能为空")

    weights = (config.get("scoring") or {}).get("weights") or {}
    missing = [name for name in REQUIRED_WEIGHTS if name not in weights]
    if missing:
        errors.append(f"scoring.weights 缺少：{', '.join(missing)}")
    elif sum(int(weights[name]) for name in REQUIRED_WEIGHTS) != 100:
        errors.append("六维评分权重之和必须为 100")
    if int((config.get("scoring") or {}).get("topic_gate", 0)) < 0:
        errors.append("scoring.topic_gate 不能小于 0")

    delivery = config.get("delivery") or {}
    if delivery.get("channel", "local") not in {"local", "feishu", "telegram"}:
        errors.append("delivery.channel 仅支持 local、feishu 或 telegram")

    if errors:
        raise ValueError("配置校验失败：\n- " + "\n- ".join(errors))


def resolve_project_path(config: dict[str, Any], value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = Path(config["_project_root"]) / path
    return path.resolve()
