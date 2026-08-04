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

| Issue | Impact | Status | Solution |
|-------|--------|--------|----------|
| cr-sqlite Python bindings | Database sync | TBD | Use official package when available |
| GitHub API rate limits | Sync frequency | Low | 5-min interval ≈ 288 calls/day (well under limit) |
| Mobile TOTP sync | iPhone setup | TBD | Consider alternative (SMS code?) if TOTP distribution complex |
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
**Why**: Laptop can work offline at cabin; desktop shutdown doesn't break syncing
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
Scans 4 data sources:
1. Claude.ai (manual JSON exports)
2. VS Code Claude extension (~/.vscode/extensions/...)
3. Cowork (local cache or API)
4. Local folder (watch for new JSON)

**Output**: Normalized chat objects matching schema

### src/processor.py
Calls Claude API to summarize each chat:
- Extracts TL;DR, learnings, patterns, tags
- Batched processing (respects rate limits)
- Saves summaries as sidecar JSON files

**Output**: Summary JSON alongside originals

### src/redactor.py
Masks sensitive data:
- API keys, GitHub tokens, emails, IPs
- Flags sessions for manual review if > 3 redactions
- Audit trail in SQLite

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
├── SPEC.md                # Full specification
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

### iPhone (Web UI)

```
1. Safari: https://your-laptop-ip:7654
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

See `SPEC.md` → "Troubleshooting" for more issues.

---

## Session log (2026-08-02)

- **ROADMAP.md #6/#7 shipped:** join-device GUI popup fix (the passphrase
  step never actually used the popup at all — fixed), `/sync` + `/import`
  REST endpoints, full web UI sync dashboard (health badge, Pull/Push/Sync
  Now buttons, drag-and-drop Claude.ai export import). Passphrase is now
  remembered per browser tab via sessionStorage after a successful sync —
  a fresh TOTP code is still required every time. Commits `6a870fc`,
  `062d44d`, `59e1333` on `origin/main`.
- **Real bugs found and fixed along the way, not just planned features:**
  a `test_sync.py` test was silently wiping the real production ChromaDB
  with fixture data on every test run (fixed with an isolation fixture
  mirroring `test_embedder.py`'s); `index.html` and `src/api.js` both
  declared a top-level `const api`, which collide the instant the page is
  actually served by a browser — this went undetected until this session
  added the `GET /` route that finally served the page at all; `/sync`'s
  response shape was wrong for every direction (`files_changed` came back
  `undefined`) because it called the wrapped `worker.sync()` instead of
  mirroring `cli.py`'s flat per-direction calls.
- **Cost decision:** `src/processor.py`'s summarization model switched
  from `claude-opus-5` to `claude-haiku-4-5`. Push/pull/search involve
  zero model calls ever (pure git/crypto/local-embedding) — summarizing
  *new* sessions via `process` is the only real API cost anywhere in this
  pipeline. Worst case (a 16K-token session) is ~$0.026, roughly a
  quarter of a Norwegian krone.
- **ROADMAP #8 (iOS chat capture) is explicitly UNSOLVED** — re-read that
  roadmap entry before attempting a fix. Official export is desktop/web
  only; unofficial claude.ai scrapers exist but violate Anthropic's ToS
  (real account-suspension risk, confirmed via dedicated research, not
  assumed); no iOS Share Sheet export hook exists either.
- **Next up, per the user:** continuing through ROADMAP.md, in
  system-completeness order — UI/visual polish is explicitly deferred
  until the underlying system itself is fully working.

## Session log (2026-08-03 to 2026-08-04)

**All 5 original ROADMAP.md items shipped this stretch (#1-#5), plus #9
(new, solved) and web UI polish. The system is now fully working
end-to-end with real personal data, not just tests.**

- **#1-#5 shipped**: PowerShell orchestration, cost reporting
  (`cli.py costs`), Markdown export, Web Chat Import (rewritten - the
  original plan was the same ToS-risky scraping approach #8 already
  ruled out; built `src/claude_export_import.py` for the official
  Settings → Export Data flow instead), retention/pruning
  (`cli.py prune`).
- **New collectors beyond the original roadmap, all built from real
  local app data, never claude.ai's private API:**
  - `collect_from_claude_code()` — Claude Code's own
    `~/.claude/projects/*.jsonl` transcripts.
  - `collect_from_claude_desktop()` — the desktop app's local IndexedDB
    cache. Required real reverse-engineering (Chromium's Snappy
    compression wasn't being decompressed before V8 deserialization -
    see ROADMAP.md #9 for the full investigation). Only captures
    conversations actually opened in the desktop app recently, not full
    history.
  - `collect_from_cowork()` — Cowork sessions, discovered by the user
    noticing a different icon next to 3 conversations. Much simpler than
    the desktop-app one (plain JSONL, same format as Claude Code) once
    found, but confirmed Cowork sessions are **entirely absent** from
    the official export - this collector is the *only* way to recover
    them.
  - Real bug fixed along the way: Cowork's nested folder paths exceed
    Windows' 260-char MAX_PATH, silently breaking plain pathlib
    glob/iterdir. Fixed with a `\\?\` long-path prefix helper.
- **`cli.py sync` now auto-collects from every local source first** by
  default (`--no-collect` to opt out) - closes the "forgot to collect
  before syncing" gap, especially for the desktop-app/Cowork collectors
  whose data only exists locally until pushed.
- **Two serious, currently-active sync bugs found and fixed via real
  usage, not unit tests:**
  1. Pull was bumping the same device-level checkpoint push used to
     decide what's new, so a pull-then-push (the normal flow) silently
     pushed nothing.
  2. Push compared each session's own *content* timestamp against that
     device checkpoint, so any newly-imported historical session (an
     old conversation imported today) looked "already synced" and was
     silently dropped forever. This one was serious - it affected most
     of a 41-conversation real historical import. Fixed by switching to
     proper per-session `synced_at` tracking (the column already
     existed in the schema, unused until now).
- **Login friction fixed**: `join_device_existing_setup()` used to
  re-derive the encryption key (full passphrase+TOTP popup) on every
  single CLI call. Added a 30-minute local session cache
  (`SESSION_CACHE_PATH`) - explicit personal-machine tradeoff, not a
  general security default.
- **Web UI polish**: full dark "command-center" reskin (near-black bg,
  amber accent, JetBrains Mono for data) plus 4 real functional fixes
  found by reading the code, not just cosmetics - search filters were
  completely non-functional end-to-end (built but never wired through
  api.js/server.py), the drag-and-drop importer bypassed the real export
  converter entirely, health check errors were invisible, cost/pruning
  had no UI surface. Also fixed a separate real bug: the page went
  totally blank because `@babel/standalone`'s unpinned CDN URL silently
  upgraded to an incompatible major version (8) - pinned to `@7`.
- **Real data now in the library and fully synced**: 59 sessions across
  claude-ai (45, from a real full account export), claude-code (11),
  and cowork (3) - all pushed to `github.com/nobody174/claude-search-data`
  and verified present there directly via `gh api`, not just trusted.
- **Real, confirmed limitation worth remembering**: the automatic
  collectors (claude-code, claude-desktop, cowork) only ever see this
  machine's own local app data - never conversations from a browser tab
  or mobile. The manual export (#4) is not fully retired, just
  downgraded to an occasional safety-net for those.
- **Not yet fixed** (documented in ROADMAP.md #9, real but lower
  priority): when the same conversation UUID is collected by two
  different sources with different content, `store_session_with_hash()`
  crashes with a raw `sqlite3.IntegrityError` instead of updating in
  place. Worked around by hand once; needs a proper fix.

---

## Contact & Support

- **GitHub**: https://github.com/nobody174/claude-search-library
- **Issues**: GitHub Issues (report bugs)
- **Patreon**: https://patreon.com/c/Nobody174

---

**Last Updated**: August 4, 2026
**Author**: Vartdal (nobody174)
**License**: MIT
