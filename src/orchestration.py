#
# Claude Search Library
# Author:  nobody174
# Repo:    https://github.com/nobody174/claude-search-library
# Patreon: https://www.patreon.com/c/Nobody174
# License: MIT
# "It's never too late to give up!"
#

"""Collection orchestration for Claude Search Library.

Adds source selection and two failure-handling modes on top of the
per-source collectors in src.collector:

- fail_fast=True  (manual/dev): stop immediately on the first collector or
  storage error, so problems surface right away.
- fail_fast=False (automated/cron): log and continue past a failed source,
  so one broken collector doesn't block collection from the others. This
  matches collect_all()'s original always-continue behavior.

CLI: python3 cli.py collect --source claude-ai --fail-fast
See CHANGELOG.md.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from src import collector

logger = logging.getLogger(__name__)

# claude-android is deliberately NOT in SOURCES (the default "collect
# from everything" set `cli.py sync` and `run_collection(sources=None)`
# use) - unlike every other collector, it drives a live device UI over
# several minutes per run (real device time, see
# src/android_bridge.py's module docstring) and depends on a phone
# being reachable over WiFi right now. Running that silently on every
# 5-minute sync tick would be a real surprise, not a convenience.
# Explicitly selectable via `cli.py collect --source claude-android`
# instead - see ALL_SOURCES for the full set including it.
SOURCES = ("claude-ai", "vscode", "claude-code", "claude-desktop", "cowork", "local")
ALL_SOURCES = SOURCES + ("claude-android",)


class CollectionError(RuntimeError):
    """Raised in fail_fast mode when a source's collector or storage step fails."""


def _default_folders() -> dict:
    base = Path.home() / ".claude-search-library" / "data" / "raw_exports"
    return {
        "claude-ai": str(base / "claude-ai"),
        "local": str(base / "local"),
    }


def _collector_and_arg(source: str, folders: dict):
    if source == "claude-android":
        from src.android_bridge import collect_from_claude_android
        return (collect_from_claude_android, folders.get("claude-android"))
    return {
        "claude-ai": (collector.collect_from_claude_ai, folders.get("claude-ai")),
        "vscode": (collector.collect_from_vscode, folders.get("vscode")),
        "claude-code": (collector.collect_from_claude_code, folders.get("claude-code")),
        "claude-desktop": (collector.collect_from_claude_desktop, folders.get("claude-desktop")),
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
    claude_desktop_indexeddb_root: Optional[str] = None,
    cowork_path: Optional[str] = None,
    local_folder: Optional[str] = None,
    android_address: Optional[str] = None,
) -> dict:
    """Run the requested collectors (default: all sources except
    claude-android - see SOURCES/ALL_SOURCES) and persist new sessions
    to storage.

    Returns a dict with per-source results plus aggregate totals:
    {"new": int, "errors": int, "total": int, "sources": {name: {...}}}.

    In fail_fast mode, the first collector or storage failure raises
    CollectionError immediately instead of being recorded and skipped.

    android_address defaults to None, meaning collect_from_claude_android()
    falls back to its own persisted last-known device address (see
    src/android_bridge.py's connect_device()) - only needed here if you
    want to override that for a one-off run.
    """
    from src.storage import Storage

    if sources is None:
        sources = list(SOURCES)
    unknown = [s for s in sources if s not in ALL_SOURCES]
    if unknown:
        raise ValueError(f"Unknown source(s): {unknown}. Valid sources: {ALL_SOURCES}")

    defaults = _default_folders()
    folders = {
        "claude-ai": claude_ai_folder or defaults["claude-ai"],
        "vscode": vscode_extensions_path,
        "claude-code": claude_code_projects_path,
        "claude-desktop": claude_desktop_indexeddb_root,
        "cowork": cowork_path,
        "local": local_folder or defaults["local"],
        "claude-android": android_address,
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
    updated_count = 0
    with Storage(db_path) as db:
        for session in deduped_sessions:
            try:
                hash_source = collector._load_raw_export_for_hash(session)
                result = db.store_session_with_hash(
                    collector._session_to_storage_dict(session), hash_source=hash_source
                )
                if result["status"] == "inserted":
                    new_count += 1
                elif result["status"] == "updated":
                    updated_count += 1
            except Exception as e:
                logger.error("Failed to store session %s: %s", session.get("id"), e)
                errors += 1
                if fail_fast:
                    raise CollectionError(f"Failed to store session {session.get('id')}: {e}") from e

    return {
        "new": new_count,
        "updated": updated_count,
        "errors": errors,
        "total": len(all_sessions),
        "sources": per_source,
    }

# Built with assistance from Claude Code by Anthropic.
