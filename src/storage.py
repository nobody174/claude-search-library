"""Storage module for Claude Search Library.

SQLite persistence for sessions, summaries, search index, redaction log,
and sync metadata. Optionally loads the cr-sqlite extension for CRDT-based
multi-device merge support (see CLAUDE.md -> Known Blockers: cr-sqlite
Python bindings are not yet reliably available on all platforms, so this
degrades gracefully to plain SQLite when the extension can't be loaded).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".claude-search-library" / "data" / "claude_search.db"

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    device TEXT,
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    duration_seconds INTEGER,
    message_count INTEGER,
    user_message_count INTEGER,
    assistant_message_count INTEGER,
    raw_file_path TEXT,
    summary_file_path TEXT,
    content_hash TEXT UNIQUE,
    processed_at TEXT,
    status TEXT DEFAULT 'processed',
    review_reason TEXT,
    synced_at TEXT,
    sync_version INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source);
CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);

CREATE TABLE IF NOT EXISTS summaries (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id),
    tldr TEXT NOT NULL,
    learnings TEXT NOT NULL,
    patterns TEXT NOT NULL,
    tags TEXT,
    mentioned_tools TEXT,
    mentioned_languages TEXT,
    mentioned_frameworks TEXT,
    estimated_effort_minutes INTEGER,
    topic_categories TEXT,
    confidence_score REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS search_index (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id),
    searchable_text TEXT NOT NULL,
    keywords TEXT
);

CREATE TABLE IF NOT EXISTS redaction_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    redaction_type TEXT,
    original_value TEXT,
    redacted_value TEXT,
    confidence_score REAL,
    redacted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    manually_reviewed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sync_metadata (
    device_id TEXT PRIMARY KEY,
    device_name TEXT,
    last_sync_at TEXT,
    last_heartbeat TEXT,
    pending_changes INTEGER,
    is_hub INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

SESSION_COLUMNS = [
    "id", "source", "device", "title", "created_at", "updated_at",
    "duration_seconds", "message_count", "user_message_count",
    "assistant_message_count", "raw_file_path", "summary_file_path",
    "content_hash", "processed_at", "status", "review_reason",
    "synced_at", "sync_version",
]

SUMMARY_JSON_FIELDS = {"learnings", "patterns", "tags", "mentioned_tools", "mentioned_languages", "mentioned_frameworks", "topic_categories"}

_local = threading.local()


def _try_load_cr_sqlite(conn: sqlite3.Connection) -> bool:
    """Best-effort load of the cr-sqlite extension. Returns True if loaded."""
    try:
        conn.enable_load_extension(True)
        conn.load_extension("crsqlite")
        conn.enable_load_extension(False)
        return True
    except (sqlite3.OperationalError, AttributeError) as e:
        logger.info("cr-sqlite extension not loaded (falling back to plain SQLite): %s", e)
        return False


def _run_schema_upgrades(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT value FROM schema_meta WHERE key = 'version'").fetchone()
    current_version = int(row[0]) if row else 0
    if current_version < SCHEMA_VERSION:
        conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES ('version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()


def init_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Create all tables/indices and return a fresh connection."""
    path = db_path or str(DEFAULT_DB_PATH)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _try_load_cr_sqlite(conn)
    conn.executescript(_SCHEMA)
    conn.commit()
    _run_schema_upgrades(conn)
    return conn


class Storage:
    """Thread-safe wrapper around a SQLite connection for the search library DB.

    Use as a context manager:

        with Storage(db_path) as db:
            db.insert_session(session_dict)
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or str(DEFAULT_DB_PATH)
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    def __enter__(self) -> "Storage":
        self._conn = init_db(self.db_path)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Storage must be used as a context manager (`with Storage(...) as db:`)")
        return self._conn

    @contextmanager
    def _cursor(self):
        with self._lock:
            cur = self.conn.cursor()
            try:
                yield cur
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
            finally:
                cur.close()

    # ---- Sessions ---------------------------------------------------

    def insert_session(self, session_dict: dict) -> str:
        session_id = session_dict["id"]
        values = [session_dict.get(col) for col in SESSION_COLUMNS]
        placeholders = ", ".join("?" for _ in SESSION_COLUMNS)
        with self._cursor() as cur:
            cur.execute(
                f"INSERT INTO sessions ({', '.join(SESSION_COLUMNS)}) VALUES ({placeholders})",
                values,
            )
        return session_id

    def update_session(self, session_id: str, updated_fields: dict) -> bool:
        if not updated_fields:
            return False
        fields = [k for k in updated_fields if k in SESSION_COLUMNS and k != "id"]
        if not fields:
            return False
        set_clause = ", ".join(f"{f} = ?" for f in fields)
        values = [updated_fields[f] for f in fields] + [session_id]
        with self._cursor() as cur:
            cur.execute(f"UPDATE sessions SET {set_clause} WHERE id = ?", values)
            return cur.rowcount > 0

    def get_session(self, session_id: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def get_all_sessions(self) -> list:
        rows = self.conn.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def mark_as_processed(self, session_id: str, status: str) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE sessions SET status = ?, processed_at = ? WHERE id = ?",
                (status, datetime.now(timezone.utc).isoformat(), session_id),
            )
            return cur.rowcount > 0

    def mark_for_review(self, session_id: str, reason: str) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE sessions SET status = 'needs_review', review_reason = ? WHERE id = ?",
                (reason, session_id),
            )
            return cur.rowcount > 0

    # ---- Summaries ----------------------------------------------------

    def store_summary(self, session_id: str, summary_dict: dict) -> bool:
        def _ser(key: str):
            val = summary_dict.get(key)
            return json.dumps(val) if key in SUMMARY_JSON_FIELDS and val is not None else val

        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO summaries
                    (session_id, tldr, learnings, patterns, tags, mentioned_tools,
                     mentioned_languages, mentioned_frameworks, estimated_effort_minutes,
                     topic_categories, confidence_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    tldr = excluded.tldr,
                    learnings = excluded.learnings,
                    patterns = excluded.patterns,
                    tags = excluded.tags,
                    mentioned_tools = excluded.mentioned_tools,
                    mentioned_languages = excluded.mentioned_languages,
                    mentioned_frameworks = excluded.mentioned_frameworks,
                    estimated_effort_minutes = excluded.estimated_effort_minutes,
                    topic_categories = excluded.topic_categories,
                    confidence_score = excluded.confidence_score
                """,
                (
                    session_id,
                    summary_dict.get("session_tldr") or summary_dict.get("tldr"),
                    _ser("learnings"),
                    _ser("patterns"),
                    _ser("tags"),
                    _ser("mentioned_tools"),
                    _ser("mentioned_languages"),
                    _ser("mentioned_frameworks"),
                    summary_dict.get("estimated_effort_minutes"),
                    _ser("topic_categories"),
                    summary_dict.get("confidence_score"),
                ),
            )
        return True

    def get_summary(self, session_id: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM summaries WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        for field in SUMMARY_JSON_FIELDS:
            if result.get(field):
                result[field] = json.loads(result[field])
        return result

    # ---- Search index ---------------------------------------------------

    def index_session(self, session_id: str, searchable_text: str, keywords: Optional[str] = None) -> bool:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO search_index (session_id, searchable_text, keywords)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    searchable_text = excluded.searchable_text,
                    keywords = excluded.keywords
                """,
                (session_id, searchable_text, keywords),
            )
        return True

    # ---- Redaction log ---------------------------------------------------

    def log_redaction(
        self,
        session_id: str,
        redaction_type: str,
        original: str,
        replacement: str,
        confidence: float,
    ) -> int:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO redaction_log
                    (session_id, redaction_type, original_value, redacted_value, confidence_score)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, redaction_type, original, replacement, confidence),
            )
            return cur.lastrowid

    def get_redactions_for_session(self, session_id: str) -> list:
        rows = self.conn.execute(
            "SELECT * FROM redaction_log WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- Utility ---------------------------------------------------

    def check_duplicate(self, content_hash: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sessions WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        return row is not None

    def get_session_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
        return row[0]

    def get_stats(self) -> dict:
        total = self.get_session_count()
        by_status = {
            r["status"]: r["n"]
            for r in self.conn.execute(
                "SELECT status, COUNT(*) as n FROM sessions GROUP BY status"
            ).fetchall()
        }
        by_source = {
            r["source"]: r["n"]
            for r in self.conn.execute(
                "SELECT source, COUNT(*) as n FROM sessions GROUP BY source"
            ).fetchall()
        }
        redaction_count = self.conn.execute("SELECT COUNT(*) FROM redaction_log").fetchone()[0]
        return {
            "total_sessions": total,
            "by_status": by_status,
            "by_source": by_source,
            "total_redactions": redaction_count,
        }


def _run_init() -> None:
    """Full first-run initialization: load config, validate, create
    directories, initialize SQLite (with cr-sqlite if available) and
    ChromaDB, and print a step-by-step success report.
    """
    import sys

    from src.config import create_directories, load_config

    # Some Windows consoles use a legacy codepage (cp1252) that can't encode
    # the checkmark glyphs below; fall back to ASCII there rather than crash.
    ok = "OK" if sys.stdout.encoding and "utf" not in sys.stdout.encoding.lower() else "✓"
    fail = "X" if sys.stdout.encoding and "utf" not in sys.stdout.encoding.lower() else "✗"

    try:
        config = load_config()
    except ValueError as e:
        print(f"{fail} Config invalid: {e}")
        raise SystemExit(1)
    print(f"{ok} Config loaded")

    create_directories(config)
    print(f"{ok} Directories created")

    db_path = config["storage"]["db_path"]
    conn = init_db(db_path)
    conn.close()
    print(f"{ok} SQLite initialized at {db_path}")

    chroma_path = config["storage"]["chromadb_path"]
    from src.embedder import get_collection
    get_collection(chroma_path)
    print(f"{ok} ChromaDB initialized at {chroma_path}")

    print(f"{ok} System ready for use")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Claude Search Library storage")
    parser.add_argument("--init", action="store_true", help="Initialize config, directories, SQLite, and ChromaDB")
    args = parser.parse_args()

    if args.init:
        _run_init()


if __name__ == "__main__":
    main()
