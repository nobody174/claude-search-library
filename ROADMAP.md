# Phase 2 Roadmap

Features to implement after public launch:

## 1. PowerShell Orchestration (HIGH)
- Separate collectors per source (claude.ai, VS Code, Cowork, local)
- Two modes: fail_fast=True (manual/dev), fail_fast=False (automated cron)
- File: src/orchestration.py
- CLI: python3 cli.py collect --source claude.ai --fail-fast

## 2. Cost Reporting (MEDIUM)
- Track API spend per session
- Monthly/quarterly reports
- File: src/cost_tracker.py
- CLI: python3 cli.py costs --month 2026-08

## 3. Markdown Export (MEDIUM)
- Export session + summary as .md file
- Shareable format
- File: src/export.py
- CLI: python3 cli.py export SESSION_ID --format markdown

## 4. Web Chat Import (MEDIUM)
- Import from claude.ai via private API (if available)
- Automated daily sync
- File: src/collectors/claude_web.py

## 5. Retention/Pruning (LOW)
- Delete old sessions (>1 year)
- Keep summaries in index
- File: src/maintenance.py
- CLI: python3 cli.py prune --older-than 365 --dry-run

## 6. Secure credential entry UI (HIGH)
- Problem found during real end-to-end testing: `--setup`/`--join-device`/`sync`
  use `getpass.getpass()`/`input()`, which only work in a real interactive
  terminal. There's no way to feed a passphrase or live TOTP code into these
  flows from an automated/non-interactive context (e.g. an agent driving the
  CLI on the user's behalf), and no secure side-channel exists today other
  than a plaintext `.env` file the user edits by hand and we remember to
  clear afterward.
- Build a small local popup/GUI (or a one-time local web form served on
  localhost, similar in spirit to public/index.html's setup page) that
  collects the passphrase + TOTP code securely for a single operation, hands
  the derived key to the calling process in memory only, and never persists
  either value to disk.
- Should replace the `.env`-based `MASTER_PASSPHRASE`/`TOTP_CODE` workaround
  used for one-off testing.

## 7. Sync/Export Management UI (HIGH)
- Problem: currently all sync operations (push/pull/collect/process) are
  CLI-only, driven through Claude Code or a terminal. There's no visual
  way to see sync status, trigger an export/import, or manage devices
  without typing commands.
- Add to public/index.html (or a new dedicated panel):
  - Sync status dashboard: last push/pull time per device, pending
    changes count, healthy/unhealthy archive status (from verify_archive())
  - Manual "Push" / "Pull" / "Sync now" buttons, wired to the existing
    server.py endpoints (or new ones exposing SyncWorker)
  - A file-drop/import UI for adding new Claude.ai export JSON files
    without touching the filesystem directly (currently requires manually
    placing files in ~/.claude-search-library/data/raw_exports/claude-ai/)
  - Device list showing all known devices (from sync_metadata) with
    last-seen timestamps
- Depends on: exposing SyncWorker's push/pull/sync methods via server.py
  REST endpoints (currently server.py has no sync-related routes at all)
- Consider pairing with item #6 (secure credential entry UI) so the whole
  device-join + sync flow can happen through the web UI instead of the
  CLI + popup combination used today
