"""Data collection module for Claude Search Library.

Collects chat sessions from Claude.ai exports, the VS Code Claude extension,
Cowork, and a local watch folder, normalizing all of them into a common
schema (see SPEC.md -> Normalization Schema).
"""
from __future__ import annotations

import hashlib
import json
import logging
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_WATCH_INTERVAL_SECONDS = 300


def _content_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update((part or "").encode("utf-8"))
    return h.hexdigest()[:16]


def _approx_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def detect_device() -> str:
    """Best-effort guess at what kind of device this is running on."""
    system = platform.system().lower()
    if system == "darwin" and "iphone" in platform.platform().lower():
        return "phone"
    return "desktop"


def normalize_session(
    raw: dict,
    source: str,
    device: str,
    raw_path: str = "",
) -> dict:
    """Convert a loosely-structured chat export into the normalized schema."""
    messages_in = raw.get("messages") or []
    messages = []
    for m in messages_in:
        content = m.get("content", "") or ""
        messages.append(
            {
                "role": m.get("role", "user"),
                "content": content,
                "timestamp": m.get("timestamp") or raw.get("created_at") or "",
                "tokens_approx": m.get("tokens_approx", _approx_tokens(content)),
            }
        )

    created_at = raw.get("created_at") or (messages[0]["timestamp"] if messages else "")
    updated_at = raw.get("updated_at") or (messages[-1]["timestamp"] if messages else created_at)

    created_dt = _parse_iso(created_at)
    updated_dt = _parse_iso(updated_at)
    duration_seconds = 0
    if created_dt and updated_dt and updated_dt >= created_dt:
        duration_seconds = int((updated_dt - created_dt).total_seconds())

    user_count = sum(1 for m in messages if m["role"] == "user")
    assistant_count = sum(1 for m in messages if m["role"] == "assistant")

    session_id = raw.get("id") or _content_hash(source, raw_path, created_at, str(len(messages)))

    return {
        "id": str(session_id),
        "source": source,
        "title": raw.get("title") or "Untitled Session",
        "created_at": created_at,
        "updated_at": updated_at,
        "duration_seconds": duration_seconds,
        "message_count": len(messages),
        "user_message_count": user_count,
        "assistant_message_count": assistant_count,
        "messages": messages,
        "device": device,
        "tags": raw.get("tags", []),
        "raw_path": raw_path,
    }


def _load_json_files(folder: Path) -> list[tuple[dict, str]]:
    results = []
    if not folder.exists() or not folder.is_dir():
        return results
    for path in sorted(folder.glob("*.json")):
        if path.stem.endswith("_summary"):
            # Defense in depth: processor.py writes summaries to a separate
            # directory precisely to avoid this, but skip them here too in
            # case a collector folder ever ends up pointed at that
            # directory (e.g. a future --local-folder misconfiguration).
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Skipping unreadable export %s: %s", path, e)
            continue
        results.append((data, str(path)))
    return results


def collect_from_claude_ai(export_folder: str) -> list[dict]:
    """Read JSON files from a Claude.ai exports folder and normalize them."""
    folder = Path(export_folder)
    sessions = []
    for data, raw_path in _load_json_files(folder):
        try:
            sessions.append(normalize_session(data, "claude-ai", detect_device(), raw_path))
        except Exception as e:
            logger.warning("Failed to normalize %s: %s", raw_path, e)
    return sessions


def collect_from_vscode(extensions_path: Optional[str] = None) -> list[dict]:
    """Find the Claude VS Code extension's chat history and normalize it."""
    if extensions_path is None:
        extensions_path = str(Path.home() / ".vscode" / "extensions")

    ext_root = Path(extensions_path)
    sessions = []
    if not ext_root.exists():
        logger.info("VS Code extensions path not found: %s", ext_root)
        return sessions

    for ext_dir in ext_root.glob("anthropic.claude-vscode-*"):
        history_dir = ext_dir / "chat_history"
        for data, raw_path in _load_json_files(history_dir):
            try:
                sessions.append(normalize_session(data, "vscode", detect_device(), raw_path))
            except Exception as e:
                logger.warning("Failed to normalize %s: %s", raw_path, e)
    return sessions


def collect_from_cowork(cowork_path: Optional[str] = None) -> list[dict]:
    """Collect sessions from a local Cowork cache folder.

    Cowork has no public sync API at time of writing, so this reads from a
    local cache directory matching the normalized schema (Option B in SPEC.md).
    """
    if cowork_path is None:
        cowork_path = str(Path.home() / ".claude-search-library" / "cache" / "cowork")

    folder = Path(cowork_path)
    sessions = []
    for data, raw_path in _load_json_files(folder):
        try:
            sessions.append(normalize_session(data, "cowork", detect_device(), raw_path))
        except Exception as e:
            logger.warning("Failed to normalize %s: %s", raw_path, e)
    return sessions


def collect_from_local(folder_path: str) -> list[dict]:
    """Import any JSON files sitting in a local watch folder."""
    folder = Path(folder_path)
    sessions = []
    for data, raw_path in _load_json_files(folder):
        try:
            sessions.append(normalize_session(data, "local", detect_device(), raw_path))
        except Exception as e:
            logger.warning("Failed to normalize %s: %s", raw_path, e)
    return sessions


def _session_to_storage_dict(session: dict) -> dict:
    """Map a normalize_session() dict onto Storage.SESSION_COLUMNS.

    normalize_session() produces a richer in-memory schema (messages, tags,
    raw_path) than the sessions table stores directly; this adapts field
    names (raw_path -> raw_file_path) and fills in the columns Storage
    expects for insert_session().
    """
    return {
        "id": session["id"],
        "source": session["source"],
        "device": session["device"],
        "title": session["title"],
        "created_at": session["created_at"],
        "updated_at": session["updated_at"],
        "duration_seconds": session["duration_seconds"],
        "message_count": session["message_count"],
        "user_message_count": session["user_message_count"],
        "assistant_message_count": session["assistant_message_count"],
        "raw_file_path": session.get("raw_path") or None,
        "summary_file_path": None,
        "processed_at": None,
        "status": "new",
        "review_reason": None,
        "synced_at": None,
        "sync_version": 1,
    }


def _load_raw_export_for_hash(session: dict) -> Optional[dict]:
    """Re-read a session's original export file for content hashing.

    compute_session_hash() must see the same bytes verify_archive() will
    later see when it re-reads and re-hashes the file from disk (see the
    docstring on compute_session_hash in storage.py) — so this re-parses
    the raw file rather than reconstructing an approximation from the
    already-normalized session dict, which previously caused hashes to
    mismatch (normalize_session() adds tokens_approx and backfills
    timestamp, neither of which exist in the original file).

    Returns None if there's no raw_path recorded or the file can't be
    read, in which case the caller falls back to hashing the normalized
    session — internally consistent, but won't match a later re-read.
    """
    raw_path = session.get("raw_path")
    if not raw_path:
        return None
    try:
        with open(raw_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def collect_all(
    claude_ai_folder: Optional[str] = None,
    vscode_extensions_path: Optional[str] = None,
    cowork_path: Optional[str] = None,
    local_folder: Optional[str] = None,
    db_path: Optional[str] = None,
) -> dict:
    """Run all collectors, persist new sessions to storage, and return a
    summary of results.

    Errors in one collector do not prevent the others from running.
    Sessions are deduplicated by content hash via
    Storage.store_session_with_hash() — re-collecting the same conversation
    (even under a different id or from a different source folder) is a
    no-op rather than a duplicate row.
    """
    from src.storage import Storage  # local import: avoids a hard dependency for callers that only normalize

    base = Path.home() / ".claude-search-library" / "data" / "raw_exports"
    claude_ai_folder = claude_ai_folder or str(base / "claude-ai")
    local_folder = local_folder or str(base / "local")

    collectors = {
        "claude-ai": (collect_from_claude_ai, claude_ai_folder),
        "vscode": (collect_from_vscode, vscode_extensions_path),
        "cowork": (collect_from_cowork, cowork_path),
        "local": (collect_from_local, local_folder),
    }

    all_sessions: list[dict] = []
    errors = 0

    for name, (func, arg) in collectors.items():
        try:
            sessions = func(arg)
            all_sessions.extend(sessions)
        except Exception as e:
            logger.error("Collector '%s' failed: %s", name, e)
            errors += 1

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
                hash_source = _load_raw_export_for_hash(session)
                result = db.store_session_with_hash(
                    _session_to_storage_dict(session), hash_source=hash_source
                )
                if result["status"] == "inserted":
                    new_count += 1
            except Exception as e:
                logger.error("Failed to store session %s: %s", session.get("id"), e)
                errors += 1

    return {
        "new": new_count,
        "errors": errors,
        "total": len(all_sessions),
    }


def watch(interval: int = DEFAULT_WATCH_INTERVAL_SECONDS, iterations: Optional[int] = None) -> None:
    """Run collect_all() on a fixed interval, forever (or `iterations` times)."""
    count = 0
    while iterations is None or count < iterations:
        result = collect_all()
        logger.info(
            "Collection run: %d new, %d errors, %d total",
            result["new"], result["errors"], result["total"],
        )
        count += 1
        if iterations is None or count < iterations:
            time.sleep(interval)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Claude Search Library collector")
    parser.add_argument("--watch", action="store_true", help="Run collection on a recurring interval")
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_WATCH_INTERVAL_SECONDS,
        help="Seconds between collection runs when --watch is set (default: 300)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.watch:
        watch(interval=args.interval)
    else:
        result = collect_all()
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
