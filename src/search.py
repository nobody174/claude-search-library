"""Search interface module for Claude Search Library.

Provides semantic search (ChromaDB) and keyword search (SQLite LIKE),
merging results with full session/summary data and applying filters.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.embedder import semantic_search as _chroma_semantic_search
from src.storage import Storage

logger = logging.getLogger(__name__)

LOG_PATH = Path.home() / ".claude-search-library" / "logs" / "search.log"
RAW_CHATS_DIR = Path.home() / ".claude-search-library" / "raw_chats"


def _setup_file_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not any(isinstance(h, logging.FileHandler) and h.baseFilename == str(LOG_PATH) for h in logger.handlers):
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


def _matches_filters(session: dict, summary: Optional[dict], filters: dict) -> bool:
    if not filters:
        return True

    source = filters.get("source")
    if source and session.get("source") != source:
        return False

    device = filters.get("device")
    if device and session.get("device") != device:
        return False

    date_range = filters.get("date_range")
    if date_range:
        created_at = session.get("created_at") or ""
        start = date_range.get("start")
        end = date_range.get("end")
        if start and created_at < start:
            return False
        if end and created_at > end:
            return False

    tags = filters.get("tags")
    if tags:
        if isinstance(tags, str):
            tags = [tags]
        summary_tags = set((summary or {}).get("tags") or [])
        if not summary_tags.intersection(tags):
            return False

    return True


def _build_result(session_id: str, relevance_score: float, db: Storage) -> Optional[dict]:
    session = db.get_session(session_id)
    if session is None:
        return None
    summary = db.get_summary(session_id)

    patterns = (summary or {}).get("patterns") or []
    top_pattern = patterns[0] if patterns else None

    raw_path = session.get("raw_file_path")
    link_to_raw = f"file://{raw_path}" if raw_path else None

    return {
        "session_id": session_id,
        "title": session.get("title"),
        "tldr": (summary or {}).get("tldr"),
        "source": session.get("source"),
        "device": session.get("device"),
        "created_at": session.get("created_at"),
        "relevance_score": relevance_score,
        "top_pattern": top_pattern,
        "link_to_raw": link_to_raw,
    }, session, summary


def semantic_search(query: str, top_k: int = 10, filters: Optional[dict] = None, db_path: Optional[str] = None, chroma_path: Optional[str] = None) -> list:
    """Semantic search over session summaries via ChromaDB, enriched with SQLite data."""
    chroma_results = _chroma_semantic_search(query, top_k=top_k * 3 if filters else top_k, chroma_path=chroma_path)

    results = []
    with Storage(db_path) as db:
        for r in chroma_results:
            built = _build_result(r["session_id"], r["relevance_score"], db)
            if built is None:
                continue
            result, session, summary = built
            if not _matches_filters(session, summary, filters or {}):
                continue
            results.append(result)
            if len(results) >= top_k:
                break

    return results


def keyword_search(query: str, top_k: int = 10, filters: Optional[dict] = None, db_path: Optional[str] = None) -> list:
    """Keyword search via SQL LIKE against the search_index table."""
    like_pattern = f"%{query}%"

    with Storage(db_path) as db:
        rows = db.conn.execute(
            """
            SELECT s.id as session_id, s.title, s.source, s.device, s.created_at,
                   s.raw_file_path,
                   sm.tldr, sm.patterns, sm.tags,
                   CASE WHEN s.title LIKE ? THEN 2 ELSE 1 END as rank
            FROM search_index si
            JOIN sessions s ON s.id = si.session_id
            LEFT JOIN summaries sm ON sm.session_id = s.id
            WHERE si.searchable_text LIKE ? OR si.keywords LIKE ?
            ORDER BY rank DESC, s.created_at DESC
            LIMIT ?
            """,
            (like_pattern, like_pattern, like_pattern, top_k * 3 if filters else top_k),
        ).fetchall()

        results = []
        for row in rows:
            row_dict = dict(row)
            session = {
                "source": row_dict["source"],
                "device": row_dict["device"],
                "created_at": row_dict["created_at"],
            }
            import json as _json
            summary = {
                "tldr": row_dict["tldr"],
                "patterns": _json.loads(row_dict["patterns"]) if row_dict["patterns"] else [],
                "tags": _json.loads(row_dict["tags"]) if row_dict["tags"] else [],
            }
            if not _matches_filters(session, summary, filters or {}):
                continue

            patterns = summary["patterns"]
            raw_path = row_dict["raw_file_path"]
            results.append(
                {
                    "session_id": row_dict["session_id"],
                    "title": row_dict["title"],
                    "tldr": row_dict["tldr"],
                    "source": row_dict["source"],
                    "device": row_dict["device"],
                    "created_at": row_dict["created_at"],
                    "relevance_score": 1.0 if row_dict["rank"] == 2 else 0.5,
                    "top_pattern": patterns[0] if patterns else None,
                    "link_to_raw": f"file://{raw_path}" if raw_path else None,
                }
            )
            if len(results) >= top_k:
                break

    return results


def search(query: str, mode: str = "semantic", top_k: int = 10, filters: Optional[dict] = None, db_path: Optional[str] = None, chroma_path: Optional[str] = None) -> list:
    """Route to semantic or keyword search, applying filters and logging."""
    _setup_file_logging()
    start = time.monotonic()

    if mode == "keyword":
        results = keyword_search(query, top_k=top_k, filters=filters, db_path=db_path)
    else:
        results = semantic_search(query, top_k=top_k, filters=filters, db_path=db_path, chroma_path=chroma_path)

    elapsed_ms = (time.monotonic() - start) * 1000
    logger.info(
        "query=%r mode=%s top_k=%d filters=%s results=%d time_ms=%.1f",
        query, mode, top_k, filters, len(results), elapsed_ms,
    )
    return results
