# Task 4: Storage Module (SQLite + cr-sqlite)

Create the storage module (`src/storage.py`) for SQLite + cr-sqlite operations.

## Requirements

1. **Database Initialization**
   - Create all tables: `sessions`, `summaries`, `search_index`, `redaction_log`, `sync_metadata`
   - Load cr-sqlite extension (CRDT support)
   - Set up indices
   - Handle schema upgrades

2. **CRUD Functions for Sessions Table**
   - `insert_session(session_dict) -> session_id`
   - `update_session(session_id, updated_fields) -> bool`
   - `get_session(session_id) -> dict`
   - `get_all_sessions() -> list[dict]`
   - `mark_as_processed(session_id, status)`
   - `mark_for_review(session_id, reason)`

3. **CRUD Functions for Summaries Table**
   - `store_summary(session_id, summary_dict) -> bool`
   - `get_summary(session_id) -> dict`

4. **Functions for Search Index**
   - `index_session(session_id, searchable_text, keywords) -> bool`

5. **Functions for Redaction Log**
   - `log_redaction(session_id, redaction_type, original, replacement, confidence)`
   - `get_redactions_for_session(session_id) -> list[dict]`

6. **Utility Functions**
   - `check_duplicate(content_hash) -> bool`
   - `get_session_count() -> int`
   - `get_stats() -> dict`

7. **Connection Management**
   - Use context manager (with statement)
   - Auto-commit for insert/update
   - Thread-safe

## Database Schema

### sessions table
```sql
CREATE TABLE sessions (
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
```

### summaries table
```sql
CREATE TABLE summaries (
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
```

### search_index table
```sql
CREATE TABLE search_index (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id),
    searchable_text TEXT NOT NULL,
    keywords TEXT
);
```

### redaction_log table
```sql
CREATE TABLE redaction_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    redaction_type TEXT,
    original_value TEXT,
    redacted_value TEXT,
    confidence_score REAL,
    redacted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    manually_reviewed INTEGER DEFAULT 0
);
```

### sync_metadata table
```sql
CREATE TABLE sync_metadata (
    device_id TEXT PRIMARY KEY,
    device_name TEXT,
    last_sync_at TEXT,
    last_heartbeat TEXT,
    pending_changes INTEGER,
    is_hub INTEGER DEFAULT 0
);
```

## Testing

- Use in-memory SQLite (`:memory:`) for unit tests
- Test CRUD operations
- Test indices work
- Test context manager usage

## Output File

Save as: `src/storage.py`

---

**Claude Code ready!**
