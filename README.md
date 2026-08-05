# Claude Search Library

**Distributed, offline-first personal knowledge management system**

Collect Claude chats from all your devices. Summarize with AI. Search semantically. Sync encrypted to GitHub. Works offline.

![Status Badge](https://img.shields.io/badge/status-production-green)
![Tests](https://img.shields.io/badge/tests-323%20passing-brightgreen)
![License](https://img.shields.io/badge/license-MIT-blue)

## What Is This?

You use Claude across multiple machines (desktop, laptop, phone, tablet). Your chats scatter across devices and disappear when a machine dies or gets wiped.

**Claude Search Library solves this:**

- 📦 **Collect** — Gather chats from Claude.ai, Claude Code, Claude desktop app, Cowork, local folders
- 🧠 **Summarize** — Claude API extracts learnings, patterns, reusable workflows
- 🔍 **Search** — Semantic (finds by meaning) + keyword (FTS5, finds by exact words) hybrid search
- 🌍 **Sync** — Multi-device sync via encrypted GitHub private repo
- 🔒 **Encrypt** — Master passphrase + Google Authenticator 2FA
- 📱 **Access** — Search from desktop, laptop, phone (React web UI)
- 🔌 **Offline** — Works completely offline, syncs when internet returns
- 🩺 **Self-healing** — Web UI surfaces archive health directly and can repair/reprocess failed or pending sessions with one click, no CLI needed
- ✅ **Test** — 323 Python + 10 Node tests, production-ready

## Quick Start

### Requirements
- Python 3.11+
- Git
- GitHub account (private repo for your own data)
- Google Authenticator (phone)
- LastPass or similar (for master passphrase backup)
- `vendor/cr-sqlite/crsqlite.dll` (Windows x86_64, already committed in this repo) — real CRDT multi-device merge. Missing/wrong-platform binary degrades gracefully to a plain-SQLite Last-Write-Wins fallback (see CLAUDE.md's Known Blockers); get other-platform builds from [cr-sqlite's releases](https://github.com/vlcn-io/cr-sqlite/releases).

### Installation (First Device)

```bash
git clone https://github.com/nobody174/claude-search-library.git
cd claude-search-library

# Setup Python environment
python3 -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate          # Windows (cmd/PowerShell)

# Install dependencies
pip install -r requirements.txt

# Initialize database + ChromaDB
python3 -m src.storage --init

# Setup 2FA encryption (one-time)
python3 -m src.crypto --setup
# Follow prompts: scan QR → enter passphrase → verify TOTP code

# Collect existing chats
python3 cli.py collect

# Process summaries with Claude API
python3 cli.py process --batch-size 10

# Verify the archive is healthy before syncing
python3 cli.py verify

# Start sync daemon (runs every 5 min)
python3 src/sync.py --daemon &

# Start search API
python3 server.py --port 7654 &

# Test search
python3 cli.py search "your query here"
```

### Installation (Additional Device, join existing setup)

```bash
git clone https://github.com/nobody174/claude-search-library.git
cd claude-search-library

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt

# Join existing setup (sync encryption key)
python3 -m src.crypto --join-device
# Follow prompts: enter passphrase → scan TOTP QR → verify code

# Pull all data from desktop
python3 src/sync.py --pull

# Start daemons
python3 src/sync.py --daemon &
python3 server.py --port 7654 &
```

### Access from Mobile

```
1. Browser: https://<host-device-ip>:7654
2. Enter master passphrase
3. Enter Google Authenticator code
4. Start searching!
```

## Search Modes

| Mode | How it works | When to use |
|------|--------------|-------------|
| `semantic` | ChromaDB cosine similarity — finds results by meaning | Fuzzy, conceptual queries |
| `keyword` | SQLite FTS5 with BM25 ranking — finds exact/partial word matches | Fast, precise lookups |
| `hybrid` (default) | Semantic first; falls back to keyword when semantic is slow or sparse | General use — best of both |

```bash
python3 cli.py search "async patterns"                    # hybrid (default)
python3 cli.py search "async patterns" --mode semantic
python3 cli.py search "async patterns" --mode keyword --top-k 20
```

## Common Commands

```bash
# Collect new chats from all sources
python3 cli.py collect
python3 cli.py collect --watch      # run continuously
python3 cli.py collect --dry-run    # preview without importing

# Summarize with Claude API
python3 cli.py process --batch-size 10

# Search
python3 cli.py search "minecraft mod debugging"
python3 cli.py search "python" --mode keyword --filters '{"source":"vscode"}'

# Check archive integrity (run before syncing)
python3 cli.py verify
python3 cli.py verify --verbose
python3 cli.py verify --json

# Sync to/from GitHub
python3 cli.py sync              # bidirectional
python3 cli.py sync --pull
python3 cli.py sync --push
python3 cli.py sync --watch      # daemon mode

# REST API
python3 server.py --port 7654
curl "http://localhost:7654/search?q=minecraft&mode=hybrid" | jq
curl http://localhost:7654/stats | jq
curl http://localhost:7654/health | jq

# Self-serve repair: list sessions stuck in needs_review or new, then
# reprocess one or all of them (same code path as `cli.py process`)
curl http://localhost:7654/review | jq
curl -X POST http://localhost:7654/review/reprocess -d '{}' | jq

# Sessions related by shared tags, and API spend for a specific month/quarter
curl http://localhost:7654/session/SESSION_ID/related | jq
curl "http://localhost:7654/costs?month=2026-08" | jq
curl "http://localhost:7654/costs?quarter=2026-Q3" | jq
```

## Architecture

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
Auto-merge (real cr-sqlite CRDT — per-column, not whole-row)
    ↓
Rebuild ChromaDB
    ↓
Search locally (semantic + keyword hybrid)
```

## Why This Approach?

| Decision | Benefit |
|----------|---------|
| **Distributed sync via GitHub** | No central server; any device can go fully offline and catch up later |
| **Hybrid search (ChromaDB + FTS5)** | Semantic recall for fuzzy queries, fast BM25 keyword matching as backstop |
| **Master passphrase + TOTP** | Two independent factors; brute-force resistant |
| **Local ChromaDB** | Semantic search works offline; no API calls at query time |
| **Encrypt everything on GitHub** | GitHub only ever sees encrypted blobs |
| **Content-hash deduplication** | Re-collecting the same chat twice is a no-op |
| **JSONL durability mirror** | Summaries survive SQLite corruption; rebuild from a flat backup |
| **React web UI (CDN, no build step)** | Works on iPhone Safari; nothing to compile or deploy |

## Key Questions Answered

**Q: Is this secure?**
A: Master passphrase + TOTP 2FA, combined via Argon2id key derivation. GitHub only sees encrypted blobs. The encryption key is never uploaded or transmitted — see [Security](#security).

**Q: Does it work offline?**
A: Yes. Everything runs locally. Syncing to GitHub is the only thing that needs a connection, and it batches automatically when one is available.

**Q: How much storage does this use on GitHub?**
A: Small — encrypted summaries and (optionally) encrypted raw chats. Actual size depends on your chat volume.

**Q: Can I have unlimited devices?**
A: Yes. Each device is autonomous; GitHub is just the transport layer.

**Q: What if my GitHub account is compromised?**
A: An attacker sees only encrypted blobs. Decrypting requires both your master passphrase and your TOTP secret.

**Q: What if I lose my phone with the Authenticator app?**
A: Use one of the 10 generated backup codes (store them in your password manager, not in this repo).

**Q: What if my local database gets corrupted?**
A: Run `python3 cli.py verify` to detect it, then `python3 -m src.storage --restore-from-jsonl` to rebuild the summaries table from the JSONL durability mirror.

## Security

- **Two-factor key derivation**: `derive_encryption_key(passphrase, totp_secret)` combines both factors via Argon2id before producing a Fernet key — see `src/crypto.py`.
- **The master passphrase is never stored** anywhere, on any device or on GitHub.
- **Redaction before indexing**: API keys, GitHub/Discord tokens, AWS keys, emails, and IP addresses are auto-redacted from summaries; sessions with more than 3 redactions are flagged for manual review instead of being indexed automatically.
- **Every API route requires a real server-side session**, not just a client-side flag: `/setup` verifies your passphrase + TOTP and issues a short-lived (30 min), HttpOnly session cookie — everything except the index page, static assets, and `/setup` itself requires it. `/setup` is rate-limited (5 attempts, then a 15-minute per-IP lockout). `Lock` in the UI actually invalidates the session server-side, not just local storage.
- **HTTPS by default, via a self-signed cert**: `server.py` generates/uses a cert at `~/.claude-search-library/certs/` so the session cookie doesn't cross your LAN in cleartext (`--no-tls` opts back into plain HTTP for pure-localhost dev). Because it's self-signed, not issued by a public Certificate Authority, your browser will show a "Not secure" / "connection isn't private" warning the first time each device connects — this is expected, not a sign anything's broken, and is the same tradeoff every self-hosted LAN tool with HTTPS makes (router admin pages, home NAS UIs, etc.) without a public domain to get a CA-signed cert from. Two ways to deal with it:
  - **Click through it** (Advanced → Proceed) — the connection is still genuinely encrypted, just not vouched for by a public CA. You'll need to do this once per browser/device.
  - **Trust the cert permanently** on a device you control, so the warning stops appearing entirely: import `~/.claude-search-library/certs/server.crt` into that OS's trusted root certificate store (on Windows: `certutil -user -addstore Root path\to\server.crt`, then fully restart your browser). This only works for your own devices — there's no way to make a self-signed cert "trusted" for an arbitrary stranger's browser; that requires a real public domain and a CA like Let's Encrypt, a fundamentally different deployment model than a self-hosted LAN tool.
- **CORS is restricted** to `localhost`/`127.0.0.1` by default in `server.py` — do not expose the API port directly to the public internet without adding your own auth/reverse-proxy layer.

If you find a security issue, please open a private security advisory on GitHub rather than a public issue.

## Project Structure

```
claude-search-library/
├── src/
│   ├── collector.py     # Gather chats from Claude.ai, VS Code, Cowork, local
│   ├── processor.py     # Summarize via Claude API
│   ├── redactor.py      # Secret detection & redaction
│   ├── storage.py       # SQLite schema, CRUD, dedup, JSONL mirror, verify_archive
│   ├── embedder.py      # ChromaDB semantic embeddings
│   ├── crypto.py        # Passphrase + TOTP key derivation, encrypt/decrypt
│   ├── sync.py          # GitHub push/pull + merge
│   ├── search.py        # Semantic / keyword (FTS5) / hybrid search
│   ├── config.py        # config.yaml loading + env var overrides
│   └── api.js           # Client-side API wrapper for the web UI
├── public/
│   └── index.html       # React SPA (search, filters, session detail, sync status)
├── cli.py                # claude-search CLI (collect, process, search, verify, sync)
├── server.py             # Flask REST API
├── config_template.yaml  # Copy to config.yaml and fill in
├── requirements.txt
└── tests/                 # 323 Python tests (pytest) + 10 Node tests (api.js)
```

## Documentation

- **[DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)** — Step-by-step setup for desktop, additional devices, and the web UI
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** — Fixes for common setup, sync, and search issues
- **[SPEC.md](SPEC.md)** — Full technical specification: schema, encryption model, sync protocol
- **[CLAUDE.md](CLAUDE.md)** — Architecture decisions, known limitations, troubleshooting notes
- **[ROADMAP.md](ROADMAP.md)** — Real future features, not yet started
- **[BACKLOG.md](BACKLOG.md)** — Small deferred decisions and known low-severity gaps
- **[CHANGELOG.md](CHANGELOG.md)** — Everything already built and fixed, in order
- **[tasks/](tasks/)** — The original build-task breakdown this project was implemented from

## Contributing

Issues and pull requests are welcome. This started as a personal tool, so expect some rough edges — see `CLAUDE.md` for known limitations (e.g. cr-sqlite CRDT support is best-effort and falls back to a simpler merge policy where the native extension isn't available).

## License

MIT — see [LICENSE](LICENSE).

## Author

Built by Vartdal ([@nobody174](https://github.com/nobody174)).

Built with Claude Code. Tested on production. Ready for public launch.
