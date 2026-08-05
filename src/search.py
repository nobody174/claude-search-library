#
# Claude Search Library
# Author:  nobody174
# Repo:    https://github.com/nobody174/claude-search-library
# Patreon: https://www.patreon.com/c/Nobody174
# License: MIT
# "It's never too late to give up!"
#

"""Search interface module for Claude Search Library.

Provides semantic search (ChromaDB), keyword search (FTS5 with a LIKE
fallback), and a hybrid mode that combines both, merging results with full
session/summary data and applying filters.
"""
from __future__ import annotations

import logging
import sqlite3
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
            result["search_type"] = "semantic"
            results.append(result)
            if len(results) >= top_k:
                break

    return results


def keyword_search(query: str, top_k: int = 10, filters: Optional[dict] = None, db_path: Optional[str] = None) -> list:
    """Keyword search via FTS5 (BM25-ranked), enriched with SQLite data.

    Falls back to the slower LIKE-based search_index scan if the FTS5 index
    hasn't been built yet (create_fts5_index() is run once per processing
    batch — see storage.py — so a brand-new install may not have it).
    """
    with Storage(db_path) as db:
        try:
            fts_results = db.search_fts5(query, top_k=top_k * 3 if filters else top_k)
        except sqlite3.OperationalError:
            logger.info("FTS5 index not available, falling back to LIKE search")
            return keyword_search_like(query, top_k=top_k, filters=filters, db_path=db_path)

        results = []
        for r in fts_results:
            built = _build_result(r["session_id"], r["relevance_score"], db)
            if built is None:
                continue
            result, session, summary = built
            if not _matches_filters(session, summary, filters or {}):
                continue
            result["search_type"] = "keyword"
            results.append(result)
            if len(results) >= top_k:
                break

    return results


def keyword_search_like(query: str, top_k: int = 10, filters: Optional[dict] = None, db_path: Optional[str] = None) -> list:
    """Keyword search via SQL LIKE against the search_index table.

    This is the original (pre-FTS5) keyword search implementation, kept as
    a fallback for databases that haven't built the FTS5 index yet.
    """
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


def hybrid_search(
    query: str,
    top_k: int = 10,
    filters: Optional[dict] = None,
    db_path: Optional[str] = None,
    chroma_path: Optional[str] = None,
    timeout_ms: float = 500,
) -> list:
    """Hybrid search: semantic first, with FTS5 keyword results filling gaps.

    Semantic (ChromaDB) results are preferred — they're tier 1 and always
    kept. Keyword (FTS5) results are only pulled in when semantic search
    was slow (> timeout_ms) or returned fewer than top_k // 2 results, and
    only for session_ids semantic search didn't already find. This keeps
    the "smart" results primary while using FTS5 as a fast-and-cheap
    completeness backstop, per the hybrid design in Task 8.
    """
    results_by_id: dict = {}

    start = time.monotonic()
    semantic_results = semantic_search(query, top_k=top_k, filters=filters, db_path=db_path, chroma_path=chroma_path)
    semantic_time_ms = (time.monotonic() - start) * 1000

    for r in semantic_results:
        results_by_id[r["session_id"]] = {**r, "search_rank": 1, "semantic_time_ms": semantic_time_ms}

    if semantic_time_ms > timeout_ms or len(semantic_results) < top_k // 2:
        keyword_results = keyword_search(query, top_k=top_k, filters=filters, db_path=db_path)
        for r in keyword_results:
            session_id = r["session_id"]
            if session_id not in results_by_id:
                results_by_id[session_id] = {**r, "search_rank": 2}
            else:
                results_by_id[session_id]["found_by_keyword"] = True

    sorted_results = sorted(
        results_by_id.values(),
        key=lambda x: (x["search_rank"], -x.get("relevance_score", 0)),
    )
    return sorted_results[:top_k]


def search(
    query: str,
    mode: str = "semantic",
    top_k: int = 10,
    filters: Optional[dict] = None,
    db_path: Optional[str] = None,
    chroma_path: Optional[str] = None,
) -> list:
    """Route to semantic, keyword, or hybrid search, applying filters and logging."""
    _setup_file_logging()
    start = time.monotonic()

    if mode == "keyword":
        results = keyword_search(query, top_k=top_k, filters=filters, db_path=db_path)
    elif mode == "hybrid":
        results = hybrid_search(query, top_k=top_k, filters=filters, db_path=db_path, chroma_path=chroma_path)
    else:
        results = semantic_search(query, top_k=top_k, filters=filters, db_path=db_path, chroma_path=chroma_path)

    elapsed_ms = (time.monotonic() - start) * 1000
    logger.info(
        "query=%r mode=%s top_k=%d filters=%s results=%d time_ms=%.1f",
        query, mode, top_k, filters, len(results), elapsed_ms,
    )
    return results


class HybridSearch:
    """Object-oriented wrapper over the module-level search functions.

    Provided for callers that want to hold a Storage instance and reuse it
    across multiple searches (e.g. a REPL or a long-lived server process),
    matching the HybridSearch(storage) interface from the Task 8 spec. The
    module-level `search()` / `semantic_search()` / `keyword_search()`
    functions remain the primary API and open their own Storage per call.
    """

    def __init__(self, storage: Storage):
        self.storage = storage

    def semantic_search(self, query: str, top_k: int = 10, filters: Optional[dict] = None) -> list:
        try:
            return semantic_search(query, top_k=top_k, filters=filters, db_path=self.storage.db_path)
        except Exception as e:
            logger.warning("Semantic search failed: %s", e)
            return []

    def keyword_search(self, query: str, top_k: int = 10, filters: Optional[dict] = None) -> list:
        try:
            return keyword_search(query, top_k=top_k, filters=filters, db_path=self.storage.db_path)
        except Exception as e:
            logger.warning("Keyword search failed: %s", e)
            return []

    def hybrid_search(self, query: str, top_k: int = 10, filters: Optional[dict] = None, timeout_ms: float = 500) -> list:
        return hybrid_search(
            query, top_k=top_k, filters=filters, db_path=self.storage.db_path, timeout_ms=timeout_ms
        )

    def search(self, query: str, mode: str = "hybrid", top_k: int = 10, **filters) -> list:
        """Main entry point. mode: "semantic" | "keyword" | "hybrid"."""
        if mode == "semantic":
            return self.semantic_search(query, top_k=top_k, filters=filters or None)
        elif mode == "keyword":
            return self.keyword_search(query, top_k=top_k, filters=filters or None)
        elif mode == "hybrid":
            return self.hybrid_search(query, top_k=top_k, filters=filters or None)
        else:
            raise ValueError(f"Unknown search mode: {mode}")

# Built with assistance from Claude Code by Anthropic.
