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

## 4. Web Chat Import (MEDIUM) — DONE, rewritten for ToS safety 2026-08-02
- Original plan ("import via claude.ai private API") was rejected: it's
  the same unofficial-scraper approach ruled out in #8's research —
  Anthropic's Consumer Terms ban automated/non-human access to claude.ai,
  confirmed via dedicated research, real account-suspension risk.
- Built instead: `src/claude_export_import.py` converts the ZIP/JSON a
  user downloads through claude.ai's own Settings -> Export Data feature
  (the only sanctioned path, same one #8 confirmed is desktop/web-only)
  into the per-session raw-export JSON `collect_from_claude_ai()` already
  watches. Never talks to claude.ai's API — only reads a file the user
  already has on disk.
- CLI: `python3 cli.py import-export PATH [--run-collect]`
- No automated daily sync — the official export is a manual download,
  so there's nothing to poll.

## 5. Retention/Pruning (LOW)
- Delete old sessions (>1 year)
- Keep summaries in index
- File: src/maintenance.py
- CLI: python3 cli.py prune --older-than 365 --dry-run

## 9. Claude desktop app / claude.ai chat capture — UNSOLVED, actively being researched (HIGH)
- Problem: the user has "a lot of" real conversations in the Claude
  desktop app (claude.ai account) that are NOT in the library. Only
  Claude Code CLI sessions are collected automatically today. The user
  explicitly does not want a manual export→zip→email→unzip→import
  workflow as an ongoing habit (roadmap #4's importer exists for a
  one-time/occasional catch-up, but that's not automatic capture).
- Investigated (2026-08-03, via background research agent) whether the
  desktop app's own local cache could be read directly — same category
  of solution as roadmap #4's local-file approach for Claude Code, NOT
  the ToS-violating claude.ai-private-API-scraping path ruled out in #8.
  This is a fundamentally different, legitimate approach: reading a
  local cache file an app *the user runs* wrote to *their own disk*.
- **Findings so far:**
  - The desktop app is MSIX/Microsoft-Store-packaged; its Electron
    userData lives at
    `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\`
    (not the usual `%APPDATA%\Claude` — virtualized by the MSIX sandbox).
  - It caches data locally via Chromium's IndexedDB, backed by LevelDB,
    at `IndexedDB\https_claude.ai_0.indexeddb.leveldb\` (+ a sibling
    `.indexeddb.blob` dir for large/overflow values).
  - The app is currently running while the app is open, so the LevelDB
    store must be **copied to a temp location before reading** (LevelDB
    holds a single-writer lock) — never open or write to the live store.
  - Confirmed there IS real conversation-related data present: a large
    (~715KB) `react-query-cache` entry spilled to the `.indexeddb.blob`
    overflow directory decodes (partially) to real account data
    (matching email/org info) and appears to be a persisted cache of the
    conversation list/detail react-query state.
  - **The actual blocker**: reading the *populated* content requires
    parsing Chromium's internal V8 "serialized script value" binary
    format (used for all IndexedDB values), which is not JSON. Two
    Python libraries were tried:
    - `chromium-reader` (pure-Python, pip) — has a real bug in its key
      classification code, reports zero databases. Not usable.
    - `ccl_chromium_reader` (the actual CCL Forensics library — install
      via `pip install git+https://github.com/obsidianforensics/ccl_chrome_indexeddb.git`,
      NOT the nonexistent PyPI names `ccl_chrome_indexeddb`/
      `ccl-chromium-reader`) — correctly resolves databases/object
      stores, but its V8 `Deserializer` throws `Unknown tag` errors
      partway through this specific blob's nested sparse/dense JS-array
      structures. Patching around the error causes byte-stream desync,
      producing corrupted output (e.g. `queries: [{}, null, null, ...]`)
      rather than real recovered data — worse than no collector, so no
      collector was shipped rather than fabricate a working one.
  - Only 2 IndexedDB databases exist for the claude.ai origin:
    `keyval-store` (drafts/pin-state only, not transcripts) and
    `claude-device-binding` (empty, auth-related). Not exhaustively
    ruled out: Cache Storage API, other on-disk files the Electron app
    might use instead of/alongside IndexedDB.
- **Next steps to try** (in rough priority order):
  1. Find or write a more complete V8 deserializer that correctly
     handles object back-references inside dense/sparse arrays — this
     looks like the actual missing piece (repeated string keys across
     many cached query entries likely get serialized as back-reference
     tags, and mishandling those would produce exactly the observed
     cascading misalignment).
  2. Check whether `ccl_chromium_reader` has open issues/newer commits
     upstream addressing this, or whether a different/newer Chromium
     IndexedDB parsing tool exists that handles it correctly.
  3. Look for conversation data in other on-disk locations the app
     might use (Cache Storage API, other SQLite/LevelDB stores under the
     same `LocalCache\Roaming\Claude\` tree) as an alternative or
     supplementary source.
  4. If the V8 deserializer gap proves genuinely unfixable in reasonable
     time, consider writing a purpose-built minimal parser for just the
     specific tag types this blob uses, rather than a general-purpose
     V8 deserializer — narrower scope, more tractable.
- Do not abandon this without exhausting the above — the user has
  explicitly asked for continued, actively-pursued research on this
  until solved (see chat log 2026-08-03).

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

## 8. iOS chat capture — UNSOLVED, needs a real automated path (HIGH)
- Problem: there is currently no way to get conversations out of the
  Claude iOS app into this archive without the user manually
  copy/pasting each chat by hand. A manual step "gets forgotten, or not
  done" (user's words) — if collection depends on manual labor, the
  phone is effectively out of scope for this whole project, since it
  defeats the "collects from all Claude interfaces" goal in CLAUDE.md.
- Researched and ruled out (2026-08-02, via research agent — see chat log
  around this date for full findings):
  - Official export (Settings → Export data) is the only sanctioned path
    and is desktop/web-only — Anthropic's own docs confirm it cannot be
    run from Claude for iOS/Android at all.
  - The iOS app's Share Sheet only works inbound (share content *into*
    Claude) — there is no outbound "share this conversation out" intent,
    no documented URL scheme, no Shortcuts gallery action for exporting
    a conversation. Nothing for an iOS Shortcut to hook into.
  - Unofficial cookie-based scrapers of claude.ai's internal API exist
    and genuinely work (e.g. github.com/socketteer/Claude-Conversation-Exporter,
    github.com/ryanschiang/claude-export, github.com/st1vms/unofficial-claude-api)
    but Anthropic's Consumer Terms explicitly ban "automated or
    non-human means" of accessing claude.ai, and 2026 enforcement
    reporting shows this is actively policed. Do not build on these —
    real account-suspension risk, not a theoretical one.
  - A "one-tap save" button in our own web UI was considered, but still
    requires the user to manually copy the chat text first — doesn't
    remove the labor, just moves where it happens. Correctly rejected
    by the user as not actually solving the problem.
- Still open, needs genuine rethinking rather than another workaround
  pass at the same idea. Possible directions worth researching properly
  (none vetted yet):
  - On-device automation that reads the screen/accessibility tree
    (e.g. an iOS Shortcut using accessibility APIs to extract on-screen
    text) instead of touching claude.ai's API at all — sidesteps the
    ToS problem since it never talks to Anthropic's servers
    automatically, but unproven, likely fragile, and may hit Apple's
    own Shortcuts/Screen Time restrictions.
  - Whether Anthropic offers (or would ever offer) a legitimate
    data-export API for consumer accounts, e.g. as a paid/business tier
    feature — worth just asking Anthropic support directly rather than
    reverse-engineering around them.
  - Reconsidering scope: is capturing *phone-originated* conversations
    actually required, vs. using the phone purely as a search/reference
    client (per the original CLAUDE.md Key Decision #5) and doing all
    real conversation work on desktop/laptop where official export
    works fine?
- Do not schedule implementation work here until a specific approach is
  chosen — this entry exists to make sure the gap stays visible instead
  of being silently dropped.
