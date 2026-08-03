"""Retention/pruning module for Claude Search Library.

Prunes old raw chat content while keeping sessions searchable: the
sessions row, its stored summary, and its search/embedding index all
stay intact — only the on-disk raw export file (the full conversation
text) is deleted, since that's the bulk of storage and the least useful
part of an old session (see ROADMAP.md #5).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _parse_created_at(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def find_prunable_sessions(older_than_days: int, db_path: Optional[str] = None) -> list[dict]:
    """Return sessions older than `older_than_days` that still have a raw
    export file on disk (i.e. haven't already been pruned)."""
    from src.storage import Storage

    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)

    candidates = []
    with Storage(db_path) as db:
        for session in db.get_all_sessions():
            created_at = _parse_created_at(session.get("created_at"))
            if created_at is None or created_at >= cutoff:
                continue
            raw_path = session.get("raw_file_path")
            if raw_path and os.path.exists(raw_path):
                candidates.append(session)

    return candidates


def prune_sessions(older_than_days: int = 365, dry_run: bool = True, db_path: Optional[str] = None) -> dict:
    """Delete the on-disk raw export file for sessions older than
    `older_than_days`, clearing raw_file_path so the session stops
    reporting a file that no longer exists. Summaries, search/embedding
    index entries, and the session row itself are never touched.

    Returns {"candidates": int, "pruned": int, "freed_bytes": int, "dry_run": bool}.
    """
    from src.storage import Storage

    candidates = find_prunable_sessions(older_than_days, db_path=db_path)

    if dry_run:
        freed_bytes = 0
        for session in candidates:
            try:
                freed_bytes += os.path.getsize(session["raw_file_path"])
            except OSError:
                pass
        return {"candidates": len(candidates), "pruned": 0, "freed_bytes": freed_bytes, "dry_run": True}

    pruned = 0
    freed_bytes = 0
    with Storage(db_path) as db:
        for session in candidates:
            raw_path = Path(session["raw_file_path"])
            try:
                freed_bytes += raw_path.stat().st_size
                raw_path.unlink()
            except OSError as e:
                logger.warning("Failed to delete raw export for %s: %s", session["id"], e)
                continue
            db.update_session(session["id"], {"raw_file_path": None})
            pruned += 1

    return {"candidates": len(candidates), "pruned": pruned, "freed_bytes": freed_bytes, "dry_run": False}
