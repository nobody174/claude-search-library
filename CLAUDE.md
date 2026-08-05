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
- cr-sqlite integration (CRDT support)
- Schema initialization

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
- Push encrypted blobs to GitHub
- Pull & merge via cr-sqlite CRDT
- Rebuild ChromaDB on sync

**Output**: Synchronized database across devices

### src/search.py + cli.py + server.py
Search interface:
- Semantic search (ChromaDB)
- Keyword search (SQLite LIKE)
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

## File Structure (After Build)

```
~/projects/claude-search-library/
├── src/
│   ├── __init__.py
│   ├── collector.py       # Task 1
│   ├── processor.py       # Task 2
│   ├── redactor.py        # Task 3
│   ├── storage.py         # Task 4
│   ├── embedder.py        # Task 5
│   ├── crypto.py          # Task 6
│   ├── sync.py            # Task 7
│   ├── search.py          # Task 8
│   ├── config.py          # Task 9
│   └── utils.py
├── public/
│   └── index.html         # Task 10
├── cli.py                 # Task 8
├── server.py              # Task 8
├── api.js                 # Task 10
├── config_template.yaml   # Task 9
├── requirements.txt
├── CLAUDE.md              # This file
├── ROADMAP.md             # Unshipped future features
├── BACKLOG.md             # Small deferred decisions
├── CHANGELOG.md           # Everything already built/fixed
├── .gitignore
└── venv/                  # Virtual environment
```

---

## Setup Instructions

### Desktop (First Time)

```bash
# 1. Clone repo
git clone https://github.com/nobody174/claude-search-library.git
cd claude-search-library

# 2. Virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Initialize (creates DB, directories)
python3 -m src.storage --init

# 5. Setup 2FA encryption
python3 -m src.crypto --setup
# Follow prompts: scan QR → enter passphrase → verify TOTP

# 6. Collect existing chats
python3 cli.py collect

# 7. Process summaries
python3 cli.py process --batch-size 10

# 8. Start sync daemon (background)
python3 src/sync.py --daemon --interval 300 &

# 9. Start search API
python3 server.py --port 7654 &

# 10. Test search
python3 cli.py search "test query"
```

### Laptop (Join Existing Setup)

```bash
# 1-3. Same as above

# 4. Join device (sync encryption key)
python3 -m src.crypto --join-device
# Follow prompts: enter passphrase → scan TOTP QR → verify code

# 5. Initial sync (pull all Desktop data)
python3 src/sync.py --pull

# 6-10. Same as Desktop
```

### Mobile (Web UI)

```
1. Browser: https://<host-device-ip>:7654
2. Setup Device:
   - Enter master passphrase
   - Scan TOTP QR into Google Authenticator
   - Verify code
3. Start searching!
```

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

```bash
# Collect new chats
python3 cli.py collect

# Process summaries (with progress)
python3 cli.py process --batch-size 10

# Search
python3 cli.py search "minecraft"

# Start daemon (5-min sync)
python3 src/sync.py --daemon &

# Start API server
python3 server.py --port 7654 &

# View stats
curl http://localhost:7654/stats | jq

# Manual sync
python3 src/sync.py --pull
python3 src/sync.py --push

# Run tests
python3 -m pytest tests/ -v
```

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

**Q: "Encryption key mismatch" between devices**
A: Check master passphrase in LastPass; retry `python3 -m src.crypto --join-device`

**Q: "TOTP code keeps failing"**
A: Sync system time: `sudo sntp -s time.apple.com`; try ±1 time step

**Q: "Sync shows no changes"**
A: Normal — if no new chats, sync silently exits (saves data)

**Q: "Phone can't see Desktop data"**
A: Force push: `python3 src/sync.py --push` on Desktop; refresh phone

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for more issues.

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
**Author**: Vartdal (nobody174)
**License**: MIT
