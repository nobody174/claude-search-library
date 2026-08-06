# Troubleshooting

Common issues and fixes, organized by area. If you're not sure where to start, run `python3 cli.py verify --verbose` first — it will often tell you exactly what's wrong.

---

## Setup & Installation

### `ModuleNotFoundError` when running any command

Your virtual environment isn't active, or dependencies weren't installed into it.

```bash
source venv/bin/activate          # macOS/Linux
venv\Scripts\activate             # Windows
pip install -r requirements.txt
```

### `Invalid configuration: Missing required field: ...`

`load_config()` validates required fields on every run and raises before doing anything else. The error message names the exact missing field (e.g. `storage.data_dir`, `api.anthropic_api_key`). Fixes:

- Make sure `config.yaml` exists (copy it from `config_template.yaml` if you haven't already)
- Make sure any `${ENV_VAR}` reference in `config.yaml` has that environment variable actually set — an unset variable substitutes to an empty string, which then fails required-field validation
- Check you're running commands from the directory containing `config.yaml`, or that `~/.claude-search-library/config.yaml` exists — see the README's config file priority order

### `cr-sqlite extension not loaded (falling back to plain SQLite)` in the logs

This is expected on most systems and **not an error**. The cr-sqlite native extension for CRDT-based merging isn't reliably available as a Python-loadable extension on every platform yet. The system automatically falls back to a plain SQLite Last-Write-Wins merge policy in `sync.py`, which is safe but resolves same-timestamp conflicts by keeping whichever side is newer rather than true CRDT merge semantics. This is a known, tracked limitation — see `CLAUDE.md` → Known Blockers.

---

## 2FA / Encryption

### `Invalid TOTP code` during `--setup` or `--join-device`

- Make sure your device's clock is accurate — TOTP codes are time-based and drift more than ~60 seconds will cause every code to fail. The verifier tolerates one 30-second step of drift either direction, not more.
- Make sure you're reading the code from the correct account in your Authenticator app if you have multiple entries.
- The code refreshes every 30 seconds — if you're slow to type it, it may have rotated. Wait for a fresh code and try again immediately.

### `Failed to decrypt TOTP secret — check your passphrase` during `--join-device`

This means the passphrase you entered doesn't match the one used during the original `--setup`. There's no recovery from a wrong passphrase other than entering the correct one — the whole design point is that the server side can't help you bypass this. Double-check for typos, extra spaces, or a wrong entry in your password manager.

### Lost my phone with the Authenticator app

You have not lost access, as long as you still have your master passphrase. On any device (the original one, a new one, or a spare):

```bash
python3 -m src.crypto --join-device
```

This fetches your encrypted TOTP secret from GitHub, decrypts it using **only your passphrase**, and shows you a fresh QR code to scan into a new Authenticator install. Your TOTP secret doesn't change — you're just re-adding the same account to a new app instance.

If you've also lost the passphrase, there is currently no recovery path — this is intentional (the passphrase is never stored anywhere, by design), but it does mean you must keep it safe in a password manager. A backup-codes mechanism exists in the code (`generate_backup_codes()` in `src/crypto.py`) but is not yet wired into the setup flow in this release.

### Want to add a second phone — but my CURRENT phone still works fine

**This is not the "lost my phone" case above — if your phone is lost, broken, or you have no working Authenticator code at all, use `--join-device` above instead.** This section is only for when your existing phone/Authenticator still works and you want to *also* set up a second one (a spare phone, or scanning into a replacement before wiping the old one) — you don't need the full `--join-device` flow for that:

```bash
python3 cli.py show-totp-qr
```

This requires proving you already have access: your passphrase, **and** a currently-valid code from your existing Authenticator app. If you don't have a working code at all (the "lost my phone" case above), use `--join-device` instead — `show-totp-qr` won't help you there, since it needs an existing code to prove access with.

### I set a weak/short passphrase and want to change it

There's currently no rotate-passphrase command. The practical approach is to run `--setup` again to establish a fresh passphrase + TOTP secret, then re-sync all devices with `--join-device`. Treat this as effectively starting a new archive identity — plan for some manual re-sync work on every device.

---

## Collection

### `collect` finds 0 new sessions but I know I have chats

- Check the source-specific paths: Claude.ai collection reads from manually exported JSON files, not a live API — you need to export your conversations from claude.ai first and drop them where the collector expects them.
- The VS Code collector looks under `~/.vscode/extensions/anthropic.claude-vscode-*/chat_history` by default — if your extension version or install location differs, pass the path explicitly (see `src/collector.py::collect_from_vscode`).
- Run `python3 cli.py collect --dry-run` to see counts without side effects, and check the collection log for skipped/errored files.

### A chat was collected twice / appears duplicated

Sessions are deduplicated by content hash (`compute_session_hash()` in `src/storage.py`), which hashes the actual messages/title/source — not the file name or session ID. Two different exports of the *same* conversation should dedupe automatically. If you're seeing true duplicates, run `python3 cli.py verify --verbose` and check the session/summary count stats — a real duplicate suggests the hash computation saw different content (e.g. an export that includes a timestamp inside the message content itself).

---

## Processing (Claude API)

### `process` is slow / rate limited

This is expected — the processor deliberately batches at a limited rate to respect Claude API rate limits (`rate_limit_per_min` in `config.yaml`, default from `config_template.yaml`). A large first-time batch of hundreds of sessions will take a while. Lower `--batch-size` if you want smaller, more frequent runs instead of one long one.

### `ANTHROPIC_API_KEY is not set` from `cli.py process`

Set the environment variable in the shell you're running the command from:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Note this must be set in the actual process environment — putting it only in `config.yaml` as `${ANTHROPIC_API_KEY}` doesn't set the variable, it reads it, so the export still has to happen somewhere.

---

## Search

### Semantic search returns nothing, or seems to ignore my query

- Confirm you've actually run `cli.py process` — semantic search is built on ChromaDB embeddings generated from summaries, so unsummarized sessions won't show up in `semantic` or `hybrid` mode.
- Try `--mode keyword` — if keyword search finds it but semantic doesn't, the summary/embedding may not have been generated yet, or the query phrasing is too far from the summary content for cosine similarity to surface it.

### Keyword search behaves like a plain substring match instead of ranked full-text search

Keyword search uses SQLite FTS5 with BM25 ranking, but the FTS5 index (`fts5_summaries`) is a snapshot table — it has to be built explicitly and isn't updated automatically as new summaries are added. If it hasn't been built yet, `keyword_search()` transparently falls back to a simpler LIKE-based scan against `search_index`, which explains ranking that looks "off." Rebuild the index after processing new sessions:

```python
from src.storage import Storage
with Storage() as db:
    db.create_fts5_index()
```

(There is currently no CLI flag for this — it's a direct Python call. If you find yourself doing this often, consider calling it automatically after every `process` batch.)

### Hybrid mode feels slower than expected

`hybrid_search()` always runs semantic search first, and only adds keyword results if semantic search was slow (default threshold: 500ms) or returned fewer than half of `top_k` results. If ChromaDB is consistently slow on your machine (large collection, constrained hardware), you'll pay that latency on every hybrid query before the keyword fallback even considers kicking in. Use `--mode keyword` directly if you want guaranteed-fast lookups and don't need semantic recall.

---

## Sync

### `sync` fails with a git error (`GitCommandError`)

- Confirm the local repo path passed to `SyncWorker`/`--daemon` is actually a git clone with a working `origin` remote pointed at your private data repo — this must be a *separate* repo from the code repo you cloned to build the tool, used purely to store your encrypted archive.
- Confirm `GITHUB_TOKEN` is set and has write access to that repo.
- If push fails due to the remote having diverged (another device pushed first), pull before pushing — the sync daemon does this automatically on its own cycle, but a manual `cli.py sync --push` without a preceding pull can hit this.

### My devices show different data after both say they synced

Without a genuine CRDT merge engine (see the cr-sqlite note above), conflicting concurrent edits are resolved by Last-Write-Wins on timestamp. If two devices modify related data within the same sync window, the "losing" side's specific edit can be silently dropped rather than merged. This is a known limitation, not a bug — see `CLAUDE.md` for the tracked status of proper cr-sqlite integration.

### Sync daemon isn't picking up new local changes

`check_for_changes()` compares each session's `updated_at`/`created_at` timestamp against this device's last recorded sync time in `sync_metadata`. If your system clock is wrong, or a session was inserted with a stale/incorrect timestamp, it may be silently excluded from what the daemon considers "changed." Run `cli.py sync --push` manually to force a push regardless.

---

## Archive Verification Failures

`python3 cli.py verify` runs 7 checks and reports `errors` (must-fix, archive is unhealthy) separately from `warnings` (worth knowing, not blocking). Common results:

| Message | Meaning | Fix |
|---|---|---|
| `Database integrity check failed: ...` | SQLite's own `PRAGMA integrity_check` found real corruption | Restore from a recent backup of the `.db` file if you have one, or rebuild from the JSONL mirror (below) as a partial recovery for summaries |
| `Session X: content hash mismatch` | The raw chat file's content genuinely changed since it was first collected — a live conversation that grew, a re-export, or a manual edit | As of 2026-08-04, just run `cli.py collect` (or `cli.py sync`, which collects first automatically) — `store_session_with_hash()` now updates the session in place and clears the stale hash instead of erroring. Only worth investigating further if the mismatch persists after a normal collect run |
| `Session/summary mismatch: N sessions but M summaries` (warning) | Some collected sessions haven't been processed yet, or a summary insert failed | Run `cli.py process` to catch up |
| `N session(s) reference a raw chat file that no longer exists` (warning) | Raw chat files were moved or deleted after collection | Restore the files if you still have them, or accept that raw-file links for those sessions are now broken (summaries are unaffected) |
| `Invalid JSON in JSONL mirror at line N` | The durability backup file (`ai-summaries.jsonl`) has a corrupted line | The good lines are still usable; regenerate the whole file with `export_summaries_to_jsonl()` once the database itself is confirmed healthy |
| `JSONL mirror not found` (warning) | You haven't run an export yet | Not urgent, but consider running `export_summaries_to_jsonl()` periodically so you have a durability backup |
| `FTS5 index not yet created` (warning) | Keyword/hybrid search is using the slower LIKE fallback | See the Search section above — call `create_fts5_index()` |

### Recovering the summaries table from the JSONL mirror

If your database is damaged but you have a JSONL export from before the damage occurred:

```bash
python3 -m src.storage --restore-from-jsonl
```

This rebuilds the `summaries` table from `~/.claude-search-library/summaries/ai-summaries.jsonl` using `INSERT OR REPLACE`, so it's safe to run more than once. Note this only restores **summaries**, not the `sessions` table itself — the JSONL mirror is a summaries-only backup, so sessions still need to exist (e.g. from re-running `collect`) for the restored summaries to attach to.

---

## Web UI

### The web UI shows a setup screen every time, even after I've already set up

The browser client currently persists nothing about your session across page loads beyond what your browser's own storage retains for that origin — if you're testing across different ports, in a private/incognito window, or clearing site data, you'll be asked to re-authenticate. This is a privacy trade-off, not a bug: the master passphrase and derived key are intentionally never persisted server-side.

### Web UI can't reach the server from my phone

- Confirm `server.py` is bound to an address your phone can reach (`--host 0.0.0.0`, not `127.0.0.1`, if you want LAN access) and that your phone is on the same network.
- Check the CORS configuration in `server.py` (`allowed_origins`) — if you're accessing via a hostname or IP not covered by it, browser requests will be blocked even though the server is reachable.
- Do not attempt to expose port 7654 directly to the public internet — see the [Security](README.md#security) section in the README for why, and use a VPN or SSH tunnel for remote access instead.

---

## Still Stuck?

- Run the specific command with more logging: check `~/.claude-search-library/logs/` — there's a separate log file per subsystem (`processing.log`, `redaction.log`, `sync.log`, `search.log`, `crypto.log`, `embeddings.log`).
- Run `python3 cli.py verify --verbose --json` and inspect the full structured report.
- See [CLAUDE.md](CLAUDE.md) for the architecture/module reference if you need to understand *why* something works the way it does, not just how to fix it.
