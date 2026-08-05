# Claude Search Library — Project Documentation

## Project Overview

**Claude Search Library** is a distributed, offline-first personal knowledge management system that:
- Collects chat sessions from all Claude interfaces (Claude.ai, VS Code, Cowork)
- Summarizes sessions into actionable insights using Claude API
- Stores encrypted summaries + raw chats on GitHub (private repo)
- Syncs seamlessly across unlimited devices (desktop, laptops, phones, tablets)
- Provides instant semantic search via local ChromaDB
- Uses master passphrase + Google Authenticator 2FA for security
- Auto-merges conflicts via cr-sqlite CRDT

**Status**: Under development (10 Claude Code build tasks)

---

## Known Blockers

Resolved blockers (cr-sqlite Python bindings, no TLS on server.py) have
moved to [CHANGELOG.md](CHANGELOG.md). Still open:

| Issue | Impact | Status | Solution |
|-------|--------|--------|----------|
| GitHub API rate limits | Sync frequency | Low | 5-min interval ≈ 288 calls/day (well under limit) |
| Mobile TOTP sync | iPhone setup | Low | See [BACKLOG.md](BACKLOG.md) |
| ChromaDB persistence | Search rebuilding | Low | Handled by PersistentClient |

---

## Architecture at a Glance

```
Each Device (Desktop | Laptop | Phone)
    ↓
Collect chats from multiple sources
    ↓
Process with Claude API (summarize)
    ↓
Redact secrets
    ↓
Store locally (SQLite + ChromaDB)
    ↓
Encrypt & sync to GitHub (every 5 min)
    ↓
Pull updates from other devices
    ↓
Auto-merge via cr-sqlite CRDT
    ↓
Rebuild ChromaDB
    ↓
Search locally (semantic + keyword)
```

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Local DB** | SQLite + cr-sqlite | CRDT auto-merge |
| **Embeddings** | ChromaDB | Local semantic search |
| **Encryption** | Fernet (cryptography) | Proven AES-128 |
| **2FA** | Google Authenticator | Industry standard |
| **Sync** | Git + GitHub | Version control + audit |
| **Conflict Resolution** | cr-sqlite CRDT | Automatic merging |
| **API** | Claude (summarization) | Best-in-class |
| **CLI** | Click | Terminal interface |
| **Web Server** | Flask | Lightweight REST |
| **Frontend** | React | Multi-device compatible |

---

## Key Decisions

### 1. Encryption: Master Passphrase + TOTP 2FA

**Decision**: Users provide both factors to unlock encryption key
**Why**: Brute-force resistant (148 bits entropy vs. single factor)
**Trade-off**: Slightly more setup friction, but significantly more secure

### 2. Storage: Keep Raw Chats on GitHub

**Decision**: Store both summaries + raw chats encrypted on GitHub
**Why**: Full backup, multi-device access, negligible space (~10 MB/year)
**Trade-off**: GitHub becomes larger (but still tiny)

### 3. Sync: Distributed via GitHub, No Central Hub

**Decision**: Each device is autonomous; GitHub is the transport layer
**Why**: Laptop can work fully offline anywhere; desktop shutdown doesn't break syncing
**Trade-off**: No real-time sync (5-min interval acceptable)

### 4. Conflict Resolution: cr-sqlite CRDT

**Decision**: Automatic Last-Write-Wins (LWW) merging on timestamp
**Why**: No manual resolution queue; all devices converge automatically
**Trade-off**: If two edits happen simultaneously, one is lost (rare, low impact)

### 5. Mobile Access: React Web UI (not native app)

**Decision**: Start with responsive web UI in React
**Why**: Faster to build, works in Safari, easier maintenance
**Trade-off**: Slightly less performant than native app

---

## Core Modules

### src/collector.py
Scans 6 data sources:
1. Claude.ai (manual JSON exports, or the official Data Export via `src/claude_export_import.py`)
2. VS Code Claude extension (~/.vscode/extensions/...)
3. Claude Code (local `~/.claude/projects/*.jsonl` transcripts)
4. Claude desktop app (local Chromium IndexedDB cache — see CHANGELOG.md for the full investigation)
5. Cowork (local JSONL, same shape as Claude Code)
6. Local folder (watch for new JSON)

**Output**: Normalized chat objects matching schema

### src/processor.py
Calls Claude API to summarize each chat. The transcript is wrapped in
explicit `<transcript_to_analyze>` delimiters plus a "don't participate"
instruction before being sent (see CHANGELOG.md 2026-08-04 — without
this, some sessions pulled the model into continuing the conversation
instead of summarizing it). System prompt asks for exactly this JSON
shape:

```
Analyze this chat session. Respond ONLY with valid JSON (no markdown, no preamble).

User and Claude worked on: {description}

Respond with exactly this structure:
{
    "session_tldr": "One sentence: what was accomplished",
    "learnings": ["Key takeaway 1", "Key takeaway 2"],
    "patterns": ["Reusable workflow 1", "Reusable workflow 2"],
    "tags": ["tag1", "tag2"],
    "mentioned_tools": ["Tool1", "Tool2"],
    "mentioned_languages": ["Python", "TypeScript"],
    "mentioned_frameworks": ["Phaser 3", "NeoForge"],
    "estimated_effort_minutes": 45,
    "topic_categories": ["minecraft-modding", "debugging"],
    "confidence_score": 0.92
}
```

- Batched processing (respects rate limits)
- Saves summaries as sidecar JSON files

**Output**: Summary JSON alongside originals

### src/redactor.py
Masks sensitive data before storage/indexing, ordered highest-confidence
pattern first so a specific match (e.g. a GitHub token) claims it before
a looser one (e.g. email) could:

| Pattern | Replacement | Confidence |
|---------|-------------|------------|
| GitHub token (`ghp_...`) | `[GH_TOKEN_REDACTED]` | 0.99 |
| AWS key (`AKIA...`) | `[AWS_KEY_REDACTED]` | 0.99 |
| Discord token | `[DISCORD_TOKEN_REDACTED]` | 0.95 |
| Generic API key | `[API_KEY_REDACTED]` | 0.9 |
| Patreon link | `[PATREON_LINK]` | 0.85 |
| Email | `[EMAIL_REDACTED]` | 0.8 |
| IP address | `[IP_REDACTED]` | 0.7 |

- Flags sessions for manual review if > 3 redactions (`REVIEW_THRESHOLD` in `src/redactor.py`)
- Audit trail in SQLite (`redaction_log` table)

**Output**: Redacted summaries + redaction log

### src/storage.py
SQLite operations:
- CRUD for sessions, summaries, search_index, redaction_log, sync_metadata
- cr-sqlite integration (CRDT support) — `sessions`/`summaries` are real
  CRR tables; `crsql_changes` is the actual sync payload (see src/sync.py)
- Schema initialization + migrations (`init_db()`, `SCHEMA_VERSION`) —
  raises `SchemaTooNewError` if a database's own recorded schema
  version is ahead of what this code understands, instead of silently
  running old-shape queries against it (distinct from `sync_protocol_
  version` in src/sync.py, which guards the sync wire format, not the
  local schema — see CHANGELOG.md's 2026-08-06 entry)
- `verify_archive()`: 7 integrity checks (DB integrity, session/summary/
  index count consistency, per-session content-hash validation, raw
  chat + summary sidecar file presence, JSONL mirror validity, sync
  metadata sanity, FTS5 index status) — this is what `cli.py verify`
  and the web UI's health check both call
- JSONL durability mirror (`export_summaries_to_jsonl()`/
  `restore_summaries_from_jsonl()`): a flat backup of the summaries
  table, not the source of truth — lets you rebuild summaries if
  SQLite itself gets corrupted

**Output**: Persistent local database

### src/embedder.py
ChromaDB vector embeddings:
- Embed each summary (local-only, not synced)
- Semantic search via cosine similarity
- Re-index on sync

**Output**: Vector embeddings for search

### src/crypto.py
Encryption + 2FA:
- Master passphrase + TOTP key derivation
- Fernet symmetric encryption
- Device setup (first time vs. joining existing)
- Backup codes generation

**Output**: Encryption key + 2FA verification

### src/sync.py
GitHub-based distributed sync:
- 5-minute daemon loop
- Push: real `crsql_changes` changesets (one encrypted file per push,
  per device, named by the `db_version` it covers) + raw chat files —
  not whole-row session/summary files (that was the pre-2026-08-05
  design; see CHANGELOG.md)
- Pull: applies changesets via `INSERT INTO crsql_changes` — real
  per-column CRDT merge, not a hand-written Last-Write-Wins comparison
- Rebuild ChromaDB + FTS5 index after every pull that brought in changes

**Output**: Synchronized database across devices

### src/search.py + cli.py + server.py
Search interface:
- Semantic search (ChromaDB, cosine similarity)
- Keyword search: FTS5 with BM25 ranking is the primary path
  (`search_fts5()`), falling back to a slower `LIKE`-based scan only if
  the FTS5 index hasn't been built yet for that session
- `hybrid` mode (default): semantic first, falls back to keyword when
  semantic is slow or sparse
- CLI commands (Click)
- REST API (Flask)

**Output**: Search results as JSON

### src/config.py
Configuration management:
- Load config.yaml + .env overrides
- Create directories
- Validate required fields

**Output**: Merged config dict

### public/index.html + src/api.js
Web UI:
- Setup page (passphrase + TOTP)
- Search interface (results + filters)
- Session detail view
- Device sync status

**Output**: React SPA for multi-device access

---

## File Structure

See README.md's [Project Structure](README.md#project-structure) section
for the current, real file tree — this section used to duplicate it with
a pre-build/aspirational version (referencing "Task N" labels from the
original 10-task build plan) that drifted out of sync as real modules
(`cost_tracker.py`, `maintenance.py`, `orchestration.py`, `export.py`,
`claude_export_import.py`, `auth_ui.py`, and more) were added.

---

## Setup Instructions

See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) for the current,
step-by-step setup walkthrough (first device, additional devices, web
UI/mobile access) — this used to be a shorter duplicate that drifted
out of sync (missing the `cli.py verify` step DEPLOYMENT_GUIDE.md adds
before syncing).

---

## Development Workflow

### Adding a New Chat Source

1. Add collector function to `src/collector.py` (e.g., `collect_from_X()`)
2. Call from `collect_all()`
3. Normalize to schema
4. Test with sample data

### Adding a New Search Filter

1. Update `src/search.py` filter logic
2. Update CLI in `cli.py`
3. Update REST API in `server.py`
4. Update web UI in `public/index.html`

### Adding a New Redaction Rule

1. Add regex pattern to `src/redactor.py`
2. Test with mock data
3. Update redaction_type enum

---

## Common Commands

See README.md's [Common Commands](README.md#common-commands) section for
the current, complete command reference — this used to be a shorter
duplicate that drifted stale (referenced `python3 src/sync.py --pull`
directly instead of the `cli.py sync` wrapper, and was missing `verify`
and the REST endpoints added since).

---

## Security

### Encryption Model

```
Master Passphrase (in LastPass) + Google Authenticator (on phone)
    ↓
Derive Encryption Key (Argon2 + PBKDF2)
    ↓
Fernet AES-128 CBC
    ↓
Encrypt summaries + raw chats
    ↓
Commit to GitHub (encrypted blobs only)
```

### Threat Mitigations

| Threat | Mitigation |
|--------|-----------|
| GitHub account compromised | Encrypted blobs; key requires passphrase + TOTP |
| Laptop stolen | Key in .env requires passphrase to unlock |
| Network sniffer | HTTPS + encrypted payloads |
| Lost phone with TOTP | Backup codes in LastPass |
| One device compromised | Others unaffected; can revoke from GitHub |

### Best Practices

- ✅ Store master passphrase in LastPass (not in .env)
- ✅ Never commit .env file
- ✅ Use HTTPS in production
- ✅ Rotate encryption key yearly (optional, complex)
- ✅ Keep GitHub token in separate .env (read-only for syncing)

---

## Performance Targets

| Operation | Target | Actual |
|-----------|--------|--------|
| 5-min sync check | < 5ms | ~1ms (SQLite local query) |
| Semantic search | < 1s | ~500ms (ChromaDB cosine) |
| Keyword search | < 100ms | ~50ms (SQLite LIKE) |
| API response | < 500ms | ~200ms (search + fetch) |
| Daily sync (5 chats) | < 1 second network | ~500ms (compress + encrypt + push) |

---

## Testing

```bash
# Unit tests
python3 -m pytest tests/test_collector.py -v
python3 -m pytest tests/test_storage.py -v
python3 -m pytest tests/test_crypto.py -v

# Integration tests
python3 -m pytest tests/test_sync.py -v

# All tests
python3 -m pytest tests/ -v --cov=src
```

---

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for the current, complete
troubleshooting guide — this used to be a shorter duplicate (4 Q&As,
a strict subset) that drifted stale (referenced `python3 src/sync.py
--push` directly instead of the `cli.py sync` wrapper).

---

## Where the rest of the history lives

Detailed session-by-session change history has moved to
[CHANGELOG.md](CHANGELOG.md) — everything that's actually been built and
fixed, in the order it happened. Small deferred decisions and known
low-severity gaps live in [BACKLOG.md](BACKLOG.md). Unshipped future
features live in [ROADMAP.md](ROADMAP.md).

---

## Contact & Support

- **GitHub**: https://github.com/nobody174/claude-search-library
- **Issues**: GitHub Issues (report bugs)
- **Patreon**: https://patreon.com/c/Nobody174

---

**Last Updated**: August 5, 2026
**Author**: nobody174
**License**: MIT
