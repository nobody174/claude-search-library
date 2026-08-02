"""Collection orchestration for Claude Search Library.

Adds source selection and two failure-handling modes on top of the
per-source collectors in src.collector:

- fail_fast=True  (manual/dev): stop immediately on the first collector or
  storage error, so problems surface right away.
- fail_fast=False (automated/cron): log and continue past a failed source,
  so one broken collector doesn't block collection from the others. This
  matches collect_all()'s original always-continue behavior.

CLI: python3 cli.py collect --source claude-ai --fail-fast
See ROADMAP.md #1.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from src import collector

logger = logging.getLogger(__name__)

SOURCES = ("claude-ai", "vscode", "claude-code", "cowork", "local")


class CollectionError(RuntimeError):
    """Raised in fail_fast mode when a source's collector or storage step fails."""


def _default_folders() -> dict:
    base = Path.home() / ".claude-search-library" / "data" / "raw_exports"
    return {
        "claude-ai": str(base / "claude-ai"),
        "local": str(base / "local"),
    }


def _collector_and_arg(source: str, folders: dict):
    return {
        "claude-ai": (collector.collect_from_claude_ai, folders.get("claude-ai")),
        "vscode": (collector.collect_from_vscode, folders.get("vscode")),
        "claude-code": (collector.collect_from_claude_code, folders.get("claude-code")),
        "cowork": (collector.collect_from_cowork, folders.get("cowork")),
        "local": (collector.collect_from_local, folders.get("local")),
    }[source]


def run_collection(
    sources: Optional[list] = None,
    fail_fast: bool = False,
    db_path: Optional[str] = None,
    claude_ai_folder: Optional[str] = None,
    vscode_extensions_path: Optional[str] = None,
    claude_code_projects_path: Optional[str] = None,
    cowork_path: Optional[str] = None,
    local_folder: Optional[str] = None,
) -> dict:
    """Run the requested collectors (default: all four sources) and persist
    new sessions to storage.

    Returns a dict with per-source results plus aggregate totals:
    {"new": int, "errors": int, "total": int, "sources": {name: {...}}}.

    In fail_fast mode, the first collector or storage failure raises
    CollectionError immediately instead of being recorded and skipped.
    """
    from src.storage import Storage

    if sources is None:
        sources = list(SOURCES)
    unknown = [s for s in sources if s not in SOURCES]
    if unknown:
        raise ValueError(f"Unknown source(s): {unknown}. Valid sources: {SOURCES}")

    defaults = _default_folders()
    folders = {
        "claude-ai": claude_ai_folder or defaults["claude-ai"],
        "vscode": vscode_extensions_path,
        "claude-code": claude_code_projects_path,
        "cowork": cowork_path,
        "local": local_folder or defaults["local"],
    }

    per_source: dict = {}
    all_sessions: list = []
    errors = 0

    for name in sources:
        func, arg = _collector_and_arg(name, folders)
        try:
            sessions = func(arg)
            per_source[name] = {"collected": len(sessions), "error": None}
            all_sessions.extend(sessions)
        except Exception as e:
            logger.error("Collector '%s' failed: %s", name, e)
            per_source[name] = {"collected": 0, "error": str(e)}
            errors += 1
            if fail_fast:
                raise CollectionError(f"Collector '{name}' failed: {e}") from e

    seen_ids = set()
    deduped_sessions = []
    for s in all_sessions:
        if s["id"] not in seen_ids:
            seen_ids.add(s["id"])
            deduped_sessions.append(s)

    new_count = 0
    with Storage(db_path) as db:
        for session in deduped_sessions:
            try:
                hash_source = collector._load_raw_export_for_hash(session)
                result = db.store_session_with_hash(
                    collector._session_to_storage_dict(session), hash_source=hash_source
                )
                if result["status"] == "inserted":
                    new_count += 1
            except Exception as e:
                logger.error("Failed to store session %s: %s", session.get("id"), e)
                errors += 1
                if fail_fast:
                    raise CollectionError(f"Failed to store session {session.get('id')}: {e}") from e

    return {
        "new": new_count,
        "errors": errors,
        "total": len(all_sessions),
        "sources": per_source,
    }
