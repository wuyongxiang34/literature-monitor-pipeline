from __future__ import annotations

import datetime as dt
import json
import logging
import os
import socket
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import __version__
from .config import resolve_project_path
from .delivery import deliver
from .desktop_widget import render_widget
from .digest import build_digest
from .models import Paper
from .normalize import deduplicate
from .scoring import score_and_select_detailed, validate_scores
from .sources import collect_sources
from .storage import LiteratureDatabase, archive_note, export_excel
from .wos import search_wos


LOGGER = logging.getLogger(__name__)


class RunLock:
    def __init__(self, path: Path, stale_hours: int = 12):
        self.path = path
        self.stale_hours = stale_hours

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
                created = dt.datetime.fromisoformat(value["created"])
                age = dt.datetime.now(dt.timezone.utc) - created
                if age < dt.timedelta(hours=self.stale_hours):
                    raise RuntimeError(f"已有任务正在运行：{self.path}")
            except (ValueError, KeyError, json.JSONDecodeError):
                raise RuntimeError(f"任务锁无效且无法确认是否安全：{self.path}")
        self.path.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "host": socket.gethostname(),
                    "created": dt.datetime.now(dt.timezone.utc).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.path.exists():
            self.path.unlink()


def _setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )


def _close_logging() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        try:
            handler.flush()
            handler.close()
        finally:
            root.removeHandler(handler)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _mark_public_unverified(papers: list[Paper]) -> None:
    for paper in papers:
        if "sciencedirect" in paper.sources:
            paper.sci_status = "Indexed (ScienceDirect; not SCI evidence)"
        elif "wos" not in paper.sources:
            paper.sci_status = "Unverified (public metadata source)"


def run_pipeline(config: dict[str, Any], *, no_delivery: bool = False) -> dict[str, Any]:
    timezone = ZoneInfo(config.get("schedule", {}).get("timezone", "Asia/Taipei"))
    started = dt.datetime.now(timezone)
    run_date = started.date().isoformat()
    run_id = started.strftime("%Y%m%dT%H%M%S%f%z")

    data_root = resolve_project_path(config, config["paths"]["root"])
    profile_id = config["research_profile"]["id"]
    profile_name = config["research_profile"]["name"]
    run_dir = data_root / "papers" / started.strftime("%Y") / started.strftime("%m") / f"{run_date}_{profile_id}"
    report_dir = run_dir / "report"
    metadata_dir = run_dir / "metadata"
    report_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_root / "logs" / f"{run_id}.log"
    _setup_logging(log_path)

    database_path = resolve_project_path(config, config["paths"]["database"])
    lock_path = data_root / "state" / "daily.lock"
    with RunLock(lock_path):
        with LiteratureDatabase(database_path) as database:
            existing_paper_count = database.paper_count()
        override = config.get("_lookback_override")
        if override is not None:
            lookback = int(override)
            lookback_reason = "override"
        elif existing_paper_count == 0:
            lookback = int(config["search"].get("first_run_lookback_days", 90))
            lookback_reason = "initial_empty_database"
        else:
            lookback = int(config["search"]["lookback_days"])
            lookback_reason = "routine"
        start_date = (started.date() - dt.timedelta(days=lookback - 1)).isoformat()
        end_date = run_date
        LOGGER.info("检索窗口：%s 至 %s", start_date, end_date)

        public_papers, source_status = collect_sources(config, start_date, end_date)
        _mark_public_unverified(public_papers)
        wos_papers, wos_status = search_wos(config, start_date, end_date)
        source_status["wos"] = wos_status
        all_papers = [*wos_papers, *public_papers]
        unique_papers, duplicate_count = deduplicate(all_papers)
        scored, _, filter_summary, rejected = score_and_select_detailed(unique_papers, config)
        validate_scores(scored, config)

        with LiteratureDatabase(database_path) as database:
            new_count = 0
            new_papers: list[Paper] = []
            for paper in scored:
                _, was_new = database.upsert_paper(paper, run_id, run_date)
                new_count += int(was_new)
                if was_new:
                    new_papers.append(paper)
            selected_new = new_papers[: int(config["search"]["final_selection_count"])]

            for source, status in source_status.items():
                database.record_search(
                    run_id=run_id,
                    run_date=run_date,
                    database_name=source,
                    query=(
                        config["search"]["wos_query"]
                        if source == "wos"
                        else " | ".join(config["search"]["queries"])
                    ),
                    retrieved=sum(source in paper.sources for paper in all_papers),
                    included=sum(source in paper.sources for paper in scored),
                    excluded=max(
                        0,
                        sum(source in paper.sources for paper in all_papers)
                        - sum(source in paper.sources for paper in scored),
                    ),
                    duplicates=duplicate_count,
                    status=status,
                    error="" if status.startswith(("ok", "skipped")) else status,
                )

            digest = build_digest(
                run_date,
                profile_id,
                profile_name,
                config["research_profile"]["field"],
                selected_new,
                retrieved=len(all_papers),
                deduplicated=len(unique_papers),
                eligible_count=len(scored),
                new_count=new_count,
                source_status=source_status,
                filter_summary=filter_summary,
            )
            digest_path = report_dir / "Daily_Report.md"
            digest_path.write_text(digest, encoding="utf-8")
            history_dir = report_dir / "history"
            history_dir.mkdir(parents=True, exist_ok=True)
            (history_dir / f"{run_id}.md").write_text(digest, encoding="utf-8")
            widget_status = "disabled"
            widget_config = config.get("desktop_widget") or {}
            if widget_config.get("enabled", False):
                try:
                    widget_path = resolve_project_path(
                        config,
                        widget_config.get(
                            "output", f"Literature_Monitor_Data/{profile_id}/desktop_widget/latest.html"
                        ),
                    )
                    widget_status = str(
                        render_widget(
                            digest_path,
                            widget_path,
                            history_limit=int(widget_config.get("history_reports", 4)),
                        )
                    )
                except Exception as exc:
                    widget_status = f"error: {exc}"
                    LOGGER.warning("桌面文献卡片更新失败：%s", exc)
            _write_json(metadata_dir / "candidates.json", [paper.as_dict() for paper in scored])
            _write_json(metadata_dir / "rejected.json", rejected)
            _write_json(metadata_dir / "selected.json", [paper.as_dict() for paper in selected_new])

            archive_paths: list[str] = []
            archive_config = config.get("archive") or {}
            if archive_config.get("enabled"):
                archive_root = resolve_project_path(config, archive_config["root"])
                for paper in selected_new:
                    archive_paths.append(str(archive_note(paper, archive_root, run_date)))

            excel_path = resolve_project_path(config, config["paths"]["excel_export"])
            try:
                export_excel(database, excel_path)
                excel_status = str(excel_path)
            except PermissionError:
                pending = excel_path.with_name(f"{excel_path.stem}_{run_id}_pending.xlsx")
                export_excel(database, pending)
                excel_status = f"Excel 被占用，已输出 pending 文件：{pending}"

            delivery_status = "skipped by --no-delivery" if no_delivery else deliver(digest, config)
            source_available = any(status.startswith("ok") for status in source_status.values())
            required_sources = config["search"].get("required_sources") or []
            required_sources_available = all(
                source_status.get(source, "").startswith("ok")
                for source in required_sources
            )
            overall = "SUCCESS" if source_available and required_sources_available else "PARTIAL"
            database.set_task_status(
                overall,
                f"new={new_count}; selected={len(selected_new)}; delivery={delivery_status}",
                successful=overall == "SUCCESS",
            )

        summary = {
            "version": __version__,
            "profile_id": profile_id,
            "profile_name": profile_name,
            "run_id": run_id,
            "status": overall,
            "search_window": {"start": start_date, "end": end_date},
            "retrieved": len(all_papers),
            "deduplicated": len(unique_papers),
            "eligible": len(scored),
            "rejected": len(rejected),
            "selected": len(selected_new),
            "new_records": new_count,
            "filter_summary": filter_summary,
            "lookback_days": lookback,
            "lookback_reason": lookback_reason,
            "source_status": source_status,
            "database": str(database_path),
            "excel": excel_status,
            "report": str(digest_path),
            "desktop_widget": widget_status,
            "archive_notes": archive_paths,
            "delivery": delivery_status,
            "log": str(log_path),
        }
        _write_json(report_dir / "run_summary.json", summary)
        _write_json(report_dir / "history" / f"{run_id}.json", summary)
        _close_logging()
        return summary
