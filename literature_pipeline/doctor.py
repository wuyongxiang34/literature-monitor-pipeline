from __future__ import annotations

import importlib.util
import os
import platform
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

from .config import load_config, resolve_project_path
from .profiles import ProfileError, resolve_profile_id


SUPPORTED_PYTHON = {(3, 11), (3, 12), (3, 13), (3, 14)}
CORE_DEPENDENCIES = {
    "PyYAML": "yaml",
    "openpyxl": "openpyxl",
    "xlrd": "xlrd",
    "tzdata": "tzdata",
}
CREDENTIALS = {
    "ScienceDirect / Scopus": ("ELSEVIER_API_KEY",),
    "OpenAlex": ("OPENALEX_API_KEY",),
    "Semantic Scholar": ("SEMANTIC_SCHOLAR_API_KEY",),
    "Web of Science": ("WEBOFSCIENCE_API_KEY", "WEBOFSCIENDE_API_KEY"),
}


def _distribution_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return ""


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path.resolve()
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate


def collect_diagnostics(config_path: Path, profile_id: str | None = None) -> dict[str, Any]:
    version = (sys.version_info.major, sys.version_info.minor)
    result: dict[str, Any] = {
        "python": {
            "version": platform.python_version(),
            "supported": version in SUPPORTED_PYTHON,
            "bits": platform.architecture()[0],
            "executable": sys.executable,
        },
        "dependencies": {},
        "configuration": {"valid": False, "error": ""},
        "profile": {"id": "", "status": "not selected"},
        "credentials": {},
        "output": {"path": "", "writable": None},
        "playwright": {"installed": False, "version": ""},
    }

    for distribution, module in CORE_DEPENDENCIES.items():
        installed = importlib.util.find_spec(module) is not None
        result["dependencies"][distribution] = {
            "installed": installed,
            "version": _distribution_version(distribution) if installed else "",
        }

    playwright_installed = importlib.util.find_spec("playwright") is not None
    result["playwright"] = {
        "installed": playwright_installed,
        "version": _distribution_version("playwright") if playwright_installed else "",
    }

    try:
        load_config(config_path, require_profile=False)
        result["configuration"]["valid"] = True
    except Exception as exc:
        result["configuration"]["error"] = f"{type(exc).__name__}: {exc}"

    try:
        resolved = resolve_profile_id(config_path, profile_id)
        full_config = load_config(config_path, profile_id=resolved)
        result["profile"] = {"id": resolved, "status": "valid"}
        output_path = resolve_project_path(full_config, full_config["paths"]["root"])
        writable_parent = _nearest_existing_parent(output_path)
        result["output"] = {
            "path": str(output_path),
            "writable": writable_parent.exists() and os.access(writable_parent, os.W_OK),
        }
    except ProfileError as exc:
        result["profile"] = {"id": profile_id or "", "status": str(exc)}
    except Exception as exc:
        result["profile"] = {
            "id": profile_id or "",
            "status": f"{type(exc).__name__}: {exc}",
        }

    for source, variables in CREDENTIALS.items():
        result["credentials"][source] = any(os.getenv(name, "").strip() for name in variables)
    return result


def print_diagnostics(config_path: Path, profile_id: str | None = None) -> int:
    result = collect_diagnostics(config_path, profile_id)
    python = result["python"]
    print("环境诊断")
    print(
        f"[{'OK' if python['supported'] else 'ERROR'}] Python "
        f"{python['version']} ({python['bits']}): {python['executable']}"
    )
    for name, detail in result["dependencies"].items():
        state = "OK" if detail["installed"] else "ERROR"
        suffix = f" {detail['version']}" if detail["version"] else ""
        print(f"[{state}] 核心依赖 {name}{suffix}")
    config = result["configuration"]
    print(f"[{'OK' if config['valid'] else 'ERROR'}] 基础配置" + (f"：{config['error']}" if config["error"] else ""))
    profile = result["profile"]
    profile_ok = profile["status"] == "valid"
    print(f"[{'OK' if profile_ok else 'WARN'}] 活动主题：{profile['id'] or profile['status']}")
    if result["output"]["path"]:
        print(
            f"[{'OK' if result['output']['writable'] else 'ERROR'}] 输出目录："
            f"{result['output']['path']}"
        )
    for source, configured in result["credentials"].items():
        print(f"[{'OK' if configured else 'WARN'}] {source} 凭据：{'已配置' if configured else '未配置'}")
    playwright = result["playwright"]
    suffix = f" {playwright['version']}" if playwright["version"] else ""
    print(f"[{'OK' if playwright['installed'] else 'INFO'}] Playwright：{'已安装' if playwright['installed'] else '未安装（可选）'}{suffix}")

    core_ok = (
        python["supported"]
        and all(item["installed"] for item in result["dependencies"].values())
        and config["valid"]
        and result["output"]["writable"] is not False
    )
    return 0 if core_ok else 1
