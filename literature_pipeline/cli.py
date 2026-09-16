from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from . import __version__
from .config import load_config
from .pipeline import run_pipeline
from .profiles import (
    build_portable_queries,
    build_guided_wos,
    configure_interactively,
    list_profiles,
    load_profile,
    resolve_profile_id,
    validate_profile_document,
)
from .storage import LiteratureDatabase, export_excel
from .wos import initialize_login


def _configure_console_output() -> None:
    """Keep Windows legacy consoles from failing on names outside GBK."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"Configurable Literature Monitor v{__version__}")
    parser.add_argument("--config", type=Path, default=Path("config/settings.yaml"))
    parser.add_argument("--profile", help="研究主题 ID；优先于环境变量和活动主题")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="执行每日检索")
    run.add_argument("--no-delivery", action="store_true", help="不发送外部消息")
    subparsers.add_parser("validate", help="校验配置")
    subparsers.add_parser("login-wos", help="人工初始化 WoS 持久登录")
    subparsers.add_parser("export", help="从 SQLite 重新导出 Excel")
    subparsers.add_parser("configure-search", help="交互式创建或更新研究主题")
    profiles = subparsers.add_parser("profiles", help="管理和检查研究主题")
    profile_commands = profiles.add_subparsers(dest="profile_command", required=True)
    profile_commands.add_parser("list", help="列出本地和示例主题")
    profile_commands.add_parser("resolve", help=argparse.SUPPRESS)
    show = profile_commands.add_parser("show", help="显示主题及编译后的查询")
    show.add_argument("profile_id")
    validate = profile_commands.add_parser("validate", help="校验指定主题")
    validate.add_argument("profile_id")
    path = profile_commands.add_parser("path", help=argparse.SUPPRESS)
    path.add_argument("profile_id")
    path.add_argument("path_name", choices=("data-root", "database", "excel", "widget", "wos-inbox"))
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_console_output()
    args = build_parser().parse_args(argv)
    try:
        if args.command == "configure-search":
            configure_interactively(args.config)
            return 0
        if args.command == "profiles":
            if args.profile_command == "resolve":
                print(resolve_profile_id(args.config, args.profile))
                return 0
            if args.profile_command == "list":
                try:
                    active = resolve_profile_id(args.config)
                except Exception:
                    active = ""
                for item in list_profiles(args.config):
                    marker = "*" if item["id"] == active else " "
                    print(f"{marker} {item['id']}: {item['name']} ({item['source']})")
                return 0
            document, path = load_profile(args.config, args.profile_id)
            base = load_config(args.config, require_profile=False)
            sources = list((base.get("search") or {}).get("sources") or [])
            validate_profile_document(document, sources)
            if args.profile_command == "show":
                print(yaml.safe_dump(document, allow_unicode=True, sort_keys=False).rstrip())
                print("\n# 编译预览")
                mode = str((document.get("query") or {}).get("mode") or "guided").casefold()
                print("WoS:", build_guided_wos(document) if mode == "guided" else document["query"]["advanced_wos"])
                print("Portable:")
                for query in build_portable_queries(document):
                    print(f"- {query}")
                print("Source:", path)
                return 0
            config = load_config(args.config, profile_id=args.profile_id)
            if args.profile_command == "path":
                from .config import resolve_project_path

                mapping = {
                    "data-root": config["paths"]["root"],
                    "database": config["paths"]["database"],
                    "excel": config["paths"]["excel_export"],
                    "widget": config["desktop_widget"]["output"],
                    "wos-inbox": config["wos"]["inbox_dir"],
                }
                print(resolve_project_path(config, mapping[args.path_name]))
                return 0
            print(f"研究主题有效：{args.profile_id} ({path})")
            return 0
        if args.command == "validate":
            config = load_config(
                args.config,
                profile_id=args.profile,
                require_profile=bool(args.profile),
            )
            print("配置有效。" if not args.profile else f"配置与研究主题有效：{args.profile}")
            return 0
        config = load_config(args.config, profile_id=args.profile)
        if args.command == "login-wos":
            initialize_login(config)
            print("WoS 持久化登录会话已保存。")
            return 0
        if args.command == "export":
            from .config import resolve_project_path

            database_path = resolve_project_path(config, config["paths"]["database"])
            excel_path = resolve_project_path(config, config["paths"]["excel_export"])
            with LiteratureDatabase(database_path) as database:
                export_excel(database, excel_path)
            print(excel_path)
            return 0
        summary = run_pipeline(config, no_delivery=args.no_delivery)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["status"] in {"SUCCESS", "PARTIAL"} else 1
    except Exception as exc:
        print(f"运行失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
