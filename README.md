# Claude Search Library — Build Package

**Complete specification and build tasks for a distributed, offline-first personal knowledge management system.**

This package contains everything you need to build the Claude Search Library with Claude Code.

---

## What's Inside

```
claude-search-library-build/
├── SPEC.md                           # Complete specification (80 pages)
├── CLAUDE_CODE_BUILD_PLAN.md         # How to use this with Claude Code
├── requirements.txt                  # Python dependencies
├── .gitignore                        # Git ignore rules
├── CLAUDE.md                         # Project documentation template
├── tasks/                            # 10 individual build tasks
│   ├── TASK_1_SETUP_AND_COLLECTION.md
│   ├── TASK_2_PROCESSING_SUMMARIZATION.md
│   ├── TASK_3_REDACTION_PRIVACY.md
│   ├── TASK_4_STORAGE_SQLITE.md
│   ├── TASK_5_EMBEDDINGS_CHROMADB.md
│   ├── TASK_6_ENCRYPTION_2FA.md
│   ├── TASK_7_DISTRIBUTED_SYNC.md
│   ├── TASK_8_SEARCH_INTERFACE.md
│   ├── TASK_9_CONFIG_INITIALIZATION.md
│   └── TASK_10_WEB_UI.md
└── README.md                         # This file
```

---

## Quick Start

### 1. Extract

```bash
unzip claude-search-library-build.zip -d ~/projects/claude-search-library/
cd ~/projects/claude-search-library/
```

### 2. Read the Spec

Open `SPEC.md` to understand the system architecture and features.

### 3. Follow the Build Plan

Open `CLAUDE_CODE_BUILD_PLAN.md` and follow the step-by-step instructions.

### 4. Build Each Task

For each task (1-10):
1. Open `tasks/TASK_N_*.md`
2. Copy the entire prompt
3. Paste into Claude Code
4. Save the generated files
5. Move to next task

---

## Files to Know

| File | Purpose |
|------|---------|
| `SPEC.md` | 80-page complete specification (architecture, schema, encryption, deployment) |
| `CLAUDE_CODE_BUILD_PLAN.md` | Step-by-step guide for building with Claude Code |
| `CLAUDE.md` | Project documentation + known blockers + troubleshooting |
| `requirements.txt` | Python dependencies (install with `pip install -r requirements.txt`) |
| `.gitignore` | Don't commit .env, .claude-search-library/, __pycache__, etc. |
| `tasks/*.md` | Individual task prompts (copy into Claude Code) |

---

## System Overview

**Claude Search Library** is a distributed personal knowledge management system that:

✅ **Collects** chats from Claude.ai, VS Code, Cowork, local folders  
✅ **Summarizes** each chat with Claude API (TL;DR, learnings, patterns)  
✅ **Encrypts** everything with master passphrase + Google Authenticator 2FA  
✅ **Syncs** to private GitHub repo (5-minute intervals)  
✅ **Auto-merges** conflicts via cr-sqlite CRDT  
✅ **Searches** semantically with local ChromaDB  
✅ **Works offline** — syncs when internet available  
✅ **Multi-device** — desktop, laptops, phones, tablets all stay in sync  

---

## Why This Approach?

| Decision | Benefit |
|----------|---------|
| **Distributed sync via GitHub** | No central server; desktop can go offline at cabin |
| **cr-sqlite CRDT** | Automatic conflict resolution; no manual merging |
| **Master passphrase + TOTP** | 148-bit entropy; brute-force resistant |
| **Local ChromaDB** | Semantic search works offline; no API calls |
| **Encrypt everything on GitHub** | GitHub can't read your data; zero-knowledge |
| **Daily batch processing** | Respects Claude API rate limits |
| **React web UI** | Works on iPhone Safari; easier than native app |

---

## Build Timeline

**Total time**: ~2-4 hours (depends on Claude Code speed and code review)

- Task 1: 15 min (data collection)
- Task 2: 20 min (processing + API)
- Task 3: 15 min (redaction)
- Task 4: 20 min (SQLite schema)
- Task 5: 15 min (ChromaDB)
- Task 6: 25 min (encryption + 2FA)
- Task 7: 30 min (distributed sync)
- Task 8: 40 min (search + CLI + API)
- Task 9: 20 min (configuration)
- Task 10: 40 min (web UI)

**Then**: 30 min testing + setup

---

## After Build: First Run

### Desktop Setup

```bash
cd ~/projects/claude-search-library/

# 1. Initialize database
python3 -m src.storage --init

# 2. Setup 2FA encryption
python3 -m src.crypto --setup
# Scan QR into Google Authenticator
# Enter master passphrase
# Verify TOTP code

# 3. Collect existing chats
python3 cli.py collect

# 4. Process summaries
python3 cli.py process --batch-size 10

# 5. Start sync daemon (background)
python3 src/sync.py --daemon &

# 6. Start search API
python3 server.py --port 7654 &

# 7. Test search
python3 cli.py search "minecraft"
```

### Laptop Setup (Later)

```bash
# Join existing setup
python3 -m src.crypto --join-device
# Enter master passphrase (from LastPass)
# Scan TOTP QR (synced)
# Verify TOTP code

# Pull all Desktop data
python3 src/sync.py --pull

# Start daemon
python3 src/sync.py --daemon &
```

### iPhone Setup (Later)

```
1. Safari: https://your-laptop-ip:7654
2. Enter master passphrase + TOTP code
3. Start searching!
```

---

## Key Questions Answered

**Q: Is this secure?**  
A: Yes. Master passphrase + TOTP 2FA. GitHub only sees encrypted blobs. Encryption key never uploaded.

**Q: Does it work offline?**  
A: Yes. Everything works offline. Syncs when internet available (5-min intervals).

**Q: How much storage on GitHub?**  
A: ~10 MB/year (negligible). Includes both summaries AND raw chats encrypted.

**Q: Can I have unlimited devices?**  
A: Yes. Desktop, laptops, phones, tablets — all sync via GitHub.

**Q: What if GitHub account is hacked?**  
A: Attacker sees encrypted blobs. Can't decrypt without master passphrase + TOTP phone.

**Q: What if I lose my phone with TOTP?**  
A: Backup codes stored in LastPass. Can recover.

**Q: Can I build this myself without Claude Code?**  
A: Yes, but it's 10k+ lines of code. Claude Code saves massive time.

---

## Troubleshooting Build Issues

**"Claude is asking confusing questions"**  
→ Reference the relevant section in `SPEC.md` in your prompt

**"Generated code has syntax errors"**  
→ Ask Claude to fix: "Fix the syntax error on line X" (paste error)

**"I don't understand the imports"**  
→ Check `SPEC.md` → "Tech Stack" section for library usage

**"Module can't find imports from previous tasks"**  
→ Normal. Previous tasks are already built. They're available to import.

---

## Next Steps After Build

1. ✅ Run `python3 -m src.storage --init` to create database
2. ✅ Follow "First Run" section above for Desktop setup
3. ✅ Add laptop (or phone) using "Join Device" flow
4. ✅ Try searching your chats
5. ✅ Set up cron jobs for automated collection + processing
6. ✅ Push to your GitHub repo

---

## Support

- **Full Specification**: See `SPEC.md` (80 pages, covers everything)
- **Project Docs**: See `CLAUDE.md` (troubleshooting, architecture, decisions)
- **Build Help**: See `CLAUDE_CODE_BUILD_PLAN.md` (step-by-step guide)

---

## License

MIT — You own the code. Use it, modify it, share it.

---

## Author

Built for Vartdal (nobody174) — distributed, offline-first, encrypted knowledge management.

**Ready to build?** → Start with `CLAUDE_CODE_BUILD_PLAN.md` 🚀
