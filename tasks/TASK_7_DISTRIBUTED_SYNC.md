# Task 7: Distributed Sync Module

Create the sync module (`src/sync.py`) for GitHub-based distributed sync with CRDT merging.

## Requirements

1. **Function: `push_to_github()`**
   - Export changed sessions since last sync
   - Encrypt summaries + raw chats with encryption_key
   - Commit encrypted blobs to GitHub
   - Push to origin
   - Update `sync_metadata` with timestamp

2. **Function: `pull_from_github()`**
   - Fetch latest from GitHub
   - Read encrypted blobs
   - Decrypt using encryption_key
   - Merge into local SQLite via cr-sqlite (CRDT auto-merge)
   - Update `sync_metadata`

3. **Function: `sync(direction="bidirectional")`**
   - Orchestrate full sync: pull, merge, push
   - Rebuild ChromaDB from merged data
   - Handle errors gracefully

4. **cr-sqlite CRDT Integration**
   - Insert sessions using cr-sqlite (handles conflicts automatically)
   - No manual conflict resolution needed
   - Last-Write-Wins (LWW) semantics on timestamp

5. **Daemon Mode**
   - Run sync every N seconds (default 300 = 5 min)
   - Check for changes locally FIRST (save data)
   - If no changes → exit silently (save network)
   - If changes → encrypt, commit, pull, merge
   - Use APScheduler for scheduling

6. **Logging**
   - Log all syncs to `~/.claude-search-library/logs/sync.log`
   - Include: timestamp, direction, files changed, merge conflicts (if any)

## GitHub Directory Structure

```
github.com/nobody174/claude-search-library/
├── encrypted_summaries/
│   ├── 2026-07-31_desktop_summary_12345.enc
│   ├── 2026-07-31_laptop_summary_67890.enc
│   └── ...
├── encrypted_raw_chats/
│   ├── 2026-07-31_desktop_raw_12345.enc
│   ├── 2026-07-31_laptop_raw_67890.enc
│   └── ...
├── secrets.enc           # Encrypted TOTP secret
├── sync_metadata.json    # Unencrypted sync state
└── .gitignore
```

## Sync Metadata Format

```json
{
    "devices": {
        "desktop_1": {
            "device_name": "Desktop",
            "last_sync_at": "2026-07-31T14:22:00Z",
            "last_heartbeat": "2026-07-31T14:25:00Z",
            "pending_changes": 0
        },
        "laptop_1": {
            "device_name": "Laptop",
            "last_sync_at": "2026-07-31T14:20:00Z",
            "last_heartbeat": "2026-07-31T14:24:00Z",
            "pending_changes": 2
        }
    }
}
```

## Sync Flow (Detailed)

```python
class SyncWorker:
    
    def check_for_changes(self) -> int:
        """
        Quick local SQLite check: any sessions since last sync?
        Cost: ~1ms, 0 bytes network
        Return: count of changed sessions
        """
        pass
    
    def push_to_github(self):
        """Upload encrypted data"""
        pass
    
    def pull_from_github(self):
        """Download and merge changes"""
        pass
    
    def sync(self, direction="bidirectional"):
        """Orchestrate full sync"""
        pass
    
    def daemon_loop(interval=300):
        """Run every 5 minutes"""
        pass
```

## CLI Usage

```bash
# Manual sync
python3 src/sync.py --pull
python3 src/sync.py --push
python3 src/sync.py  # bidirectional

# Daemon mode (runs in background)
python3 src/sync.py --daemon --interval 300 &

# Watch mode (verbose logging)
python3 src/sync.py --daemon --watch
```

## Testing

- Mock GitHub operations (use GitPython)
- Test encryption/decryption of synced data
- Test CRDT merging behavior
- Test error recovery

## Output File

Save as: `src/sync.py`

---

**Ready?** Paste into Claude Code!
