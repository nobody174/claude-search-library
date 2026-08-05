# Claude Search Library — Claude Code Build Plan

**Overview**: This package contains 10 sequential build tasks for Claude Code (VS Code extension).

Each task is independent but builds on previous ones. Follow the order below.

---

## How to Use This Package

### Step 1: Extract & Setup

```bash
# Extract zip into your project folder
unzip claude-search-library-build.zip -d ~/projects/claude-search-library/

# Navigate to project
cd ~/projects/claude-search-library/

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install base dependencies
pip install -r requirements.txt
```

### Step 2: Open in Claude Code

```bash
# Open VS Code with Claude Code extension
code .
```

### Step 3: Build Each Task Sequentially

For each task (1-10):

1. **Open** the `TASK_N_*.md` file (in this same `tasks/` folder)
2. **Copy the entire prompt** (everything inside the file)
3. **Paste into Claude Code chat** (Claude extension panel in VS Code)
4. **Wait for code generation**
5. **Claude will tell you the file path** — usually `src/module_name.py` or equivalent
6. **Create the file** in the right location (follow the path it suggests)
7. **Move to next task**

---

## Task Order (Build Sequentially)

| # | Task | File | Output |
|---|------|------|--------|
| 1 | Setup & Data Collection | `TASK_1_SETUP_AND_COLLECTION.md` | `src/collector.py` |
| 2 | Processing & Summarization | `TASK_2_PROCESSING_SUMMARIZATION.md` | `src/processor.py` |
| 3 | Redaction & Privacy | `TASK_3_REDACTION_PRIVACY.md` | `src/redactor.py` |
| 4 | Storage (SQLite + cr-sqlite) | `TASK_4_STORAGE_SQLITE.md` | `src/storage.py` |
| 5 | Vector Embeddings (ChromaDB) | `TASK_5_EMBEDDINGS_CHROMADB.md` | `src/embedder.py` |
| 6 | Encryption & 2FA | `TASK_6_ENCRYPTION_2FA.md` | `src/crypto.py` |
| 7 | Distributed Sync | `TASK_7_DISTRIBUTED_SYNC.md` | `src/sync.py` |
| 8 | Search Interface | `TASK_8_SEARCH_INTERFACE.md` | `src/search.py`, `cli.py`, `server.py` |
| 9 | Configuration & Initialization | `TASK_9_CONFIG_INITIALIZATION.md` | `config_template.yaml`, `src/config.py` |
| 10 | Web UI (Multi-Device) | `TASK_10_WEB_UI.md` | `src/api.js`, `public/index.html` |

---

## Project Structure (After Build)

```
~/projects/claude-search-library/
├── src/
│   ├── __init__.py
│   ├── collector.py           # Task 1
│   ├── processor.py           # Task 2
│   ├── redactor.py            # Task 3
│   ├── storage.py             # Task 4
│   ├── embedder.py            # Task 5
│   ├── crypto.py              # Task 6
│   ├── sync.py                # Task 7
│   ├── search.py              # Task 8
│   ├── config.py              # Task 9
│   └── utils.py               # (utilities, helpers)
├── cli.py                     # Task 8 (CLI interface)
├── server.py                  # Task 8 (Flask REST API)
├── public/
│   └── index.html             # Task 10 (React web UI)
├── src/
│   └── api.js                 # Task 10 (Web UI API client)
├── config_template.yaml       # Task 9
├── requirements.txt           # Python dependencies
├── CLAUDE.md                  # Project documentation
├── .gitignore
└── venv/                      # Virtual environment
```

---

## Tips for Claude Code

### Tip 1: File Paths
When Claude generates code, it often says:
> "Save this as `src/collector.py`"

Create the file at that exact path in your project.

### Tip 2: Imports
If Claude references a module from a previous task (e.g., `from src.storage import ...`), that's expected — the previous tasks are already built.

### Tip 3: Error Handling
Claude will include error handling, logging, and comments. That's good. Keep it as-is.

### Tip 4: Tests
Some tasks include tests. Save them to `tests/test_module_name.py` (create the `tests/` folder).

### Tip 5: Dependencies
If Claude mentions new imports (like `import pyotp` for TOTP), add them to `requirements.txt`:
```bash
# After all tasks are built:
pip install -r requirements.txt
```

---

## Build Checklist

- [ ] **Task 1**: `src/collector.py` — Data collection working
- [ ] **Task 2**: `src/processor.py` — Summarization working
- [ ] **Task 3**: `src/redactor.py` — Redaction working
- [ ] **Task 4**: `src/storage.py` — SQLite + cr-sqlite working
- [ ] **Task 5**: `src/embedder.py` — ChromaDB working
- [ ] **Task 6**: `src/crypto.py` — 2FA encryption working
- [ ] **Task 7**: `src/sync.py` — GitHub sync working
- [ ] **Task 8**: `cli.py`, `server.py`, `src/search.py` — Search working
- [ ] **Task 9**: `config_template.yaml`, `src/config.py` — Config working
- [ ] **Task 10**: `public/index.html`, `src/api.js` — Web UI working

---

## Running Tests (After Build)

```bash
# After all tasks are built:
cd ~/projects/claude-search-library/

# Run unit tests
python3 -m pytest tests/ -v

# Or test individual modules
python3 -m pytest tests/test_storage.py -v
```

---

## First Run (After All Tasks Built)

See `SPEC.md` → "Deployment Checklist" → "Desktop Setup"

```bash
# 1. Setup 2FA encryption
python3 -m src.crypto --setup

# 2. Collect existing chats
python3 cli.py collect

# 3. Process summaries
python3 cli.py process --batch-size 10

# 4. Start sync daemon
python3 src/sync.py --daemon &

# 5. Start search API
python3 server.py --port 7654 &

# 6. Test search
python3 cli.py search "test query"
```

---

## Questions During Build?

If Claude gets stuck:
1. Check the **SPEC.md** for context
2. Look at the **Requirements** section of the task prompt
3. Ask Claude to explain the error
4. Reference the specification section

---

**Ready? Start with Task 1!** 🚀
