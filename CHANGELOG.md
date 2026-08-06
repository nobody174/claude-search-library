# Changelog

A record of what's actually been built and fixed, in the order it happened.
For architecture/reference docs see [CLAUDE.md](CLAUDE.md); for what's still
open see [ROADMAP.md](ROADMAP.md) (future features) and
[BACKLOG.md](BACKLOG.md) (small deferred items).

---

## 2026-08-06, continued — mobile TOTP re-provisioning shipped

**Trigger: real friction the Android/TOTP work made obvious** — setting
up a new device already shows the TOTP QR code once, but there was no
way to see it again later (lost phone, phone reset, adding a second
phone) without redoing the entire `--join-device` flow.

- **Shipped `show_totp_qr_again()`** in `src/crypto.py`, wired into
  `cli.py show-totp-qr`. Reuses the same fetch+decrypt path
  `join_device_existing_setup()` already has, with two deliberate
  differences: requires the same proof-of-access bar as joining a
  device (passphrase AND a currently-valid TOTP code from an
  already-enrolled device, not just the passphrase alone); does NOT
  write a session cache, since this is a one-off display action, not a
  login — it always demands fresh proof rather than ever benefiting
  from the existing "stay logged in" cache window.
- Real security question asked and answered during review: is a local
  CLI command like this reachable by someone else on the same network?
  No — it's a local terminal command with no listening port, only
  runs if someone already has shell access to the machine, and even
  then requires both factors to actually see anything.
- Tests: 4 new (valid credentials displays the real QR, wrong
  passphrase rejected, wrong TOTP code rejected, no session cache
  written). 352 total passing.

---

## 2026-08-06, continued — Android chat capture shipped, closing the Android+iOS gap for real

**Trigger: the user's own question ("do iOS and Android Claude apps sync
the same account?") reopened what had just been closed as unsolved.**
Full arc in one session: research → live cross-device verification →
an Architect design pass → real implementation → 4 real bugs found and
fixed via live end-to-end testing → shipped and verified via the
actual CLI.

- **Discovery**: claude.ai conversations are one cloud-synced account
  across every mobile client, not siloed per platform (confirmed via
  Anthropic's own Help Center docs - the only documented siloing is
  Desktop app vs. mobile/web). Verified live: a conversation started on
  the user's iPhone appeared on an Android test phone within seconds
  under the same account. This means an Android-side capture mechanism
  reaches iPhone-originated conversations too, automatically - no
  iOS-side automation needed, no jailbreak, no ToS violation, since
  nothing ever touches the iPhone or claude.ai's servers directly.
- **Role attribution solved** (flagged by an Architect design pass as a
  hard blocker needing real investigation, not a guess): a message's
  enclosing container's left-edge x-offset is the real signal - Claude's
  replies sit in a full-width container starting at x=0; the user's own
  messages sit in a narrower, indented container. Found by inspecting a
  real device dump byte-for-byte, not assumed.
- **Shipped `src/android_bridge.py`**: drives a connected Android phone
  over ADB to extract conversation content via `uiautomator dump`
  (Android's built-in accessibility-tree tool - free, no root, no paid
  automation apps, contrary to the Tasker+AutoInput path initial
  research suggested). Split into pure parsing functions (real
  fixture-based tests, fixtures captured from an actual device) and
  device-driving functions verified against a real Samsung Galaxy
  Note20 Ultra during development - same testing split
  `collect_from_claude_desktop()` uses for its own untestable
  IndexedDB path.
- **4 real bugs found via live end-to-end testing, not caught by unit
  tests alone:**
  1. `adb` wasn't resolvable via `subprocess` despite working in an
     interactive shell (PATH differed) - fixed by resolving adb's real
     path once (PATH first, falling back to the standard per-OS SDK
     location).
  2. Non-ASCII conversation text crashed subprocess output decoding on
     Windows' default cp1252 console encoding - fixed by forcing UTF-8
     explicitly.
  3. `open_sidebar()` failed outright if the sidebar was already open
     and scrolled (its "already open" check relied on text that can
     scroll out of view) - fixed using a fixed-chrome `content-desc`
     signal instead, plus a self-healing relaunch-and-retry for the
     case where a stray BACK press exits the app to the home screen
     entirely.
  4. **The most serious**: `extract_conversation()` reused a
     conversation's tap bounds captured during an earlier sidebar
     enumeration pass - these go stale the moment the sidebar scrolls
     again for any reason, including a previous conversation's own
     extraction returning to a differently-scrolled sidebar. This
     silently extracted the **wrong conversation's content** in a real
     end-to-end run (returned real, plausible-looking text - just from
     the wrong chat) before being caught by checking against a known
     conversation's actual content. Fixed: every conversation is now
     re-located by title text, scrolling from the top, immediately
     before tapping.
- **Wired into `src/orchestration.py`**: `claude-android` is
  deliberately NOT in the default `SOURCES` set `cli.py sync` uses -
  unlike every other collector, this drives live device UI for real
  minutes per run and depends on a phone being reachable right now, not
  something to run silently on a 5-minute timer. Added `ALL_SOURCES` for
  the full set including it. New `cli.py collect --source
  claude-android` and `cli.py android-connect <ip>:<port>` (establishes
  and remembers a device connection, persisted to
  `~/.claude-search-library/data/android_device.json`).
- **Verified fully end-to-end via the real CLI**, not just the Python
  API: `cli.py android-connect` + `cli.py collect --source
  claude-android` against the real device collected and stored 16 real
  conversations (7 genuinely new) with 0 errors, confirmed via
  `cli.py verify` (still healthy) and direct database inspection - the
  known test conversation's content matched exactly, word-for-word,
  role-for-role.
- Tests: 348 passed (16 new for `android_bridge.py`'s parsing functions,
  against real fixture data, not hand-constructed).

---

## 2026-08-06, continued — BACKLOG.md review, a real doc-flow diagram, and a genuine "no raw file" fix

**Trigger: going through BACKLOG.md item by item for real suggested
decisions, rather than the earlier one-line table.** Also added a
Mermaid flowchart of the actual code flow (traced from source, not a
paraphrase of the existing high-level architecture summary) - see
`docs/ARCHITECTURE_FLOW.md`.

- **Unredacted git-history decision reconfirmed** now that going public
  is concrete: only `claude-search-library` (code) is going public,
  `claude-search-data` (the real chat archive, where the unredacted
  pre-fix history actually lives) stays private - so the 2026-08-05 call
  still holds. Checked the code repo's own history directly for real
  leaked secrets (none found - only placeholder syntax like `sk-ant-...`
  in setup instructions).
- **Root-caused the "5 sessions have no readable raw file" warning
  precisely, instead of leaving it as an unexplained gap.** All 5 turned
  out to be real Claude Code sessions synced from the laptop
  (`synced_at`/`sync_version` confirmed), where `raw_file_path` is
  `NULL` rather than a foreign-device path - the same underlying fact as
  the `raw_file_path`/`summary_file_path` foreign-device fix from
  earlier today, just predating that column being populated consistently
  across every collector/sync path. Not lost data, not something to
  search for - this desktop was never going to have
  `collect_from_claude_code()`'s locally-converted transcript file for a
  session that ran on a different machine.
- **Fixed `verify_archive()`'s Check 3** to distinguish a genuinely
  local anomaly (no raw path, never synced - a real problem) from this
  expected case (no raw path, but `synced_at` is set - foreign-device,
  same as an explicit non-local path). Verified against the real
  122-session library: the "5 sessions no readable raw file" warning is
  gone, `foreign_device_raw_paths` correctly grew from 56 to 61.
- **Two BACKLOG.md items turned out to be real, scopeable features, not
  permanent low-priority friction** - moved to ROADMAP.md: mobile TOTP
  re-provisioning (re-display an existing device's QR code without
  redoing full `--join-device` setup - worth doing now that mobile
  access is a real, used part of the project) and browser-profile chat
  capture (same LevelDB/Snappy/V8 technique as the already-solved
  desktop-app collector, applied to a regular Chrome/Edge profile -
  not needed for the current user's own Claude Code + desktop app
  workflow, but flagged as worth building if public users lean on
  claude.ai-via-browser more).

Tests: 332 passed (2 new - the NULL-raw-path-on-synced-vs-unsynced-session
distinction).

---

## 2026-08-06 — Security Auditor, Code Style Enforcer, and Release Manager passes

Three roles run back-to-back per the project's own AI-role workflow,
each finding real, independently-verifiable things - not review-theater.

- **Security Auditor**: reviewed the TLS change from 2026-08-05 (desktop)
  and its interaction with the existing session/auth machinery. TLS
  itself and the session lifecycle both came back clean - no mixed
  content, no fixation, no bypass shortcuts. Two real findings, both
  fixed: `/setup`'s brute-force lockout (5 attempts/15 min) could trap
  the *legitimate* user, not just an attacker, since it's keyed by IP
  with no way to distinguish a fat-fingered passphrase or a stale TOTP
  code from a real attack - loosened to 10 attempts/5 min. The CORS
  allowlist (`localhost`/`127.0.0.1`) was dead configuration that didn't
  match the app's own documented LAN-IP access pattern and wasn't doing
  any real protective work (`SameSite=Strict` on the session cookie
  already blocks the attack CORS would otherwise guard against) -
  changed to `origins=[]`, matching the app's actual security model.
- **Code Style Enforcer**: checked naming, docstrings, logging setup,
  and type hint consistency across the whole codebase against its own
  dominant convention (no formal linter config exists). Found the code
  itself in good shape overall - two real findings: `src/redactor.py`
  had its own duplicate `DB_PATH` constant instead of importing
  `storage.py`'s canonical `DEFAULT_DB_PATH`; and the header/footer
  banner convention added to `cli.py`/`server.py`/`public/index.html`
  hadn't propagated to any of the 13 `src/*.py` modules - now applied
  to all of them for consistency.
- **Release Manager / Versioning Advisor**: evaluated whether this
  project needs app-level version numbers/git tags, given it's not
  packaged/published (deployment is `git pull`, not a release step).
  Conclusion: no - git SHAs + CHANGELOG.md's existing date-based entries
  already serve that purpose, and forcing version numbers onto entries
  like this one (multiple dated sub-entries on the same real day) would
  be artificial ceremony with no real reader. Found one genuine gap,
  distinct from `sync_protocol_version` (which guards the sync *wire
  format* between devices): nothing guarded against old code opening an
  already-migrated (newer-schema) local database - a local failure mode,
  not a sync failure, so `sync_protocol_version`'s check never triggers
  for it. Fixed: `_run_schema_upgrades()` now raises `SchemaTooNewError`
  if a database's stored `schema_meta.version` is ahead of the running
  code's `SCHEMA_VERSION`, instead of silently running old-shape queries
  against a schema it doesn't understand.

Tests: 330 passed (added 1 new test for the schema-version-mismatch
guard), no regressions.

---

## 2026-08-05, continued — full project review + fix cascade

**Trigger: after the cr-sqlite work, ran a genuine "Project Reviewer, full
analysis" pass against the whole codebase, then worked the findings
through a deliberate sequence of roles** (Implementer/Fixer → Security
Auditor → QA/Playtester → Devil's Advocate → Design Critic), each
finding real, independently-verifiable issues rather than re-covering
the same ground. Full detail lives in the conversation; this is the
durable summary.

- **Found and fixed: `src/redactor.py` was never actually called.**
  Built to spec, unit-tested in isolation, and never wired into
  `processor.py` - every summary this project had ever produced went out
  unredacted, directly contradicting CLAUDE.md's own Security section.
  Now wired in before storage/indexing/embedding; sessions crossing the
  redaction threshold get marked `needs_review` and skip
  search_index/ChromaDB, matching the documented behavior. Also removed
  a duplicate, drifted copy of the `redaction_log` schema that lived in
  `redactor.py` itself instead of storage.py's canonical one.
- **Found and fixed: unbounded relevance score.** `embedder.py` computed
  `1 - distance` assuming ChromaDB's cosine distance ranges [0,1]; it
  actually ranges [0,2] (distance = 1 - similarity, similarity in
  [-1,1]). Real search results were showing 240%+ "relevance" in the UI.
  Correct normalization is `1 - distance/2`, clamped to [0,1].
- **Found and fixed (CRITICAL): the entire API was reachable with zero
  credentials except `/setup` and `/sync`.** Confirmed live via a bare
  `curl` call with no auth headers at all - `/search` returned full
  conversation history, `/costs` returned real spend data,
  `/review/reprocess` could trigger real API charges. The "Unlock
  Device" screen was purely client-side (a localStorage flag), never
  enforced server-side, despite the server binding `0.0.0.0` by design
  for LAN/phone access. Fixed with a real server-side session: `/setup`
  issues a short-lived (30 min), in-memory, HttpOnly cookie only after
  real passphrase+TOTP verification; every route except `GET /`,
  `GET /src/*`, and `POST /setup` now requires it; new `POST /logout`
  actually invalidates it server-side (Lock used to only clear
  client-side storage). 6 regression tests cover the gate directly.
- **Devil's Advocate found 2 real gaps in that same fix**: `/setup` had
  no rate limiting (Argon2id makes each guess expensive, not bounded in
  count - added a 5-attempt/15-min per-IP lockout, verified live), and
  the session cookie had no `Secure` flag, meaning it crossed the LAN in
  cleartext - the exact threat model the fix was built to close. Fixed
  with `secure=request.is_secure` (tightens automatically once TLS is
  added). See the TLS entry below for the real fix that landed on
  desktop the same day.
- **Devil's Advocate also flagged, correctly**: every summary pushed to
  `claude-search-data` *before* the redaction fix landed is still
  unredacted in that repo's git history. Decision with the user: leave
  git history alone (private repo, Fernet-encrypted, real risk is low,
  and a history rewrite right now risks the not-yet-migrated desktop's
  clone) and instead reprocess existing sessions through the now-fixed
  pipeline. Ran for real: 56 of 62 succeeded; the other 6 aren't
  failures, they're `not_found` (5 real sessions with no readable raw
  file - the same pre-existing gap `/health` has flagged all along - plus
  the known `test-session-001` fixture row). Pushed live to GitHub
  (`changesets/nobody174-laptop/...`), confirmed on `origin/main`. This
  decision — leave history alone — still stands; see BACKLOG.md.
- **QA/Playtester found 2 real friction points** in the new session-gate
  UX: a session expiring mid-use silently kicked the user back to
  Unlock with zero explanation (now shows an actual "session expired"
  message), and the import dropzone's success message told users to run
  `cli.py collect` even though clicking Sync now auto-collects too.
- **Design Critic**: result cards showed six roughly-equal-weight
  signals (title, relevance %, tldr, source/device, date, top-pattern)
  on a screen whose one job is "find it in a few seconds." De-emphasized
  relevance %/top-pattern (muted instead of accent-colored) so
  title+tldr read as the actual primary scan targets.
- **Also added, separately**: `python-dotenv` was a listed dependency
  since day one but `load_dotenv()` was never actually called anywhere -
  every prior run only worked because a human/agent manually exported
  `.env` into the shell first. Fixed in all three entry points; added
  `start_server.bat` for a genuine double-click launch (which is what
  actually needed the fix, since a double-clicked `.bat` has no shell
  environment to inherit from).
- **Process note for future reviews**: the roles found real,
  independently-verifiable things at each step - this wasn't
  review-theater. The one place effort was consciously *not* spent: a
  full TLS/HTTPS setup, correctly identified as a real design decision
  (cert management, phone trust prompts) rather than something to guess
  at inside a fix-the-gaps pass. That design work landed the same day —
  see below.
- **Project Reviewer round 2**: all 4 round-1 gaps verified genuinely
  closed by direct code inspection. One new low-severity note: the
  session-gate's two in-memory maps (`_sessions`, `_setup_attempts`)
  only pruned stale entries lazily, never proactively - negligible at
  personal scale, but real. (Fixed later the same day on desktop — see
  below.)

---

## 2026-08-05 (desktop) — migration, TLS, and closing the round-2 punch list

The laptop's 2026-08-05 review cascade (above) left a documented
action-item list for the desktop machine to pick up. All of it closed
out the same day, plus a few things a fresh Project Reviewer checkpoint
found after.

- **Desktop migrated onto the CRDT schema/sync protocol.** `git pull`
  the code repo first (old code can't read the new changeset-shaped
  sync transport at all), backed up `library.db`, ran `init_db()` to
  migrate schema v1→v2, then a full bidirectional sync. Both devices
  merged into one library: 122 sessions total (0 conflicts), collecting
  60 new sessions from this machine's VS Code/Cowork sources along the
  way.
- **TLS added, closing the "No TLS on server.py" Known Blocker.**
  `server.py` now serves HTTPS by default via a self-signed cert
  (`~/.claude-search-library/certs/`, 10-year validity, SAN covers
  `localhost`/`127.0.0.1`/the LAN IP so phone access doesn't hit a
  hostname mismatch). `--no-tls` opts back into plain HTTP for
  pure-localhost dev. The session cookie's existing
  `secure=request.is_secure` logic now actually sets `Secure` in the
  normal case, since requests genuinely arrive over HTTPS. There's no
  way to make a self-signed cert trusted for arbitrary public users —
  that needs a real domain + a CA like Let's Encrypt, a different
  deployment model — so this is documented in README.md's Security
  section as expected behavior, not fixed further.
- **114 stale pre-CRDT sync files deleted** from `claude-search-data`'s
  `encrypted_sessions/`/`encrypted_summaries/` directories, after
  confirming nothing in `sync.py` reads them anymore — fully superseded
  by the `changesets/` stream.
- **`_sessions`/`_setup_attempts` unbounded growth fixed** (the round-2
  low-severity note above): both maps now get swept every 10 minutes on
  request, instead of only pruning lazily on next access to that same
  token/IP.
- **Real bug found and fixed: `verify_archive()`'s raw-file check was
  badly noisy in a multi-device world.** `raw_file_path` is a
  device-local absolute path that rides along in the CRDT-synced
  `sessions` table, so any session pulled from another device always
  looked like "raw file missing" on every other device, forever — not a
  real integrity gap, a false positive baked into multi-device sync
  itself. Fixed to only flag paths under the current device's own home
  directory; other-device paths now tracked separately as
  `foreign_device_raw_paths`. Verified against the real 122-session
  library: `raw_chat_files_missing` dropped from 56 (noise) to 0, and
  the "no readable raw file" warning dropped from 61 to the real number
  (5) — matching the already-known, already-accepted BACKLOG.md finding
  instead of drowning it in sync noise.
- **Second real bug found while testing the above: the JSONL durability
  mirror path was hardcoded instead of derived from `db_path`.**
  `export_summaries_to_jsonl()`/`restore_summaries_from_jsonl()`/
  `verify_archive()`'s JSONL check all pointed at a single fixed
  `~/.claude-search-library/...` path regardless of which database a
  `Storage` instance actually pointed at — meaning every test using an
  isolated `:memory:` database silently read/wrote whatever real mirror
  file happened to already exist on the machine running the tests. This
  is exactly the pre-existing test-isolation bug flagged (not fixed) in
  the 2026-08-05 cr-sqlite integration entry below. Fixed:
  `_default_jsonl_path()` now derives the mirror location from
  `db_path`'s directory (reproduces the real path exactly for the
  default profile; returns `None` for `:memory:` instead of silently
  reading unrelated real data).
- **A Project Reviewer checkpoint** (run after the above fixes, per the
  project's own AI-role workflow convention — a §3 periodic health
  check, not a full pre-release gauntlet) confirmed 327 tests passing,
  no TLS loose ends anywhere in tests or the web UI, and no other
  hardcoded-path-instead-of-derived-from-db_path bugs elsewhere in the
  codebase. It did find one more real (if dormant) instance of the same
  device-local-path pattern: **`summary_file_path`** has the identical
  issue as `raw_file_path` — same table, same CRDT sync, same
  device-local nature — just not yet triggering visible noise since
  nothing previously checked it for cross-device validity. Fixed the
  same way, folded into the existing raw-file-check rather than adding
  a new numbered check. Verified clean against the real library
  (`summary_sidecar_files_missing: 0`). Tests: 329 passing.
- **Personal location/device details scrubbed from public-facing docs**
  (README.md, SPEC.md, CLAUDE.md, `tasks/`) — a real town name, "cabin"
  references, and hardcoded example IPs generalized, since this repo may
  go public later. Git history still contains the original town-name
  mention (from the initial commit) — reviewed and deliberately left
  alone (low exposure, not worth a destructive history rewrite for a
  single generic mention).
- **`start_server.bat` finalized** as a simple visible-console-window
  launcher (double-click to start, close the window or Ctrl+C to stop)
  after trying and reverting a detached-process + separate
  `stop_server.bat` version — simpler, and avoids the self-signed-cert
  HTTPS warning being mistaken for something broken by a background
  process with no visible output.
- **This file (CHANGELOG.md), plus BACKLOG.md, were split out of
  ROADMAP.md and CLAUDE.md's "Session log" sections the same day** —
  ROADMAP.md had drifted into acting as a changelog/backlog/roadmap all
  at once; this is the fix.

---

## 2026-08-05 — real cr-sqlite CRDT integration

**Trigger: the user is about to genuinely run two devices concurrently
(desktop + a laptop, both real machines, both in active use) for the
first time.** Until now cr-sqlite had never been installed on any
device - `sessions.py`'s conflict resolution was entirely the
hand-written whole-row Last-Write-Wins fallback described in `sync.py`'s
docstrings. That's adequate for "one device at a time," but with two
devices genuinely concurrent, a real conflict (both devices editing the
same session between syncs) would silently discard one device's entire
edit, even a change to a completely unrelated column. Decided, with the
user, that this was worth fixing properly rather than documenting
around, given real usage was about to start.

- **Windows load error was a real, already-fixed upstream bug** (GitHub
  issue vlcn-io/cr-sqlite#286, "Belirtilen modül bulunamadı" / "The
  specified module could not be found") - confirmed via the issue
  thread that a Windows-specific rebuild fixed it; the current release
  (v0.16.3) works. Vendored `crsqlite-win-x86_64.zip`'s `crsqlite.dll`
  into `vendor/cr-sqlite/` (loaded by explicit path, not by bare name -
  see `storage._CR_SQLITE_EXTENSION_PATH`, since bare-name loading
  depends on cwd/shared-library search path, unreliable across how this
  app gets launched).
- **Proved the actual point works before investing in the full
  integration**: an isolated two-database test where "device A" and
  "device B" each edit a *different column* of the *same row* without
  syncing in between, then exchange changesets - both edits survived and
  both devices converged. This is exactly the scenario the old
  whole-row LWW fallback would have silently lost data on.
- **Real schema constraints found and fixed** (cr-sqlite's own
  `crsql_as_crr()` validation, not guessed): CRR tables need an explicit
  `NOT NULL` on primary keys (bare `TEXT PRIMARY KEY` isn't enough in
  SQLite); disallow *checked* foreign keys (replicated changesets can
  legitimately arrive out of order - dropped `summaries.session_id`'s
  FK to `sessions.id`, integrity now enforced at the application layer,
  same as callers already did); disallow any unique index besides the
  primary key (dropped `content_hash TEXT UNIQUE` - duplicate detection
  was already done in application code before every insert, so this
  was pure defense-in-depth, not load-bearing); every `NOT NULL` column
  needs a `DEFAULT` (schema forwards/backwards compatibility across
  devices on different app versions).
- **`sync.py`'s push/pull rewritten**: `sessions`/`summaries` now
  exchange real `crsql_changes` changesets (one encrypted file per push,
  per device, named by the `db_version` it covers) instead of one
  whole-row file per session - real per-column CRDT merge on pull
  (`INSERT INTO crsql_changes`) replaces the hand-written LWW
  comparison entirely. Raw chat files stay on the old per-session file
  transport (unrelated to the SQL schema). One non-obvious real bug hit
  and fixed while wiring this up: cr-sqlite's `site_id` column is never
  `NULL` for local writes (always populated with the local site's own
  ID) - the initial filter (`WHERE site_id IS NULL`) to mean "changes I
  originated" was simply wrong and silently produced empty changesets;
  the correct predicate is `site_id = crsql_site_id()`.
- **Found and fixed a second, unrelated real bug via genuine two-device
  E2E testing** (a real git remote, two real separate databases, no
  mocking): `_update_device_metadata()` writes `sync_metadata.json`
  straight to the working tree without committing it. Harmless if a
  push follows immediately (push's own commit picks it up), but calling
  `pull_from_github()` twice in a row with no intervening push - a
  completely normal thing to do - left a real uncommitted change that
  made the second `git pull` fail outright ("local changes would be
  overwritten by merge"). Fixed by discarding that one bookkeeping
  file's working-tree changes immediately before every pull (safe: it's
  pure local metadata about to be rewritten by that same pull's own
  `_update_device_metadata()` call anyway).
- **Full test suite updated to match**, not left broken: rewrote every
  affected `tests/test_sync.py` test around the new changeset shape
  (real changesets generated via a genuine second `Storage` instance
  standing in for "the other device," not hand-crafted - `pk` is an
  internally-encoded binary blob, not safe to fabricate by hand), added
  a dedicated concurrent-different-column-edit regression test, and
  fixed one incidental test breakage in `tests/test_cli.py` from
  earlier the same week's JSONL-auto-export change. 315/316 tests pass;
  the one remaining failure was a pre-existing, unrelated test-isolation
  bug (`verify_archive()`'s JSONL check hardcoded the real
  `~/.claude-search-library/...` path instead of respecting the test's
  isolated DB) - flagged at the time, fixed for real on 2026-08-05
  (desktop), see above.
- **Verified end-to-end for real**, not just unit-level: two genuinely
  separate local databases, a real bare git repo standing in for
  GitHub, real `crypto.encrypt_data`/`decrypt_data`, real cr-sqlite -
  "desktop" pushed a session, "laptop" cloned fresh and pulled it
  correctly, then both devices independently edited different fields of
  the same session without syncing, and after syncing both edits
  survived and both devices converged to an identical final state.
- **Real data has not been migrated yet** as of this log entry - this
  session shipped the code only. Migration plan (backup, convert
  locally, verify, first real push, verify on GitHub) agreed with the
  user; pilot planned on the laptop first (lower-stakes, easily
  re-collectible data) before repeating on desktop.
- **Update, same day**: the laptop migration ran for real - backed up
  `claude_search.db`, converted locally (61 sessions preserved exactly,
  1,708 real changeset rows retroactively captured), verified healthy,
  pushed for real (`changesets/nobody174-laptop/5.enc` confirmed live on
  `origin/main`). Found and fixed one more real bug during the live
  migration itself: SQLite's `ALTER TABLE RENAME` auto-rewrites
  `REFERENCES` clauses in *other* tables pointing at the renamed table,
  which silently broke `search_index`/`redaction_log`/`api_costs` until
  repaired losslessly. Desktop migration still pending - user hasn't
  reached the desktop machine yet.

---

## 2026-08-04, continued — web UI audit + self-serve tooling + 2 real bugs

**Trigger: a Claude-Desktop-driven Chrome audit of the web UI (`report.md`)
surfaced real functional bugs, not just polish.** Worked through the
prioritized list, then added the backlog feature suggestions the user
approved, then found and fixed two more serious bugs via actual use of
the app (not from the report) - one of which the audit itself later
confirmed was gone.

- **Root-cause fix for the 7 unindexed sessions**: `processor.py`'s
  `_build_narrative()` handed the model a raw, undelimited
  `[user]/[assistant]` transcript. On certain sessions (long
  design-planning chats, or ones ending on a casual assistant turn) the
  model got pulled into continuing the conversation in character instead
  of summarizing it - producing either empty output or the wrong JSON
  entirely. Fixed by wrapping the transcript in explicit
  `<transcript_to_analyze>` delimiters plus an explicit
  "don't participate" instruction - and critically, truncating the raw
  transcript *before* wrapping it, not after (an initial version of the
  fix truncated post-wrap, silently chopping the closing instruction off
  on long sessions). Verified against all 7 known-bad sessions before
  reprocessing for real.
- **Web UI fixes from the audit**: Tags filter debounce (was firing one
  API call per keystroke), a "no strong matches" state below 20%
  relevance instead of showing weak results as normal cards, a ⚠ badge
  for sessions whose summary indicates failed parsing, session-modal
  Escape/backdrop-click dismissal, a tooltip on the `archive: …` footer
  chip surfacing real error detail, and the JSONL backup mirror actually
  gets generated now (was built but never run) and auto-refreshes after
  every `process` call. Two audit findings turned out to be false
  positives on investigation, not bugs: "duplicate CDN scripts" (unpkg's
  unversioned URLs redirect server-side, showing as two network-panel
  entries for one script tag) and the `?`/"2. " title corruption (traced
  to the raw exported source file itself, upstream of our pipeline,
  before our code ever touches it - unrecoverable on our end).
- **Backlog features shipped** (health banner, self-serve repair panel,
  related-sessions panel, cost date-range breakdown in the UI, Lock
  onboarding tooltip) - see README.md's "Web UI features" section and
  server.py's `/review`, `/review/reprocess`, `/session/<id>/related`
  endpoints for the concrete shape. Along the way, found `getHealth()`
  was silently discarding the real error/warning payload on every
  unhealthy check, because `/health` intentionally returns HTTP 503 and
  the generic `request()` helper throws away the body on any non-2xx
  response - every existing `.catch(() => null)` around it (including
  the health badge that already existed on the Sync page) was quietly
  getting `null` instead of real detail. Fixed centrally in `getHealth()`.
- **Real bug #1: the sync "Working…" hang, found via the user's own
  real click-through, not the audit.** `/sync` runs a full local
  collection pass before ever touching credentials or Git.
  `collect_from_claude_desktop()` was decoding *every* historical,
  LevelDB-uncompacted version of the `react-query-cache` key - LevelDB is
  append-only, so old overwritten versions of the same key physically
  stick around until compaction runs - and each stale version triggered
  an expensive failed blob lookup (~0.65s × 3000+ stale records observed
  = 30+ minutes). Fixed by deduping to the max-`seq` (LevelDB's own write
  sequence number) record per physical key *before* ever calling the
  decoder - cut a real run from a 30+ minute de facto hang to under a
  second, and fixed a correctness bug too (was reading garbage historical
  state, not current data).
- **Real bug #2: the permanently-stuck "unhealthy" archive status.**
  Root-caused to a bug in `store_session_with_hash()`: when the same
  conversation (same id) legitimately changed after first collection - a
  live conversation still growing, a re-export overwriting the raw file,
  or the claude-desktop collector catching a partial/cached rendering
  before a later full-export brings in the complete version - the
  function only handled two cases (identical content-hash → skip as
  duplicate; new id → insert), so a same-id-different-hash case hit a
  raw `sqlite3.IntegrityError: UNIQUE constraint failed: sessions.id`
  instead of updating the existing row. Worse, this wasn't just a noisy
  log line: it also meant `verify_archive()`'s content-hash check could
  never self-heal - the stale original hash stayed forever, so the
  archive stayed permanently "unhealthy" no matter how many times the
  affected session was collected, synced, or reprocessed. **Fixed
  2026-08-04**: `store_session_with_hash()` now detects an existing row
  with the same id but a different hash, updates it in place (refreshing
  `content_hash`/`title`/`updated_at`/message counts/`raw_file_path`)
  and resets `status` to `"new"` so it flows back through the normal
  (re)processing queue, instead of failing the insert. `run_collection()`
  now reports an `"updated"` count alongside `"new"`. Verified against
  the real affected sessions: `/health` went from permanently
  `healthy: false` to `healthy: true` immediately after a normal
  collect, with zero manual DB surgery. Also broadened the self-serve
  repair panel (`/review`+`/review/reprocess`) to cover both
  `needs_review` and plain `new` sessions, since this fix's "reset to
  new" behavior needed a self-serve path too, not just `needs_review`
  recovery.
- **A `test-session-001` fixture row was found mixed into the real
  61-session dataset** (source `claude-ai`, a fake "Debugging a Python
  async race condition" session) - flagged to the user, deliberately not
  touched; deleting it is their call (see BACKLOG.md).
- **Verification note**: real browser testing (Playwright, headed
  Chrome with remote debugging, since no `chromium-cli` was available in
  this environment) was used for the sync-hang and search-freeze
  investigations. The app's Unlock Device passphrase+TOTP gate was never
  bypassed - for the search-freeze report, the user unlocked a visible
  Chrome window themselves and Claude Code reconnected via CDP afterward
  to drive the already-unlocked session, rather than being given or
  guessing the passphrase.
- **A reported "search freeze/hang" (Claude Desktop audit, round 3) did
  not reproduce** under two independent real, credentialed 35-second
  monitored test runs (continuous JS eval every second, all under 10ms,
  zero console errors). Left unresolved/unexplained rather than
  fabricating a fix for a bug that couldn't be found - round 4 of the
  same audit confirmed it did not reproduce on their end either.

---

## 2026-08-03 to 2026-08-04

**All 5 original roadmap items shipped this stretch (#1-#5), plus the
Claude desktop app / claude.ai chat capture project (new, solved) and
web UI polish. The system is now fully working end-to-end with real
personal data, not just tests.**

- **#1-#5 shipped**: PowerShell orchestration, cost reporting
  (`cli.py costs`), Markdown export, Web Chat Import (rewritten - the
  original plan was a ToS-risky scraping approach, ruled out during
  research; built `src/claude_export_import.py` for the official
  Settings → Export Data flow instead), retention/pruning
  (`cli.py prune`).
- **New collectors beyond the original roadmap, all built from real
  local app data, never claude.ai's private API:**
  - `collect_from_claude_code()` — Claude Code's own
    `~/.claude/projects/*.jsonl` transcripts.
  - `collect_from_claude_desktop()` — the desktop app's local IndexedDB
    cache. Required real reverse-engineering (Chromium's Snappy
    compression wasn't being decompressed before V8 deserialization -
    full investigation below, under "Claude desktop app chat capture").
    Only captures conversations actually opened in the desktop app
    recently, not full history.
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
  or mobile. The manual export (Web Chat Import) is not fully retired,
  just downgraded to an occasional safety-net for those.
- **Not yet fixed at the time** (real but lower priority): when the same
  conversation UUID was collected by two different sources with
  different content, `store_session_with_hash()` crashed with a raw
  `sqlite3.IntegrityError` instead of updating in place. Worked around
  by hand once; fixed for real 2026-08-04 (see above).

### Claude desktop app / claude.ai chat capture — the full investigation (solved 2026-08-03)

- **Problem**: the user has "a lot of" real conversations in the Claude
  desktop app (claude.ai account) that were NOT in the library. Only
  Claude Code CLI sessions were collected automatically at the time. The
  user explicitly did not want a manual export→zip→email→unzip→import
  workflow as an ongoing habit (the Web Chat Import feature exists for a
  one-time/occasional catch-up, but that's not automatic capture).
- Investigated (2026-08-03, via background research agent) whether the
  desktop app's own local cache could be read directly — same category
  of solution as the local-file approach used for Claude Code, NOT
  a ToS-violating claude.ai-private-API-scraping path (see BACKLOG.md's
  "iOS chat capture" — that path was researched and ruled out
  separately). This is a fundamentally different, legitimate approach:
  reading a local cache file an app *the user runs* wrote to *their own
  disk*.
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
- **Round 2 findings (2026-08-03, continued research session):**
  - **Real bug found and fixed** in `ccl_chromium_reader`'s V8
    `Deserializer._read_object_internal`: per V8's real
    `SerializationTag`/`ValueSerializer` semantics
    (v8/src/objects/value-serializer.cc), every referenceable object
    (strings, JS objects, arrays, dates, regex, maps/sets, wrapped
    primitives) gets a sequential ID as it's written, so later identical
    *object instances* can be written as a compact `kObjectReference`
    back-pointer. The library only registers a few of these types into
    its back-reference table — never plain strings
    (`kUtf8String`/`kOneByteString`/`kTwoByteString`). Patched
    `_read_object_internal` to also register string values, matching
    real V8 `AssignId` behavior. This is a legitimate, verified fix
    (confirmed against the spec, not guessed), but turned out **not** to
    be the cause of the real blob's corruption (see below) — repeated
    *string values* from separate object literals are apparently not
    deduped by V8 in the observed data at all (see next point), so the
    back-reference table never actually gets hit for them.
  - **Built a real ground-truth reference sample** to test against,
    per the user's explicit request, rather than guessing further:
    installed Chrome is present at
    `C:\Program Files\Google\Chrome\Application\chrome.exe`; no
    `playwright`/`selenium` in the venv, so instead launched
    `chrome.exe --headless=new` directly against a throwaway local HTML
    page (served via `python -m http.server` so it gets a stable
    `http://localhost` origin — `file://` origins are unreliable/opaque
    for IndexedDB) that writes a realistic TanStack Query
    `PersistedClient`-shaped object (`{buster, timestamp, clientState:
    {mutations, queries}}`, with `queries` containing 15 entries sharing
    identical property names, plus `undefined`-valued fields, mimicking
    a real mutation-cache entry) into a fresh `indexedDB.open()` +
    `transaction.objectStore.put()`. Closed Chrome, copied the resulting
    LevelDB store (same copy-first discipline as the real store), and
    decoded it.
  - **Result: all 3 reference variants (1 query; 15 repeated-key
    queries; 15 queries + a mutation with `undefined` fields) decoded
    perfectly with the *unpatched, stock* library** — no crash, no
    corruption, `mutations`/`state`/`data` keys all read correctly.
    Inspecting the raw reference bytes directly confirmed V8 does **not**
    back-reference the repeated `"queryKey"` property-name string across
    the 15 query objects (it appears as literal bytes twice at different
    offsets, not as a `kObjectReference`) — meaning the back-reference
    theory, while a real bug worth having fixed, is **not** what's
    breaking the real blob. Something about the *actual* live cached
    data differs from this reference in a way not yet identified —
    candidates not yet tested: real `Date` objects (vs. plain numbers)
    for timestamps, very long string values (full conversation text),
    deeply nested/large arrays of real message objects, or a value type
    the library marks `_not_implemented` (`kError`,
    `kSharedArrayBuffer`, `kArrayBufferTransfer`, `kWasmModuleTransfer`)
    appearing somewhere in a mutation's `error`/`data` field from a
    failed request.
  - Manual byte-level tracing of the real blob (cross-referenced tag by
    tag against `SerializationTag`) shows the corruption is
    *deterministic and reproducible* — diffed two independent fresh
    copies of the live 715KB blob taken minutes apart and only 4 bytes
    differed (all within the unrelated `timestamp` field), ruling out
    torn/partial-read races as the cause. The corrupted bytes
    consistently decode the first 3-4 characters of an expected key
    (`"sta"` for what should be `"state"`, `"muta"` for what should be
    `"mutations"`) correctly, then diverge into non-printable bytes in a
    way that isn't explained by any length-prefix or offset
    misreading — the wire format's length varints are unambiguous
    (single byte, high bit clear) at every point checked.
  - **Status at this point: genuinely unresolved wall**, not abandoned
    prematurely — a real fix was shipped (string back-reference
    registration), a real ground-truth methodology was built and used
    (Chrome headless + fresh IndexedDB writes, copy-first, byte-diffed
    for corruption vs. race conditions), and the specific failure was
    not reproduced despite 3 escalating-complexity attempts. No
    `collect_from_claude_desktop()` was shipped yet since real
    conversation titles/messages were never successfully extracted —
    only account metadata (a real `tagged_id`/`uuid` matching the user's
    account) was confirmed recoverable so far.
  - **Round 3 findings (same session, continued after round 2):**
    - Built a 4th reference sample adding `Date` objects, ~2KB repeated
      text (mimicking real message length), and a real `Error` object for
      one query's `error` field. **This one reproduced the corruption** —
      first controlled, fully reproducible failure (previous 3 reference
      samples all decoded perfectly). Crucially: this sample is small
      (7.4KB, in-place, not blob-spilled) — much easier to iterate on than
      the real 715KB blob.
    - Diagnosed a **second, independent, real bug**: the envelope
      immediately after the outer `blink_type_tag + blink_version` header
      contains a fixed 13-byte block before the real V8 payload starts,
      but *only* when Chromium picks `blink_version == 17` for this
      document (both the real blob and this new large-enough reference
      sample use version 17; the earlier small reference samples that
      decoded cleanly all used `blink_version == 21`, which the library
      already handles via its `BlinkTrailer` trailer-skip code path).
      `ccl_chromium_reader` only attempts to skip a trailer when
      `blink_version >= BlinkTrailer.MIN_WIRE_FORMAT_VERSION_FOR_TRAILER`
      (21) — version-17 documents never get this treatment, so the reader
      starts trying to parse V8 tags 13 bytes too early, in the middle of
      what is actually still header material. **Fix (verified working):**
      detect this positionally instead of by version — if the byte right
      after the version varint isn't `0xFF` (a fresh V8 header) but the
      byte 13 positions later *is* `0xFF`, skip the 13-byte block
      unconditionally. Confirmed this correctly realigns parsing to the
      real V8 header (`ff 10 6f 22 06 "buster"...`) in both the reference
      sample and the real blob.
    - With that envelope fix + the round-2 string-back-reference fix
      applied together, parsing gets much further (correctly reads
      `buster`, `timestamp`, `clientState`, into the nested `clientState`
      object) but **still corrupts at exactly the same logical point**:
      the `clientState` object's *first* property key, which should be
      `"mutations"` (declared length 9, first 4 bytes `"muta"` read
      correctly, remaining 5 bytes are non-printable garbage) — this now
      reproduces byte-for-byte-analogous corruption in the small 7.4KB
      reference sample, at the exact same structural position (2nd level
      of object nesting) as the real 715KB blob, confirming it's the same
      root cause and not an artifact of blob size.
    - This ruled out several theories conclusively: not a
      back-reference/object-ID issue (a string's own raw bytes are
      copied directly once its length is known, unaffected by the
      back-reference table); not size/blob-related (reproduces in a
      7.4KB in-place value too); correlated specifically with
      `blink_version == 17` and with being the *first key of a nested
      (non-root) object*.
    - At this point, the 2 real fixes found so far (string
      back-reference registration, the 13-byte version-17 envelope skip)
      existed only in session scratch scripts, not yet upstreamed into
      the venv's installed copy of `ccl_chromium_reader` — noted at the
      time as needing reapplication or an upstream submission to
      github.com/obsidianforensics/ccl_chrome_indexeddb if a future
      session picked this back up. Superseded by round 4's actual root
      cause below before that ever became necessary.
  - **Root cause found and SOLVED (round 4, same session):**
    - The "blink_version == 17" and "13-byte prelude" observations in
      round 3 were on the right track but mis-identified. Checked
      `cclgroupltd/ccl_chromium_reader`'s upstream GitHub issues directly
      (the actual upstream — round 2/3 had been checking
      `obsidianforensics/ccl_chrome_indexeddb`, a stale fork/mirror; the
      real upstream is `cclgroupltd/ccl_chromium_reader`, which
      `pip install git+https://github.com/obsidianforensics/...` actually
      installs the package `ccl_chromium_reader` from, confusingly). Open
      issue **#44**, "IndexedDB value decode fails on Snappy-compressed SSV
      (wrapper command 0x02)", is exactly this bug, filed independently and
      describing the precise byte pattern found by hand: Chromium
      prefixes a value with `0xFF` (Blink tag), then `0x11`
      (`kRequiresProcessingSSVPseudoVersion` — a *sentinel*, not a real wire
      version — this is what round 3 had been misreading as "blink_version
      17" the whole time, since 0x11 = 17 decimal), then a **command byte**:
      `0x01` = `kReplaceWithBlob` (already handled), `0x02` =
      `kCompressedWithSnappy` (**not handled at all** by the installed
      version of the library — falls through to the raw/no-op path and
      hands still-Snappy-compressed bytes to the V8 deserializer). What
      round 3 mis-identified as "corrupted" 4-good-then-garbage string
      bytes were genuine, un-garbled Snappy-compressed bytes the whole
      time — Snappy's literal-run/back-reference LZ77 structure produces
      exactly that "few readable characters then binary" pattern by
      design, on *any* input, which is why it looked so consistently
      "almost-textual." Chromium compresses any IndexedDB value once it
      crosses a size threshold — not a rare edge case for a react-query
      cache holding full conversation histories, but the *common* path.
    - Confirmed against Chromium's real V8 source
      (`v8/src/objects/value-serializer.cc`/`value-deserializer.cc` via
      `gh`/WebFetch) that V8's actual `kLatestVersion` is 16 (not 17/21 —
      those were always the separate Blink-level wrapper version/sentinel,
      confirmed by the real inner V8 header reading `0xFF 0x10` = version
      16 in every sample once the outer wrapper is stripped correctly) and
      that V8 does **not** register plain strings in its back-reference
      table (`ReadObjectInternal`'s per-tag dispatch only calls
      `AddObjectWithID` for objects/arrays/dates/maps/sets/wrapped
      primitives/etc, never for `kUtf8String`/`kOneByteString`/
      `kTwoByteString`) — meaning the round-2 "string back-reference" fix,
      while harmless, was solving a bug that doesn't actually occur in
      practice; the real bug was the Snappy command byte the whole time.
    - **Fix implemented directly** in `src/collector.py`
      (`_idb_ssv_decode()`), rather than patching the installed library in
      place: recursively unwraps `0xFF <version>` envelopes, handling the
      `0x11` sentinel's `0x01`/`0x02` commands (fetch-blob-then-recurse /
      Snappy-decompress-then-recurse via the already-a-dependency
      `ccl_simplesnappy.decompress()`), and falls through to the V8
      deserializer (with the correct 13-byte trailer skip for genuine
      wire versions `>= 21`) once a real payload is reached.
    - **Verified against real data**: decoded all 360 live
      `react-query-cache` records in the real (copied, read-only)
      IndexedDB store with **zero failures** (previously: corrupted or
      crashed on every record above the trivial/empty-cache size). Found
      real `chat_conversation_list` queries with actual conversation
      titles (e.g. "Dark tech UI design for search library app", "Unified
      Claude chat library and search system", ...) and a
      `chat_conversation_tree` query with a **complete real conversation**:
      title, uuid, and full `chat_messages` array with real human/assistant
      turns, per-message timestamps, and content blocks (including
      `thinking` blocks, correctly excluded from extracted text — same
      convention as `collect_from_claude_code`'s `_extract_text_content`).
    - **Real limitation, not a bug**: only `chat_conversation_tree`
      entries carry full message history, and those are only cached for
      conversations the user has actually *opened* in the desktop app
      while the cache held them (list-view queries only carry
      title/summary/timestamps, not messages). This is an incremental,
      "catches what you've been actively using" source — not a substitute
      for the official Settings → Export Data full-history catch-up (Web
      Chat Import).
    - **Shipped**: `collect_from_claude_desktop()` in `src/collector.py`,
      registered as source `"claude-desktop"` in `src/orchestration.py`'s
      `SOURCES` and `_collector_and_arg()`, added to `cli.py collect
      --source`'s choices. Dependency `ccl_chromium_reader` (installed via
      `pip install git+https://github.com/obsidianforensics/ccl_chrome_indexeddb.git`
      — not on PyPI under any documented name) added to `requirements.txt`.
      Tests in `tests/test_collector_claude_desktop.py` cover the
      conversion/normalization logic against a fixture shaped like real
      decoded data, plus graceful-empty-list behavior when the store isn't
      present — the LevelDB/Snappy/V8-decoding path itself isn't covered
      by an automated fixture (impractical to construct byte-exact
      Chromium LevelDB+Snappy+V8 wire data by hand); it was verified
      directly against the real local store instead (see above).
- **Scope clarification (2026-08-04, confirmed with real usage)**: the
  collector only ever reads the **Windows desktop app's own local
  Chromium profile** — it has no visibility into conversations opened
  only via a browser tab at claude.ai, or via mobile. Those remain
  fully dependent on the manual export (Web Chat Import). Practical
  implication: the manual export is not fully retired — it's now an
  occasional safety-net/catch-up (for browser-only or mobile-only
  chats, and for old conversations never reopened in the desktop app)
  rather than something needed after every session, as long as the
  user's day-to-day usage is mostly through the desktop app. A future
  idea, not yet started: apply the same local-cache-reading technique
  to a regular browser's own profile (Chrome/Edge's IndexedDB for
  claude.ai) to close this gap too — noted in BACKLOG.md.
- **`cli.py sync` now collects from every local source first by
  default** (2026-08-03, see the "Always collect from local sources
  before syncing" commit) — `sync`, the web UI's sync buttons, and
  `--watch` all grab fresh local data (including this collector's
  output) automatically before pushing, so a user no longer needs to
  remember a separate `collect` step before syncing from a device.
- **Same-id-different-hash bug: FIXED (2026-08-04)**. See the entry
  above under "2026-08-04, continued" for the full writeup — this is
  the bug flagged here as not-yet-fixed at the time.

---

## 2026-08-02

- **Join-device GUI popup + sync dashboard shipped:** join-device
  passphrase step never actually used the popup at all — fixed —
  `/sync` + `/import` REST endpoints, full web UI sync dashboard
  (health badge, Pull/Push/Sync Now buttons, drag-and-drop Claude.ai
  export import). Passphrase is now remembered per browser tab via
  sessionStorage after a successful sync — a fresh TOTP code is still
  required every time. Commits `6a870fc`, `062d44d`, `59e1333` on
  `origin/main`.
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
- **iOS chat capture researched and found unsolved** — official export
  is desktop/web only; unofficial claude.ai scrapers exist but violate
  Anthropic's ToS (real account-suspension risk, confirmed via dedicated
  research, not assumed); no iOS Share Sheet export hook exists either.

---

## 2026-08-01 — secure credential entry UI (GUI popup for passphrase + TOTP)

**Trigger: a real UX/automation gap hit while testing sync** —
`getpass.getpass()`/`input()` only work in a genuine interactive
terminal, so any automated caller (an agent driving the CLI, a
scheduled task, a non-interactive shell) had no way to supply a
passphrase or live TOTP code short of a plaintext `.env` workaround.

- **Shipped `src/auth_ui.py`**: a small, dark-themed Tkinter popup,
  GUI-first with a silent terminal fallback
  (`CLAUDE_SEARCH_NO_GUI_AUTH=1` forces terminal prompts instead, e.g.
  over SSH/headless). Runs entirely on the calling/main thread - an
  earlier background-thread version hit real, reproducible Tcl crashes
  (`Tcl_AsyncDelete: async handler deleted by the wrong thread`) on
  submit, confirmed via live testing. Has a hard timeout
  (`AUTH_UI_TIMEOUT_SECONDS`) so a stray invocation in an unattended
  context fails loudly instead of hanging forever - also confirmed via
  live testing, after an early version briefly hung during a pytest
  run before tests forced GUI auth off.
- **`src/crypto.py`'s `setup_device_first_time()`/
  `join_device_existing_setup()` now use the GUI-aware prompts.** QR
  codes stay as terminal ASCII art (no new Pillow dependency needed
  for that). Nothing entered in the popup is ever written to disk -
  values return to the caller in memory only, same as the terminal
  prompts they replace.
- **Tests never allow a real popup**: `test_crypto.py`'s autouse
  fixture forces GUI auth off; `test_auth_ui.py` exercises the real Tk
  submit/cancel/timeout paths via `root.after()` scheduling instead of
  waiting on a human click.
- The join-device flow's actual passphrase step didn't start using
  this popup until a follow-up fix on 2026-08-02 (see above) - this
  entry covers when the popup itself was built and wired into setup.
  See BACKLOG.md.
