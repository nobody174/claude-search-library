"""Storage module for Claude Search Library.

SQLite persistence for sessions, summaries, search index, redaction log,
and sync metadata. Optionally loads the cr-sqlite extension for CRDT-based
multi-device merge support (see CLAUDE.md -> Known Blockers: cr-sqlite
Python bindings are not yet reliably available on all platforms, so this
degrades gracefully to plain SQLite when the extension can't be loaded).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
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
    -- source/created_at keep NOT NULL (the app always provides real values
    -- for both - see collector.py) but need a DEFAULT anyway: cr-sqlite
    -- requires every NOT NULL column on a CRR table to have one, for
    -- forwards/backwards schema compatibility across devices that might be
    -- on slightly different app versions.
    id TEXT NOT NULL PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'unknown',
    device TEXT,
    title TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT,
    duration_seconds INTEGER,
    message_count INTEGER,
    user_message_count INTEGER,
    assistant_message_count INTEGER,
    raw_file_path TEXT,
    summary_file_path TEXT,
    -- Not UNIQUE at the DB level: cr-sqlite disallows any unique index
    -- besides the primary key on a CRR table (independent devices can't
    -- consistently enforce cross-device uniqueness). Duplicate detection
    -- is already done in application code before every insert - see
    -- Storage.check_duplicate()/store_session_with_hash().
    content_hash TEXT,
    processed_at TEXT,
    status TEXT DEFAULT 'processed',
    review_reason TEXT,
    synced_at TEXT,
    sync_version INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source);
CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_content_hash ON sessions(content_hash);

-- session_id intentionally has no REFERENCES/FK constraint: cr-sqlite
-- disallows *checked* foreign keys on CRR (CRDT) tables, since replicated
-- changesets can legitimately arrive out of order (a summary's changeset
-- reaching a device before its session's changeset does) - see
-- crsql_as_crr()'s own error message. Referential integrity for this
-- relationship is enforced at the application layer instead (callers
-- already check get_session() before trusting a summary).
CREATE TABLE IF NOT EXISTS summaries (
    session_id TEXT NOT NULL PRIMARY KEY,
    tldr TEXT NOT NULL DEFAULT '',
    learnings TEXT NOT NULL DEFAULT '[]',
    patterns TEXT NOT NULL DEFAULT '[]',
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

CREATE TABLE IF NOT EXISTS api_costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_input_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_input_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL,
    called_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_api_costs_called_at ON api_costs(called_at);
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


CR_SQLITE_CRR_TABLES = ("sessions", "summaries")

# Vendored per-platform binary, not a pip package - cr-sqlite ships prebuilt
# native extensions per OS/arch (see https://github.com/vlcn-io/cr-sqlite/releases),
# not something `pip install` can provide. Loading by bare name ("crsqlite")
# depends on the OS's shared-library search path/cwd, which is unreliable
# across how this app gets launched (CLI, server.py, tests) - load by
# explicit path instead so it works regardless of cwd.
_CR_SQLITE_EXTENSION_PATH = Path(__file__).resolve().parent.parent / "vendor" / "cr-sqlite" / "crsqlite"


def _try_load_cr_sqlite(conn: sqlite3.Connection) -> bool:
    """Best-effort load of the cr-sqlite extension. Returns True if loaded."""
    try:
        conn.enable_load_extension(True)
        conn.load_extension(str(_CR_SQLITE_EXTENSION_PATH))
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


def compute_session_hash(session_dict: dict) -> str:
    """Compute a SHA256 hash of session content, for deduplication and
    integrity verification.

    The hash covers only `messages` and `title` — fields present verbatim
    in the original export file — rather than the session id or any field
    added during normalization (source, device, tokens_approx, etc.). This
    is deliberate: the same conversation collected from two different
    sources/devices should hash identically, and verify_archive() re-reads
    and re-hashes the *raw file on disk* to detect corruption, which only
    works if hashing is defined purely on the raw content shape rather than
    on collector.py's internal normalized representation. Callers must pass
    the raw export dict (as loaded from the JSON file), not a
    normalize_session()-shaped dict.
    """
    content = json.dumps(
        {
            "messages": session_dict.get("messages", []),
            "title": session_dict.get("title", ""),
        },
        sort_keys=True,
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def init_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Create all tables/indices and return a fresh connection."""
    path = db_path or str(DEFAULT_DB_PATH)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    cr_sqlite_loaded = _try_load_cr_sqlite(conn)
    conn.executescript(_SCHEMA)
    if cr_sqlite_loaded:
        for table in CR_SQLITE_CRR_TABLES:
            conn.execute(f"SELECT crsql_as_crr('{table}')")
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

    # ---- API cost tracking ------------------------------------------

    def log_api_cost(
        self,
        session_id: Optional[str],
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        called_at: Optional[str] = None,
    ) -> int:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO api_costs
                    (session_id, model, input_tokens, output_tokens,
                     cache_creation_input_tokens, cache_read_input_tokens,
                     cost_usd, called_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    model,
                    input_tokens,
                    output_tokens,
                    cache_creation_input_tokens,
                    cache_read_input_tokens,
                    cost_usd,
                    called_at or datetime.now(timezone.utc).isoformat(),
                ),
            )
            return cur.lastrowid

    def get_costs(self, start: Optional[str] = None, end: Optional[str] = None) -> dict:
        """Aggregate API spend, optionally bounded by ISO timestamp range
        [start, end). Returns totals plus a per-model breakdown."""
        query = "SELECT * FROM api_costs WHERE 1=1"
        params: list = []
        if start:
            query += " AND called_at >= ?"
            params.append(start)
        if end:
            query += " AND called_at < ?"
            params.append(end)

        rows = [dict(r) for r in self.conn.execute(query, params).fetchall()]

        by_model: dict = {}
        for r in rows:
            m = by_model.setdefault(
                r["model"],
                {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
            )
            m["calls"] += 1
            m["input_tokens"] += r["input_tokens"]
            m["output_tokens"] += r["output_tokens"]
            m["cost_usd"] += r["cost_usd"]

        return {
            "calls": len(rows),
            "total_cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
            "by_model": {k: {**v, "cost_usd": round(v["cost_usd"], 6)} for k, v in by_model.items()},
        }

    # ---- Utility ---------------------------------------------------

    def check_duplicate(self, content_hash: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sessions WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        return row is not None

    def store_session_with_hash(self, session_dict: dict, hash_source: Optional[dict] = None) -> dict:
        """Insert a session, computing its content hash and skipping the
        insert entirely if a session with the same content already exists.

        By default the hash is computed from `session_dict` itself (its
        `messages`/`title` fields). Pass `hash_source` to hash a different
        dict instead — e.g. the original raw export dict rather than a
        normalized/reshaped version — so the stored hash matches what a
        later re-read of the raw file on disk (see verify_archive()) will
        recompute. `session_dict`'s own `messages`/`title` are otherwise
        unused for hashing when `hash_source` is given.

        If a session with this exact id already exists but its content
        legitimately changed since it was first collected (a growing live
        conversation, a re-export overwriting the raw file, etc.), this
        updates the existing row in place - refreshing content_hash so
        verify_archive() stops reporting a permanent mismatch, and
        resetting status to "new" so it gets (re)summarized - rather than
        attempting a second INSERT with the same id, which previously
        failed outright with a raw sqlite3.IntegrityError and left the
        stale hash in place forever (see ROADMAP.md #9).
        """
        content_hash = compute_session_hash(hash_source if hash_source is not None else session_dict)

        existing = self.get_session(session_dict["id"])
        if existing is not None:
            if existing.get("content_hash") == content_hash:
                return {"status": "skipped_duplicate", "hash": content_hash, "id": session_dict["id"]}
            updated_fields = {
                k: session_dict.get(k)
                for k in ("title", "updated_at", "message_count", "user_message_count", "assistant_message_count", "raw_file_path")
                if k in session_dict
            }
            updated_fields["content_hash"] = content_hash
            updated_fields["status"] = "new"
            self.update_session(session_dict["id"], updated_fields)
            return {"status": "updated", "hash": content_hash, "id": session_dict["id"]}

        if self.check_duplicate(content_hash):
            return {"status": "skipped_duplicate", "hash": content_hash}

        session_dict = dict(session_dict, content_hash=content_hash)
        session_id = self.insert_session(session_dict)
        return {"status": "inserted", "hash": content_hash, "id": session_id}

    # ---- JSONL durability mirror ------------------------------------

    def export_summaries_to_jsonl(self, output_file: Optional[str] = None) -> int:
        """Mirror all summaries to a JSONL file for durability.

        This is a plain backup, not the source of truth — SQLite remains
        authoritative during normal operation. If the database is ever
        corrupted, delete it, reinitialize, and call
        `restore_summaries_from_jsonl()` to rebuild the summaries table
        from this file.
        """
        if output_file is None:
            output_file = os.path.expanduser(
                "~/.claude-search-library/summaries/ai-summaries.jsonl"
            )

        os.makedirs(os.path.dirname(output_file), exist_ok=True)

        summaries = self.conn.execute("SELECT * FROM summaries").fetchall()

        count = 0
        with open(output_file, "w", encoding="utf-8") as f:
            for summary in summaries:
                f.write(json.dumps(dict(summary)) + "\n")
                count += 1

        return count

    def restore_summaries_from_jsonl(self, input_file: Optional[str] = None) -> int:
        """Restore the summaries table from a JSONL backup.

        Uses INSERT OR REPLACE, so this is safe to re-run and will not
        duplicate rows. Raises FileNotFoundError if no backup exists at
        the given (or default) path.
        """
        if input_file is None:
            input_file = os.path.expanduser(
                "~/.claude-search-library/summaries/ai-summaries.jsonl"
            )

        if not os.path.exists(input_file):
            raise FileNotFoundError(f"No JSONL backup found at {input_file}")

        count = 0
        with self._cursor() as cur:
            with open(input_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    summary_dict = json.loads(line)
                    cur.execute(
                        """
                        INSERT OR REPLACE INTO summaries
                            (session_id, tldr, learnings, patterns, tags,
                             mentioned_tools, mentioned_languages, mentioned_frameworks,
                             estimated_effort_minutes, topic_categories, confidence_score)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            summary_dict.get("session_id"),
                            summary_dict.get("tldr"),
                            summary_dict.get("learnings"),
                            summary_dict.get("patterns"),
                            summary_dict.get("tags"),
                            summary_dict.get("mentioned_tools"),
                            summary_dict.get("mentioned_languages"),
                            summary_dict.get("mentioned_frameworks"),
                            summary_dict.get("estimated_effort_minutes"),
                            summary_dict.get("topic_categories"),
                            summary_dict.get("confidence_score"),
                        ),
                    )
                    count += 1

        return count

    # ---- FTS5 full-text search ---------------------------------------

    def create_fts5_index(self) -> None:
        """Create (or rebuild) an FTS5 full-text index over summaries.

        Indexes tldr + learnings + patterns as one combined searchable_text
        column. Run once after the first processing batch, and again any
        time you want a full rebuild (e.g. after a bulk re-summarize).

        Note: this is a standalone FTS5 table populated by a one-time
        `INSERT ... SELECT`, not an "external content" table
        (`content=summaries, content_rowid=rowid`). External-content FTS5
        tables require the content table to have a real INTEGER rowid the
        FTS index can key against; `summaries.session_id` is a TEXT PRIMARY
        KEY, so there is no such rowid to alias, and that configuration
        fails at query time. The trade-off is that this index is a
        snapshot — call create_fts5_index() again after summaries change to
        keep it current, rather than getting automatic sync via triggers.
        """
        with self._cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS fts5_summaries")
            cursor.execute(
                """
                CREATE VIRTUAL TABLE fts5_summaries USING fts5(
                    session_id UNINDEXED,
                    searchable_text
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO fts5_summaries (session_id, searchable_text)
                SELECT
                    session_id,
                    tldr || ' ' || COALESCE(learnings, '') || ' ' || COALESCE(patterns, '')
                FROM summaries
                """
            )

    def search_fts5(self, query: str, top_k: int = 10) -> list:
        """FTS5 keyword search with BM25 ranking.

        Fast, exact/partial keyword matching. Returns a list of
        {"session_id", "relevance_score", "search_type"} dicts, best match
        first. Assumes create_fts5_index() has already been run; raises
        sqlite3.OperationalError (propagated to the caller) if the index
        doesn't exist yet.
        """
        rows = self.conn.execute(
            """
            SELECT session_id, rank AS score
            FROM fts5_summaries
            WHERE fts5_summaries MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, top_k),
        ).fetchall()

        return [
            {
                "session_id": row["session_id"],
                # FTS5's bm25-derived `rank` column is negative (more
                # negative = more relevant); normalize to a positive score
                # so it's comparable to ChromaDB's 0-1 relevance_score.
                "relevance_score": abs(row["score"]),
                "search_type": "keyword",
            }
            for row in rows
        ]

    # ---- Archive verification -----------------------------------------

    def verify_archive(self, verbose: bool = False) -> dict:
        """Comprehensive archive integrity check.

        Runs 7 checks (DB integrity, session/summary/index count
        consistency, per-session raw-file + content-hash verification,
        raw chat file presence, JSONL mirror validity, sync_metadata
        sanity, and FTS5 index status) and returns a structured report:

            {
                "healthy": bool,
                "checks_passed": int,
                "checks_failed": int,
                "errors": [...],
                "warnings": [...],
                "stats": {...},
                "timestamp": "...",
            }

        A failed check (exception, corrupt DB, bad JSON) increments
        checks_failed and appends to errors. A completed check that finds
        something worth flagging but not fatal (missing JSONL mirror not
        yet created, FTS5 index not yet built) still counts as passed and
        appends to warnings instead. `healthy` is True iff errors is empty
        — warnings alone do not make the archive unhealthy.
        """
        errors: list = []
        warnings: list = []
        checks_passed = 0
        checks_failed = 0
        stats: dict = {}

        def _log(step: str, total: int, label: str) -> None:
            if verbose:
                print(f"Check {step}/{total}: {label}...")

        total_checks = 7

        # Check 1: Database integrity
        _log(1, total_checks, "Database integrity")
        try:
            result = self.conn.execute("PRAGMA integrity_check").fetchone()
            if result[0] != "ok":
                errors.append(f"Database integrity check failed: {result[0]}")
                checks_failed += 1
            else:
                checks_passed += 1
        except Exception as e:
            errors.append(f"Database integrity check error: {e}")
            checks_failed += 1

        # Check 2: Session/summary/search_index count consistency
        _log(2, total_checks, "Session count consistency")
        try:
            sessions = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            summaries = self.conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]
            index_rows = self.conn.execute("SELECT COUNT(*) FROM search_index").fetchone()[0]

            stats["total_sessions"] = sessions
            stats["total_summaries"] = summaries
            stats["total_search_index_rows"] = index_rows

            if sessions != summaries:
                warnings.append(f"Session/summary mismatch: {sessions} sessions but {summaries} summaries")
            if sessions != index_rows:
                warnings.append(f"Session/search_index mismatch: {sessions} sessions but {index_rows} index rows")

            checks_passed += 1
        except Exception as e:
            errors.append(f"Session count check error: {e}")
            checks_failed += 1

        # Check 3: Content hash validation — re-hash each session's raw
        # file (when present) and compare to the stored content_hash.
        _log(3, total_checks, "Content hash validation")
        try:
            samples = self.conn.execute(
                "SELECT id, content_hash, raw_file_path FROM sessions WHERE content_hash IS NOT NULL"
            ).fetchall()

            checked = 0
            mismatches = 0
            missing_raw_files = 0
            for row in samples:
                raw_path = row["raw_file_path"]
                if not raw_path or not os.path.exists(raw_path):
                    missing_raw_files += 1
                    continue
                try:
                    with open(raw_path, "r", encoding="utf-8") as f:
                        raw_session = json.load(f)
                except (OSError, json.JSONDecodeError) as e:
                    warnings.append(f"Session {row['id']}: could not read/parse raw file for hash check ({e})")
                    continue

                recomputed = compute_session_hash(raw_session)
                checked += 1
                if recomputed != row["content_hash"]:
                    mismatches += 1
                    errors.append(f"Session {row['id']}: content hash mismatch (raw file may have changed)")

            stats["hash_samples_checked"] = checked
            stats["hash_samples_valid"] = checked - mismatches
            if missing_raw_files:
                warnings.append(f"{missing_raw_files} session(s) have no readable raw file to verify hash against")

            checks_passed += 1
        except Exception as e:
            errors.append(f"Hash validation error: {e}")
            checks_failed += 1

        # Check 4: Raw chat files exist for every session that references one
        _log(4, total_checks, "Raw chat files validation")
        try:
            rows = self.conn.execute(
                "SELECT id, raw_file_path FROM sessions WHERE raw_file_path IS NOT NULL"
            ).fetchall()
            missing = [r["id"] for r in rows if not os.path.exists(r["raw_file_path"])]

            stats["sessions_with_raw_path"] = len(rows)
            stats["raw_chat_files_missing"] = len(missing)
            if missing:
                warnings.append(f"{len(missing)} session(s) reference a raw chat file that no longer exists")

            checks_passed += 1
        except Exception as e:
            errors.append(f"Raw chat files check error: {e}")
            checks_failed += 1

        # Check 5: JSONL mirror is readable and internally valid
        _log(5, total_checks, "JSONL mirror validation")
        try:
            jsonl_path = os.path.expanduser("~/.claude-search-library/summaries/ai-summaries.jsonl")

            if os.path.exists(jsonl_path):
                valid_lines = 0
                invalid_lines = 0
                with open(jsonl_path, "r", encoding="utf-8") as f:
                    for lineno, line in enumerate(f, start=1):
                        if not line.strip():
                            continue
                        try:
                            json.loads(line)
                            valid_lines += 1
                        except json.JSONDecodeError:
                            invalid_lines += 1
                            errors.append(f"Invalid JSON in JSONL mirror at line {lineno}")

                stats["jsonl_lines"] = valid_lines
                if invalid_lines:
                    stats["jsonl_invalid_lines"] = invalid_lines
            else:
                stats["jsonl_lines"] = 0
                warnings.append("JSONL mirror not found (not created yet — run export_summaries_to_jsonl())")

            checks_passed += 1
        except Exception as e:
            errors.append(f"JSONL mirror check error: {e}")
            checks_failed += 1

        # Check 6: Sync metadata sanity
        _log(6, total_checks, "Sync metadata validation")
        try:
            devices = self.conn.execute("SELECT * FROM sync_metadata").fetchall()
            stats["devices_registered"] = len(devices)

            for device in devices:
                if device["device_name"] is None:
                    warnings.append(f"Device {device['device_id']} has no device_name set")

            checks_passed += 1
        except Exception as e:
            errors.append(f"Sync metadata check error: {e}")
            checks_failed += 1

        # Check 7: FTS5 index status
        _log(7, total_checks, "FTS5 index validation")
        try:
            fts5_exists = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='fts5_summaries'"
            ).fetchone()

            stats["fts5_index_exists"] = fts5_exists is not None
            if fts5_exists is None:
                warnings.append("FTS5 index not yet created (run create_fts5_index() after processing)")

            checks_passed += 1
        except Exception as e:
            errors.append(f"FTS5 index check error: {e}")
            checks_failed += 1

        return {
            "healthy": len(errors) == 0,
            "checks_passed": checks_passed,
            "checks_failed": checks_failed,
            "errors": errors,
            "warnings": warnings,
            "stats": stats,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

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
    parser.add_argument(
        "--restore-from-jsonl",
        action="store_true",
        help="Rebuild the summaries table from the JSONL durability mirror",
    )
    args = parser.parse_args()

    if args.init:
        _run_init()
    elif args.restore_from_jsonl:
        with Storage() as db:
            count = db.restore_summaries_from_jsonl()
        print(f"Restored {count} summaries from JSONL backup")


if __name__ == "__main__":
    main()
