# Claude Search Library — Complete Specification
**Version 2.0 | Distributed Offline-First Personal Knowledge Management**  
**Master Passphrase + Google Authenticator 2FA | GitHub Encrypted Sync | CRDT Auto-Merge**

---

## Table of Contents
1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [Security Model](#security-model)
4. [Data Collection](#data-collection)
5. [Processing Pipeline](#processing-pipeline)
6. [Storage Schema](#storage-schema)
7. [Encryption & 2FA](#encryption--2fa)
8. [Sync & CRDT Merging](#sync--crdt-merging)
9. [Search Implementation](#search-implementation)
10. [Deployment Checklist](#deployment-checklist)
11. [Claude Code Build Tasks (9)](#claude-code-build-tasks)
12. [Multi-Device Setup Guide](#multi-device-setup-guide)

---

## System Overview

### Purpose
Create a **fully distributed, offline-first personal knowledge library** that:
- Collects chat sessions from all Claude interfaces (Claude.ai, VS Code, Cowork, local)
- Summarizes each session into actionable insights (TL;DR, learnings, patterns)
- Stores summaries + raw chats **encrypted on GitHub**
- Syncs seamlessly across unlimited devices (desktop, laptops, phones, tablets)
- Provides instant semantic search via local ChromaDB
- Works completely offline; syncs when internet available
- Never requires a central server — fully distributed P2P via GitHub

### Key Features
- **Distributed**: No hub required. Each device is autonomous.
- **Offline-First**: Works without internet. Syncs automatically when reconnected.
- **Encrypted**: Master passphrase + Google Authenticator 2FA. GitHub sees only ciphertext.
- **Auto-Merging**: cr-sqlite CRDT handles conflicts automatically (no manual resolution).
- **Semantic Search**: ChromaDB embeddings find sessions by meaning, not just keywords.
- **Citation Links**: Every pattern points to source session (date, time, device).
- **Multi-Device**: Desktop, laptops, phones, tablets — all stay in sync.
- **Audit Trail**: Git history shows what changed, when, on which device.

### User (Vartdal) Context
- Primary: Desktop (Tønsberg home) + Laptop (cabin work + travel)
- Secondary: Phone, tablet (research + reference)
- Work pattern: High-velocity chat creation (1-5 per day), regular cabin trips (offline)
- Storage preference: GitHub private repo, full backup of raw chats + summaries
- Processing: Daily minimum, batched (respects Claude API rate limits)

---

## Architecture

### High-Level Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         EACH DEVICE                             │
│          (Desktop | Laptop | Phone | Tablet)                    │
└─────────────────────────────────────────────────────────────────┘

Step 1: DATA COLLECTION
  └─ Collect chats from: Claude.ai, VS Code, Cowork, local folders
  
Step 2: NORMALIZATION
  └─ Convert all formats to unified schema
  
Step 3: PROCESSING
  └─ Claude API: summarize, extract learnings, identify patterns
  
Step 4: REDACTION
  └─ Mask API keys, emails, secrets
  
Step 5: STORAGE (LOCAL)
  ├─ SQLite DB + cr-sqlite (CRDT support)
  ├─ Raw chat files (JSON, unencrypted locally)
  └─ ChromaDB (vector embeddings)
  
Step 6: ENCRYPTION & SYNC
  ├─ Encrypt summaries + raw chats with master passphrase + TOTP
  ├─ Commit to GitHub private repo
  ├─ Pull updates from other devices
  ├─ Merge via cr-sqlite CRDT (automatic, no conflicts)
  └─ Re-index ChromaDB with merged data
  
Step 7: SEARCH INTERFACE
  ├─ CLI (terminal)
  ├─ REST API (web/mobile)
  └─ Local-only (no external calls)

PRIVACY GUARANTEE:
  GitHub sees: Encrypted blobs only (ciphertext)
  Your devices see: Everything (decrypted)
  Master passphrase: Never leaves your head (or LastPass)
  TOTP secret: Encrypted, shared via GitHub
  Encryption key: Derived from (passphrase + TOTP)
```

### Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| **Local Database** | SQLite + cr-sqlite | Built-in CRDT; auto-merge conflicts |
| **Embeddings** | ChromaDB | Local semantic search; no sync needed |
| **Encryption** | Python `cryptography` (Fernet) | Symmetric E2E; proven, audited |
| **2FA** | Google Authenticator (TOTP) | Industry standard; phone-based |
| **Sync Transport** | Git + GitHub (private repo) | Version control; audit trail; free |
| **Sync Orchestration** | Python sync worker | Scheduled or on-demand |
| **Conflict Resolution** | cr-sqlite CRDT | Automatic; Last-Write-Wins on timestamp |
| **Search** | ChromaDB (cosine similarity) + SQLite LIKE | Semantic + keyword fallback |
| **API** | Flask (REST) | Lightweight; multi-device access |
| **CLI** | Python Click | Terminal interface |

### Directory Structure

```
~/.claude-search-library/
├── library.db                      # SQLite (cr-sqlite CRDT)
├── chromadb/                       # ChromaDB persistent storage
│   └── chroma.db
├── raw_chats/                      # Local raw chat files
│   ├── 2026-07-31_desktop_12345.json
│   ├── 2026-07-31_laptop_67890.json
│   └── ...
├── config.yaml                     # App configuration
├── .env                            # MASTER_PASSPHRASE (LastPass)
├── logs/
│   ├── collection.log
│   ├── processing.log
│   ├── sync.log
│   └── search.log
└── backups/                        # Manual backups (optional)

GitHub (Private Repo):
github.com/nobody174/claude-search-library
├── encrypted_summaries/
│   ├── 2026-07-31_desktop_summary_12345.enc
│   ├── 2026-07-31_laptop_summary_67890.enc
│   └── ...
├── encrypted_raw_chats/
│   ├── 2026-07-31_desktop_raw_12345.enc
│   ├── 2026-07-31_laptop_raw_67890.enc
│   └── ...
├── secrets.enc                     # Encrypted TOTP secret
├── sync_metadata.json              # Unencrypted sync state
├── .gitignore
│   └── .env                        # Never commit!
└── README.md                       # Setup instructions

Python Package:
~/projects/claude-search-library/
├── src/
│   ├── __init__.py
│   ├── collector.py                # Data collection
│   ├── processor.py                # Claude API summarization
│   ├── redactor.py                 # Secret redaction
│   ├── storage.py                  # SQLite + cr-sqlite operations
│   ├── embedder.py                 # ChromaDB vector storage
│   ├── search.py                   # Search logic
│   ├── sync.py                     # GitHub sync + CRDT merge
│   ├── crypto.py                   # Encryption + TOTP + 2FA
│   ├── utils.py                    # Helpers + logging
│   └── api.py                      # REST API endpoints
├── cli.py                          # Command-line interface
├── server.py                       # Flask app
├── requirements.txt
├── config_template.yaml
└── tests/
    ├── test_collector.py
    ├── test_processor.py
    ├── test_redactor.py
    ├── test_storage.py
    ├── test_crypto.py
    └── test_sync.py
```

---

## Security Model

### Threat Model & Mitigations

| Threat | Mitigation |
|--------|-----------|
| **GitHub account compromised** | Attacker sees encrypted blobs only; can't decrypt without master passphrase + TOTP device |
| **Laptop stolen** | Attacker has encrypted SQLite but no key (key in .env requires passphrase to unlock) |
| **Network sniffer** | All traffic is encrypted (HTTPS to GitHub + encrypted payloads) |
| **Forgotten master passphrase** | Store in LastPass (recovery option) |
| **Lost phone with TOTP** | Backup codes stored in LastPass |
| **One device compromised** | Others unaffected; can revoke device from GitHub |

### Encryption Flow

```
┌──────────────────────┐
│   Master Passphrase  │  (Stored in LastPass)
│ "solar-penguin-..."  │
└──────────┬───────────┘
           │
           ├─────────────┬─────────────┐
           │             │             │
    ┌──────▼──┐  ┌──────▼──┐  ┌──────▼──┐
    │ Desktop │  │ Laptop  │  │ Phone   │
    └─────────┘  └─────────┘  └─────────┘
           │             │             │
           └─────────────┼─────────────┘
                         │
              ┌──────────▼──────────┐
              │  Google Authenticator│  (Synced TOTP)
              │  Same 6-digit code   │  (every 30 sec)
              │  across all devices  │
              └──────────┬───────────┘
                         │
        ┌────────────────┴────────────────┐
        │                                 │
   ┌────▼───────────────────────────────┐│
   │  TOTP Code (6 digits)               ││
   │  847293                             ││
   └──────────────────────────────────┬──┘│
                                      │   │
                ┌─────────────────────▼───▼──────┐
                │ Passphrase + TOTP              │
                │ → Derive Encryption Key        │
                │ (PBKDF2 or Argon2)             │
                └─────────────────┬──────────────┘
                                  │
                     ┌────────────▼────────────┐
                     │  CLAUDE_SEARCH_KEY      │
                     │  (256-bit key)          │
                     │  Fernet symmetric       │
                     └────────────┬────────────┘
                                  │
                ┌─────────────────▼─────────────────┐
                │ Encrypt summaries + raw chats     │
                │ (Fernet AES-128 in CBC mode)      │
                └────────────────┬──────────────────┘
                                 │
                    ┌────────────▼──────────┐
                    │ GitHub Encrypted Blob │
                    │ gAAAAAB0x1y2z3...     │
                    │ (unreadable to GitHub) │
                    └────────────────────────┘
```

---

## Data Collection

### Source 1: Claude.ai

**Method**: Manual JSON export from Claude.ai UI  
**Frequency**: User exports conversations when ready  
**Format Collected**:
```json
{
  "id": "chat-uuid",
  "title": "Minecraft Mod Debugging",
  "created_at": "2026-07-31T14:22:00Z",
  "messages": [
    {
      "role": "user",
      "content": "...",
      "timestamp": "2026-07-31T14:22:05Z"
    },
    {
      "role": "assistant",
      "content": "...",
      "timestamp": "2026-07-31T14:22:15Z"
    }
  ]
}
```

### Source 2: VS Code Claude Extension

**Location**: `~/.vscode/extensions/anthropic.claude-vscode-*/`  
**Method**: Extension exposes chat history via filesystem or API  
**Frequency**: Periodic scan (collection daemon)

### Source 3: Cowork

**Method**: 
- **Option A** (if cloud): API call with authentication
- **Option B** (if local cache): Watch cache folder
- **Option C** (if neither): Manual export from UI

**Frequency**: Periodic scan or webhook

### Source 4: Local Folder

**Location**: `~/.claude-search-library/data/raw_exports/local/`  
**Method**: Watch folder for new JSON files  
**Format**: Any JSON matching normalized schema

### Normalization Schema

All sources convert to this structure:

```python
{
    "id": str,                      # Unique ID or content hash
    "source": str,                  # "claude-ai" | "vscode" | "cowork" | "local"
    "title": str,                   # Session title
    "created_at": str,              # ISO 8601
    "updated_at": str,              # Last message time
    "duration_seconds": int,         # ~estimate if available
    "message_count": int,
    "user_message_count": int,
    "assistant_message_count": int,
    "messages": [
        {
            "role": "user" | "assistant",
            "content": str,
            "timestamp": str,
            "tokens_approx": int
        }
    ],
    "device": str,                  # "desktop" | "laptop" | "phone"
    "tags": [],                     # Pre-filled or user-tagged
    "raw_path": str                 # File path to original
}
```

---

## Processing Pipeline

### Step 1: Batch Collection

```python
def collect_all_chats() -> dict:
    """
    Scan all sources for new/updated chats.
    Check for duplicates (by ID or content hash).
    Return: {"new": N, "errors": M, "total": T}
    """
    pass
```

### Step 2: Claude API Summarization

**System Prompt** (sent to Claude for each chat):

```
Analyze this chat session. Respond ONLY with valid JSON (no markdown, no preamble).

User and Claude worked on: [description]

Respond with exactly this structure:
{
    "session_tldr": "One sentence: what was accomplished",
    "learnings": [
        "Key takeaway 1",
        "Key takeaway 2"
    ],
    "patterns": [
        "Reusable workflow 1",
        "Reusable workflow 2"
    ],
    "tags": ["tag1", "tag2"],
    "mentioned_tools": ["Tool1", "Tool2"],
    "mentioned_languages": ["Python", "TypeScript"],
    "mentioned_frameworks": ["Phaser 3", "NeoForge"],
    "estimated_effort_minutes": 45,
    "topic_categories": ["minecraft-modding", "debugging"],
    "confidence_score": 0.92
}
```

**Processing**:
- Batch 10 chats/minute (respects Claude API rate limits)
- 30-second timeout per chat
- Exponential backoff on failures (3 retries)
- Log every summarization

**Output**: Sidecar JSON next to original
```
~/.claude-search-library/raw_chats/
├── 2026-07-31_desktop_12345.json          # Original
├── 2026-07-31_desktop_12345_summary.json  # Generated summary
```

### Step 3: Redaction

Apply regex patterns to detect secrets before storing:

| Pattern | Replacement |
|---------|-------------|
| `api_?key.*[a-z0-9]{20,}` | `[API_KEY_REDACTED]` |
| `ghp_[a-z0-9]{36}` | `[GH_TOKEN_REDACTED]` |
| `AKIA[0-9A-Z]{16}` | `[AWS_KEY_REDACTED]` |
| `patreon\.com/[^\s]+` | `[PATREON_LINK]` |
| Email pattern | `[EMAIL_REDACTED]` |
| IP address | `[IP_REDACTED]` |
| Discord token | `[DISCORD_TOKEN_REDACTED]` |

**If > 3 redactions detected**: Flag session for manual review before indexing.

### Step 4: Deduplication

```python
def deduplicate_sessions():
    """
    1. Compute content hash (SHA256)
    2. Check if hash exists in SQLite
    3. If exists: mark old as superseded, update new
    4. If new: insert
    """
    pass
```

---

## Storage Schema

### SQLite Tables (with cr-sqlite CRDT)

#### Table: `sessions`

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,                   -- "claude-ai" | "vscode" | "cowork" | "local"
    device TEXT,                            -- "desktop" | "laptop" | "phone"
    title TEXT,
    created_at TEXT NOT NULL,               -- ISO 8601
    updated_at TEXT,
    duration_seconds INTEGER,
    message_count INTEGER,
    user_message_count INTEGER,
    assistant_message_count INTEGER,
    raw_file_path TEXT,                     -- Path to JSON
    summary_file_path TEXT,                 -- Path to summary JSON
    content_hash TEXT UNIQUE,               -- SHA256 (deduplication)
    processed_at TEXT,                      -- When summarized
    status TEXT DEFAULT 'processed',        -- "new" | "processing" | "processed" | "failed" | "needs_review"
    review_reason TEXT,
    synced_at TEXT,                         -- Last sync timestamp
    sync_version INTEGER DEFAULT 1
);

CREATE INDEX idx_sessions_source ON sessions(source);
CREATE INDEX idx_sessions_created_at ON sessions(created_at DESC);
CREATE INDEX idx_sessions_status ON sessions(status);
```

#### Table: `summaries`

```sql
CREATE TABLE summaries (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id),
    tldr TEXT NOT NULL,
    learnings TEXT NOT NULL,                -- JSON array
    patterns TEXT NOT NULL,                 -- JSON array
    tags TEXT,                              -- JSON array
    mentioned_tools TEXT,                   -- JSON array
    mentioned_languages TEXT,               -- JSON array
    mentioned_frameworks TEXT,              -- JSON array
    estimated_effort_minutes INTEGER,
    topic_categories TEXT,                  -- JSON array
    confidence_score REAL,                  -- 0.0-1.0
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_summaries_confidence ON summaries(confidence_score DESC);
```

#### Table: `search_index`

```sql
CREATE TABLE search_index (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id),
    searchable_text TEXT NOT NULL,          -- title + tldr + learnings + patterns
    keywords TEXT
);

CREATE INDEX idx_search_full_text ON search_index(searchable_text);
```

#### Table: `redaction_log`

```sql
CREATE TABLE redaction_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    redaction_type TEXT,                    -- "api_key" | "github_token" | "email" etc.
    original_value TEXT,                    -- MASKED
    redacted_value TEXT,
    confidence_score REAL,
    redacted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    manually_reviewed INTEGER DEFAULT 0
);
```

#### Table: `sync_metadata`

```sql
CREATE TABLE sync_metadata (
    device_id TEXT PRIMARY KEY,             -- UUID
    device_name TEXT,                       -- "Desktop" | "MacBook-Work"
    last_sync_at TEXT,
    last_heartbeat TEXT,
    pending_changes INTEGER,                -- Sessions not yet synced
    is_hub INTEGER DEFAULT 0                -- Always 0 (no central hub)
);
```

### ChromaDB Collection

Vector embeddings of summaries (local-only, not synced):

```python
collection = client.get_or_create_collection(
    name="session_embeddings",
    metadata={"hnsw:space": "cosine"}
)

# For each summary:
collection.add(
    ids=[session_id],
    documents=[f"{tldr}\n\n{learnings_text}\n\n{patterns_text}"],
    metadatas=[{
        "source": source,
        "device": device,
        "created_at": created_at,
        "tags": tags_string,
        "confidence": confidence_score
    }]
)
```

---

## Encryption & 2FA

### Master Passphrase + Google Authenticator

**Two-Factor System:**
1. **Factor 1**: Master Passphrase (stored in LastPass)
   - Example: `solar-penguin-framework-mountain-crystal`
   - Used to encrypt/decrypt TOTP secret
   - User enters once per device setup

2. **Factor 2**: Google Authenticator (TOTP)
   - 6-digit code, changes every 30 seconds
   - Same TOTP secret across all devices (stored encrypted on GitHub)
   - Required to unlock encryption key

### Device Setup Flow

**Desktop (First Time)**:
```
$ python3 -m src.crypto --setup

Step 1: Generate TOTP Secret
  → QR Code displayed
  → Scan into Google Authenticator app on phone
  
Step 2: Enter Master Passphrase
  $ Enter master passphrase: solar-penguin-framework-mountain-crystal
  
Step 3: Verify TOTP Code
  → Check Google Authenticator on phone
  $ Enter code from Authenticator: 847293
  
Step 4: Success
  ✓ Encryption key derived and ready
  ✓ TOTP secret encrypted and stored on GitHub
  ✓ Master passphrase NOT stored anywhere
```

**Laptop (Join Existing Setup)**:
```
$ python3 -m src.crypto --join-device

Step 1: Enter Master Passphrase
  $ Enter master passphrase: solar-penguin-framework-mountain-crystal
  
Step 2: Download & Decrypt TOTP Secret
  → App fetches secrets.enc from GitHub
  → Decrypts using passphrase
  
Step 3: Add to Google Authenticator
  → QR Code displayed
  → Scan into Google Authenticator (now synchronized)
  
Step 4: Verify TOTP Code
  $ Enter code from Authenticator: 847293
  
Step 5: Success
  ✓ Same encryption key as desktop
  ✓ Same TOTP secret synced
  ✓ Can now encrypt/decrypt shared data
```

### Encryption Key Derivation

```python
from cryptography.fernet import Fernet
from argon2 import PasswordHasher

def derive_encryption_key(passphrase: str, totp_secret: str) -> bytes:
    """
    Derive a 256-bit encryption key from passphrase + TOTP secret.
    
    Input:
      passphrase: "solar-penguin-framework-mountain-crystal"
      totp_secret: "JBSWY3DPEBLW64TMMQ..." (base32)
    
    Output:
      32-byte key suitable for Fernet
    """
    # Combine both factors
    combined = f"{passphrase}:{totp_secret}".encode()
    
    # Derive key using Argon2 (slow, resistant to brute-force)
    key_material = PasswordHasher().hash(combined)
    
    # Truncate to 32 bytes for Fernet
    return key_material[:32]

# Encryption
cipher = Fernet(derived_key)
encrypted_blob = cipher.encrypt(plaintext)

# Decryption
plaintext = cipher.decrypt(encrypted_blob)
```

### GitHub Encrypted Secrets

```
File: .claude-search-library/secrets.enc

Content (encrypted, unreadable to GitHub):
{
  "totp_secret_encrypted": "gAAAAAB0x1y2z3...",
  "backup_codes": ["847293-backup-1", "847293-backup-2", ...],
  "created_at": "2026-07-31T14:22:00Z"
}
```

---

## Sync & CRDT Merging

### 5-Minute Sync Cycle

```
Every 5 minutes (or on-demand):

Device A (Desktop):
  1. Check local SQLite: "Any new sessions since last sync?" (instant)
  2. If NO → Exit (save network)
  3. If YES:
     a. Encrypt new summaries + raw chats
     b. Commit to GitHub
     c. Pull updates from Device B (if any)
     d. Merge via cr-sqlite CRDT
     e. Rebuild ChromaDB
     f. Update sync_metadata
```

### cr-sqlite CRDT Merging

cr-sqlite adds **Conflict-free Replicated Data Type** semantics to SQLite:

```python
# When same session is edited on Desktop and Laptop:

Desktop state: session_123 = {tldr: "X", learnings: [A, B]}
Laptop state: session_123 = {tldr: "Y", learnings: [A, B, C]}

# Both commit locally (offline capable)

# When syncing via GitHub:
cr-sqlite CRDT automatically merges:
  - Uses timestamp to determine winner
  - If Laptop is newer → Laptop version wins
  - If Desktop is newer → Desktop version wins
  - Last-Write-Wins (LWW) semantics
  - No manual conflict resolution needed

Result: All devices converge on same state automatically
```

### Sync Flow (Detailed)

```python
class SyncWorker:
    
    def push_to_github(self):
        """Upload encrypted data to GitHub"""
        # 1. Export changed sessions since last sync
        changed = self.get_changed_sessions()
        
        # 2. Encrypt summaries + raw chats
        encrypted_summaries = [
            encrypt_session(s, self.encryption_key) for s in changed
        ]
        
        # 3. Commit to GitHub
        self.git_commit(encrypted_summaries)
        self.git_push()
    
    def pull_from_github(self):
        """Download and merge changes from other devices"""
        # 1. Fetch latest from GitHub
        self.git_pull()
        
        # 2. Read encrypted blobs
        encrypted_blobs = self.read_encrypted_files()
        
        # 3. Decrypt using encryption key
        decrypted_sessions = [
            decrypt_session(blob, self.encryption_key) 
            for blob in encrypted_blobs
        ]
        
        # 4. Merge into local SQLite via cr-sqlite
        for session in decrypted_sessions:
            self.insert_or_update(session)  # cr-sqlite handles CRDT
    
    def sync(self, direction="bidirectional"):
        """Orchestrate full sync"""
        if direction in ["pull", "bidirectional"]:
            self.pull_from_github()
        
        if direction in ["push", "bidirectional"]:
            self.push_to_github()
        
        # Rebuild ChromaDB from merged SQLite
        self.rebuild_chromadb()
        
        # Update sync metadata
        self.update_sync_state()
```

### Network Data Usage (Real Numbers)

```
5-Minute Sync Check (per cycle):

Scenario A: No new sessions since last sync
  Local SQLite check: ~1ms, 0 bytes
  Network traffic: 0 bytes
  Result: Silent exit (save battery/data)

Scenario B: 1 new chat processed (typical)
  Encrypt 2 KB summary + 10 KB raw chat = 12 KB
  Git commit overhead = ~500 bytes
  GitHub pull = ~500 bytes
  Total network: ~13 KB

Daily (5 syncs, 2 have data):
  Average: 26 KB/day

Monthly:
  ~800 KB/month (negligible)

Annual:
  ~10 MB/year (trivial)

Takeaway: Fully encrypted, multi-device sync costs almost nothing
```

---

## Search Implementation

### Search Types

#### 1. Semantic Search (ChromaDB)

```python
def semantic_search(query: str, top_k: int = 10) -> list:
    """
    Query: "How do I handle async patterns in Minecraft mods?"
    Returns: Sessions about promises, callbacks, event listeners, etc.
    Even if exact words don't match.
    """
    pass
```

#### 2. Keyword Search (SQLite)

```python
def keyword_search(query: str, top_k: int = 10) -> list:
    """
    LIKE pattern match against search_index.
    Fallback if semantic search doesn't have results.
    """
    pass
```

#### 3. Filtered Search

```python
def search(
    query: str,
    source: str = None,          # "claude-ai" | "vscode"
    device: str = None,          # "desktop" | "laptop"
    date_range: tuple = None,    # (start, end)
    tags: list = None,           # ["minecraft", "modding"]
    top_k: int = 10
) -> list:
    """
    Combine semantic search + filters
    """
    pass
```

### Search Result Format

```python
{
    "session_id": "...",
    "title": "Minecraft Mod Debugging",
    "tldr": "Solved async race condition in event handler",
    "source": "vscode",
    "device": "laptop",
    "created_at": "2026-07-31T14:22:00Z",
    "relevance_score": 0.87,
    "top_pattern": "Use Promise.all() for parallel event listeners",
    "link_to_raw": "file://~/.claude-search-library/raw_chats/2026-07-31_laptop_12345.json"
}
```

---

## Deployment Checklist

### Pre-Deployment

- [ ] Python 3.11+ installed
- [ ] Git installed
- [ ] GitHub account (private repo created)
- [ ] Google Authenticator app on phone
- [ ] LastPass account (for master passphrase backup)
- [ ] Anthropic API key available

### Desktop Setup (First Device)

```bash
# 1. Clone repository
git clone https://github.com/nobody174/claude-search-library.git
cd claude-search-library

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Generate encryption key setup
python3 -m src.crypto --setup
# Follow prompts:
#   - Scan QR into Google Authenticator
#   - Enter master passphrase (from LastPass)
#   - Verify TOTP code
# Result: Encryption key ready, TOTP secret on GitHub

# 5. Initialize cr-sqlite database
python3 -m src.storage --init
# Creates SQLite schema with CRDT support

# 6. Test data collection
python3 cli.py collect --dry-run

# 7. Collect existing chats
python3 cli.py collect

# 8. Process chats (batch)
python3 cli.py process --batch-size 10

# 9. Start sync daemon (background)
python3 src/sync.py --daemon --interval 300 &

# 10. Start search API
python3 server.py --port 7654 &

# 11. Verify everything works
python3 cli.py search "test query"
curl http://localhost:7654/search?q=test
```

### Laptop Setup (Second Device)

```bash
# 1. Clone repository
git clone https://github.com/nobody174/claude-search-library.git
cd claude-search-library

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Join device (sync encryption key)
python3 -m src.crypto --join-device
# Follow prompts:
#   - Enter master passphrase (same as desktop)
#   - Scan TOTP secret QR into Google Authenticator
#   - Verify TOTP code
# Result: Same encryption key as desktop, TOTP synced

# 5. Initialize cr-sqlite database
python3 -m src.storage --init

# 6. Initial sync (pull all data from desktop)
python3 src/sync.py --pull
# All desktop sessions now on laptop (encrypted, decrypted locally)

# 7. Start sync daemon
python3 src/sync.py --daemon --interval 300 &

# 8. Start search API
python3 server.py --port 7654 &

# 9. Verify sync worked
python3 cli.py search "test query"
# Should return sessions from desktop
```

### Phone Setup (Third Device)

```bash
# Via web UI (built in Task 10):
1. Open https://localhost:7654 in Safari
2. Click "Setup New Device"
3. Enter master passphrase
4. Scan TOTP QR into Google Authenticator
5. Verify code
6. Done — can now search from phone
```

### Environment Variables (.env)

```bash
# File: ~/.claude-search-library/.env
# NEVER commit this file

ANTHROPIC_API_KEY=sk-proj-...
DATA_DIR=~/.claude-search-library
DB_PATH=~/.claude-search-library/library.db
CHROMADB_PATH=~/.claude-search-library/chromadb
MASTER_PASSPHRASE=solar-penguin-framework-mountain-crystal
GITHUB_TOKEN=ghp_...  # For automated GitHub pushes (optional)
GITHUB_REPO=github.com/nobody174/claude-search-library
```

### Automated Sync (Cron)

```bash
# macOS/Linux: crontab -e

# Collect new chats daily at 2 AM
0 2 * * * /home/vartdalffs/claude-search-library/venv/bin/python3 /home/vartdalffs/claude-search-library/cli.py collect --batch

# Process summaries daily at 3 AM
0 3 * * * /home/vartdalffs/claude-search-library/venv/bin/python3 /home/vartdalffs/claude-search-library/cli.py process --batch-size 10

# Sync to GitHub every 5 min (already running as daemon)
```

---

## Claude Code Build Tasks

### Task 1: Setup & Data Collection Module

**Prompt for Claude Code**:

```
Create the data collection module (src/collector.py) for the Claude Search Library.

Requirements:
1. Function: collect_from_claude_ai(export_folder: str) -> list[dict]
   - Read JSON files from Claude.ai exports folder
   - Validate against normalized schema (see SPEC)
   - Return list of normalized chat dicts
   
2. Function: collect_from_vscode(extensions_path: str = None) -> list[dict]
   - Find Claude extension in .vscode/extensions
   - Extract chat history
   - Normalize to schema
   
3. Function: collect_from_cowork(cowork_path: str = None) -> list[dict]
   - Either fetch from local cache or API
   - Normalize to schema
   
4. Function: collect_from_local(folder_path: str) -> list[dict]
   - Watch folder for new JSON files
   - Auto-import and normalize
   
5. Function: collect_all() -> dict
   - Run all collectors
   - Handle errors gracefully
   - Return: {"new": N, "errors": M, "total": T}
   
6. Implement file watching with watchdog library
   - --watch flag: runs collection on interval
   - Default interval: 300 seconds (5 minutes)
   
Test with sample exports; include mock JSON in tests
```

### Task 2: Processing & Summarization Module

**Prompt for Claude Code**:

```
Create the processing module (src/processor.py) for Claude API summarization.

Requirements:
1. Function: summarize_chat(chat_dict: dict, api_key: str) -> dict
   - Concatenate all messages into narrative
   - Truncate to 16k tokens if needed
   - Call Claude API with system prompt (see SPEC)
   - Parse JSON response (with error recovery)
   - Return summary dict with tldr, learnings, patterns, tags, etc.
   
2. Function: process_batch(session_ids: list, batch_size: int = 10)
   - Batch process sessions (respects rate limits)
   - Max 10 calls/minute to Claude API
   - Exponential backoff on transient failures
   - Log each success/failure with timestamp
   - Save summary as sidecar JSON
   
3. Error handling
   - Parse JSON errors: retry up to 3 times
   - Timeout (>30s): skip session, log warning
   - Invalid schema: save to "needs_review" queue
   
4. Logging
   - Log to ~/.claude-search-library/logs/processing.log
   - Include: timestamp, session_id, status, error (if any)

Test with sample chats; mock API calls in tests
```

### Task 3: Redaction & Privacy Module

**Prompt for Claude Code**:

```
Create the redaction module (src/redactor.py) for sensitive data masking.

Requirements:
1. Function: redact_summary(summary_dict: dict, session_id: str) -> tuple[dict, list]
   - Apply regex patterns (see SPEC table)
   - Match patterns in order of highest confidence
   - Replace matches with placeholders: [API_KEY_REDACTED], etc.
   - Track redactions in audit trail
   - Return (redacted_summary, redaction_events)
   
2. Implement redaction patterns:
   - API keys, GitHub tokens, AWS keys
   - Patreon URLs, emails
   - Discord tokens, IP addresses
   
3. Logic: If > 3 redactions detected
   - Mark session as "needs_review"
   - Don't index until manually approved
   - Log reason in SQLite redaction_log
   
4. Logging
   - Log all redactions to ~/.claude-search-library/logs/redaction.log
   - Also store in SQLite redaction_log table
   - Include: timestamp, pattern type, confidence, replaced value

Test with examples containing secrets (mock, don't leak real secrets)
```

### Task 4: Storage Module (SQLite + cr-sqlite)

**Prompt for Claude Code**:

```
Create the storage module (src/storage.py) for SQLite + cr-sqlite operations.

Requirements:
1. Database initialization
   - Create all tables (sessions, summaries, search_index, redaction_log, sync_metadata)
   - Load cr-sqlite extension (CRDT support)
   - Set up indices
   - Handle schema upgrades
   
2. CRUD functions for sessions table:
   - insert_session(session_dict) -> session_id
   - update_session(session_id, updated_fields) -> bool
   - get_session(session_id) -> dict
   - get_all_sessions() -> list[dict]
   - mark_as_processed(session_id, status)
   - mark_for_review(session_id, reason)
   
3. CRUD functions for summaries table:
   - store_summary(session_id, summary_dict) -> bool
   - get_summary(session_id) -> dict
   
4. Functions for search_index:
   - index_session(session_id, searchable_text, keywords) -> bool
   
5. Functions for redaction_log:
   - log_redaction(session_id, redaction_type, original, replacement, confidence)
   - get_redactions_for_session(session_id) -> list[dict]
   
6. Utility functions:
   - check_duplicate(content_hash) -> bool
   - get_session_count() -> int
   - get_stats() -> dict
   
7. Connection management
   - Use context manager (with statement)
   - Auto-commit for insert/update
   - Thread-safe
   
Test with in-memory SQLite (:memory:) for unit tests
```

### Task 5: Vector Embeddings & ChromaDB Module

**Prompt for Claude Code**:

```
Create the embeddings module (src/embedder.py) for ChromaDB integration.

Requirements:
1. Initialize ChromaDB
   - Create PersistentClient at ~/.claude-search-library/chromadb
   - Get or create collection "session_embeddings"
   - Set up metadata schema
   
2. Function: embed_session(session_id: str, summary_dict: dict) -> bool
   - Concatenate: tldr + learnings + patterns
   - Add to ChromaDB with metadata:
     - source, device, created_at, tags, confidence_score
   - Handle embeddings automatically
   - Return True if successful
   
3. Function: semantic_search(query: str, top_k: int = 10) -> list[dict]
   - Embed query
   - Query collection for top_k similar documents
   - Fetch metadata for each result
   - Return list of results with session_id, relevance_score, metadata
   
4. Function: delete_embedding(session_id: str) -> bool
   - Remove session from ChromaDB (for re-processing)
   
5. Function: reindex_all() -> int
   - Clear and rebuild entire ChromaDB collection
   - Iterate all processed sessions from SQLite
   - Re-embed all
   - Return count of re-embedded sessions
   
6. Error handling
   - Handle embedding failures gracefully
   - Log to embedding.log
   
Test with sample summaries; verify search quality
```

### Task 6: Encryption & 2FA Module

**Prompt for Claude Code**:

```
Create the encryption and 2FA module (src/crypto.py) for master passphrase + TOTP.

Requirements:
1. Function: setup_device_first_time() -> dict
   - Generate TOTP secret (base32)
   - Display QR code for Google Authenticator
   - Prompt user for master passphrase
   - Verify TOTP code (must be current)
   - Derive encryption key from (passphrase + TOTP secret)
   - Encrypt TOTP secret with passphrase
   - Store encrypted TOTP on GitHub (secrets.enc)
   - Return: {"encryption_key": bytes, "totp_secret": str}
   
2. Function: join_device_existing_setup() -> dict
   - Prompt user for master passphrase
   - Fetch encrypted TOTP from GitHub
   - Decrypt using passphrase
   - Display QR code for Google Authenticator
   - Verify TOTP code
   - Derive encryption key from (passphrase + TOTP secret)
   - Return: {"encryption_key": bytes, "totp_secret": str}
   
3. Function: derive_encryption_key(passphrase: str, totp_secret: str) -> bytes
   - Combine both factors
   - Use Argon2 for key derivation (slow, brute-force resistant)
   - Return 32-byte key for Fernet
   
4. Function: encrypt_data(plaintext: bytes, encryption_key: bytes) -> str
   - Use Fernet (AES-128 CBC)
   - Return base64 ciphertext
   
5. Function: decrypt_data(ciphertext: str, encryption_key: bytes) -> bytes
   - Use Fernet
   - Return plaintext
   
6. TOTP verification
   - Verify code is current (within ±1 time step)
   - Handle time drift gracefully
   
7. Backup codes
   - Generate 10 backup codes (for lost phone recovery)
   - Store encrypted on GitHub
   
Test with mock TOTP; verify encryption/decryption roundtrips
```

### Task 7: Distributed Sync Module

**Prompt for Claude Code**:

```
Create the sync module (src/sync.py) for GitHub-based distributed sync with CRDT merging.

Requirements:
1. Function: push_to_github()
   - Export changed sessions since last sync
   - Encrypt summaries + raw chats with encryption_key
   - Commit encrypted blobs to GitHub
   - Push to origin
   - Update sync_metadata with timestamp
   
2. Function: pull_from_github()
   - Fetch latest from GitHub
   - Read encrypted blobs
   - Decrypt using encryption_key
   - Merge into local SQLite via cr-sqlite (CRDT auto-merge)
   - Update sync_metadata
   
3. Function: sync(direction="bidirectional")
   - Orchestrate full sync: pull, merge, push
   - Rebuild ChromaDB from merged data
   - Handle errors gracefully
   
4. cr-sqlite CRDT integration
   - Insert sessions using cr-sqlite (handles conflicts automatically)
   - No manual conflict resolution needed
   - Last-Write-Wins (LWW) semantics
   
5. Daemon mode
   - Run sync every N seconds (default 300 = 5 min)
   - Check for changes locally before network calls (save data)
   - If no changes → exit silently
   - If changes → encrypt, commit, pull, merge
   
6. Logging
   - Log all syncs to ~/.claude-search-library/logs/sync.log
   - Include: timestamp, direction, files changed, merge conflicts (if any)
   
Test with mock GitHub operations; verify merging behavior
```

### Task 8: Search Interface (CLI + REST API)

**Prompt for Claude Code**:

```
Create the search interface modules:
- src/search.py: Core search logic
- cli.py: Command-line interface
- server.py: Flask REST API

Requirements for src/search.py:

1. Function: semantic_search(query: str, top_k: int = 10, filters: dict = None) -> list[dict]
   - Call ChromaDB semantic_search
   - Apply filters if provided (source, tags, device, date_range)
   - Fetch full session + summary from SQLite
   - Return ranked results
   
2. Function: keyword_search(query: str, top_k: int = 10) -> list[dict]
   - SQL LIKE pattern match against search_index
   - Return results
   
3. Function: search(query: str, mode: str = "semantic", **kwargs) -> list[dict]
   - Route to semantic or keyword search
   - Apply filters
   - Log search to search.log

Requirements for cli.py:

1. Command: claude-search <query>
   - Basic semantic search
   - Print results in table format
   
2. Command: claude-search collect [--watch] [--dry-run]
   - Trigger data collection
   - --watch: run continuously
   
3. Command: claude-search process [--batch-size N] [--watch]
   - Trigger summarization
   
4. Command: claude-search search <query> [--mode semantic|keyword] [--top-k N] [--filters JSON]
   - Advanced search with filters
   
5. Command: claude-search sync [--pull] [--push] [--watch]
   - Trigger sync operations

Use Click library for CLI

Requirements for server.py (Flask):

1. GET /search?q=QUERY&top_k=10
   - JSON response: {results: [...], total_results: N, query_time_ms: X}
   
2. GET /session/<session_id>
   - Return full session + summary details
   
3. GET /stats
   - System stats: total sessions, by source, by status, etc.
   
4. GET /devices
   - List connected devices (sync status)
   
5. POST /review/<session_id>/approve
   - Mark session as approved (for needs_review)

Use Flask; CORS enabled for mobile access
```

### Task 9: Configuration & Initialization

**Prompt for Claude Code**:

```
Create config setup (config_template.yaml, config loader, initialization)

Requirements:
1. Create config_template.yaml with sections:
   - api: ANTHROPIC_API_KEY
   - storage: DATA_DIR, DB_PATH, CHROMADB_PATH
   - sync: GITHUB_REPO, SYNC_INTERVAL (default 300)
   - processing: BATCH_SIZE, MAX_WORKERS, RATE_LIMIT_PER_MIN
   - redaction: REDACTION_RULES, FLAG_FOR_REVIEW_THRESHOLD
   - server: PORT, HOST, ALLOWED_ORIGINS
   
2. Function: load_config(config_path: str) -> dict
   - Load YAML
   - Validate required fields
   - Merge with env var overrides
   - Return config dict
   
3. Function: create_directories()
   - Ensure all required directories exist
   
4. Main initialization entry point:
   - python3 -m src.storage --init
   - Creates DB schema, initializes ChromaDB, creates directories
   - Validates config

Test initialization on fresh machine
```

### Task 10: Web UI for Multi-Device Access (Mobile + Desktop)

**Prompt for Claude Code**:

```
Create a React web UI (public/index.html + src/api.js) for searching from phone/tablet/browser.

Requirements:
1. Setup: Master passphrase + TOTP verification
   - Input fields for passphrase and TOTP code
   - Unlock encryption key locally
   
2. Search interface
   - Search box (semantic search)
   - Filters: source, device, date range, tags
   - Results displayed as cards
   
3. Session detail view
   - Summary + learnings + patterns
   - Link to raw chat file (if available locally)
   
4. Device sync status
   - Show last sync time
   - Manual sync button
   
5. Responsive design
   - Works on desktop, tablet, phone (iOS Safari)
   
6. Local encryption
   - Encryption key never sent to server
   - All decryption happens client-side
   
Build with React + Tailwind CSS; deploy to same Flask server
```

---

## Multi-Device Setup Guide

### Scenario: Desktop + Laptop + iPhone

**Step 1: Desktop Setup** (see Deployment Checklist → Desktop Setup)

```bash
cd ~/projects/claude-search-library
python3 -m src.crypto --setup

# Follow prompts:
#   Scan QR into Google Authenticator
#   Enter master passphrase (store in LastPass)
#   Verify TOTP code
#   ✓ Encryption key ready
```

**Step 2: Laptop Setup** (same directory structure)

```bash
cd ~/projects/claude-search-library
python3 -m src.crypto --join-device

# Follow prompts:
#   Enter master passphrase (from LastPass)
#   Scan TOTP QR into Google Authenticator (synced)
#   Verify TOTP code
#   ✓ Now has same encryption key as desktop
```

**Step 3: iPhone Setup** (via web UI)

```
1. Safari: https://laptop-ip:7654 (or desktop-ip if on same WiFi)
2. Click "Setup New Device"
3. Enter master passphrase (from LastPass)
4. Scan TOTP QR into Google Authenticator (synced)
5. Verify TOTP code
6. ✓ Can now search from Safari
```

### Data Flow Example

```
Desktop Chat Created:
  1. New chat in Claude.ai
  2. Export JSON
  3. Collector detects it
  4. Processor summarizes (Claude API)
  5. Redactor checks for secrets
  6. Stored in local SQLite + ChromaDB
  7. Sync daemon (every 5 min):
     a. Encrypt summary + raw chat
     b. Commit to GitHub
     c. Pull from GitHub (check if Laptop has new data)
     d. cr-sqlite merges automatically
     e. ChromaDB updated

Laptop User Searches:
  1. Open Safari: https://localhost:7654
  2. Search: "minecraft mod debugging"
  3. Semantic search finds Desktop's chat (via ChromaDB)
  4. Results shown immediately (all from local cache)
  5. Click "View Original" → Opens raw chat file (if local)
  6. If want Desktop's raw chat → Click link → GitHub download (encrypted) → decrypt locally

iPhone User:
  1. No local storage (temporary cache only)
  2. Search query goes to laptop/desktop via Flask API
  3. Results retrieved, summaries shown
  4. Raw chats not available on phone (design choice: save space)
  5. Can always open laptop to see full context
```

---

## Troubleshooting

### Issue: "Sync fails with GitHub authentication"

**Cause**: GitHub token expired or permissions missing  
**Solution**:
```bash
# Re-authenticate
git config --global credential.helper store
# Re-enter credentials (or use personal access token)
```

### Issue: "TOTP code keeps failing"

**Cause**: Device time drift  
**Solution**:
```bash
# Sync system time
# macOS/Linux:
sudo sntp -s time.apple.com

# Verify Google Authenticator is correct app
# Try ±1 time step (current + next code)
```

### Issue: "Encryption key mismatch between devices"

**Cause**: Different passphrase or TOTP secret  
**Solution**:
```bash
# Check stored TOTP on GitHub
cat .claude-search-library/secrets.enc

# Retrieve master passphrase from LastPass
# Retry join-device with correct passphrase
python3 -m src.crypto --join-device
```

### Issue: "CRDT merge created unexpected data"

**Cause**: cr-sqlite conflict resolution chose unexpected winner  
**Solution**:
```bash
# Check sync logs
tail -f ~/.claude-search-library/logs/sync.log

# Revert to previous state
git reset --hard HEAD~1  # Undo last commit

# Re-sync
python3 src/sync.py --pull
```

### Issue: "Phone can't see Desktop data"

**Cause**: Initial sync not completed  
**Solution**:
```bash
# On desktop
python3 src/sync.py --push  # Force push

# On phone
# Refresh page
# Wait 30 seconds for pull to complete
# Retry search
```

---

## Summary

This specification is **complete and ready for Claude Code implementation**.

**Handing to Claude Code:**
1. Copy all 9 build task prompts from "Claude Code Build Tasks" section
2. Run sequentially in Claude Code (VS Code)
3. Each task builds on the previous one
4. By Task 9, you have a working system

**First Run on Desktop:**
```bash
python3 -m src.crypto --setup              # One-time 2FA setup
python3 cli.py collect                     # Grab existing chats
python3 cli.py process --batch-size 10     # Summarize them
python3 src/sync.py --daemon &             # Start sync daemon
python3 server.py --port 7654 &            # Start search API
python3 cli.py search "test query"         # Verify it works
```

**Add Laptop:**
```bash
python3 -m src.crypto --join-device        # One-time, synced 2FA
python3 src/sync.py --pull                 # Pull all Desktop data
python3 src/sync.py --daemon &             # Start sync daemon
python3 cli.py search "test query"         # Verify it works
```

**Add iPhone:**
```
Safari: https://your-laptop-ip:7654
Setup New Device (same 2FA)
Done — search from phone
```

---

**Questions before handing to Claude Code?**

🎯 **Ready to build?**
