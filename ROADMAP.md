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

## 9. Claude desktop app / claude.ai chat capture — SOLVED and shipped 2026-08-03 (HIGH)
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
  - **Status: genuinely unresolved wall**, not abandoned prematurely —
    a real fix was shipped (string back-reference registration), a real
    ground-truth methodology was built and used (Chrome headless +
    fresh IndexedDB writes, copy-first, byte-diffed for corruption vs.
    race conditions), and the specific failure was not reproduced
    despite 3 escalating-complexity attempts. No `collect_from_claude_desktop()`
    was shipped since real conversation titles/messages were never
    successfully extracted — only account metadata (a real
    `tagged_id`/`uuid` matching the user's account) was confirmed
    recoverable so far.
- **Round 3 findings (2026-08-03, same session, continued after round 2):**
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
  - **This rules out several theories conclusively:**
    - Not a back-reference/object-ID issue: a string's own raw bytes are
      copied directly once its length is known; nothing about the
      shared object-ID table can affect how a string's *own*, first-ever
      occurrence is read from disk. The corruption is in the raw bytes
      themselves as declared by the (unambiguous, single-byte, high-bit-
      clear) length prefix, not a misread offset.
    - Not size/blob-related: reproduces in a 7.4KB in-place value, not
      just the 715KB externally-blobbed one.
    - Correlates specifically with `blink_version == 17` (vs. 21 in
      every sample that decoded cleanly) and with being the *first key
      of a nested (non-root) object*. Root-level keys (`buster`,
      `timestamp`, `clientState`) always decode fine even in
      version-17 documents.
  - **Not yet resolved**: what specifically differs in how V8 encodes a
    *nested* object's first property under wire version 17 vs. 21.
    Current best guess, untested: version 17 may be a genuinely older
    SerializedScriptValue wire format that encodes nested-object
    property counts, hidden classes, or per-object memoization
    checkpoints differently than what `ccl_chromium_reader`'s
    `_read_js_object`/`_read_js_object_properties` assumes (which looks
    like it targets the newer/simpler format matching version-21
    documents). This would need direct cross-referencing against
    Chromium's `value-serializer.cc` `WriteJSObject`/version-history
    (specifically what changed between whatever wire version
    corresponds to 17 vs. 21) rather than further guess-and-check.
  - All of the above (2 real fixes: string back-reference registration,
    and the 13-byte version-17 envelope skip) are captured only in
    session scratch scripts so far, **not yet upstreamed into the venv's
    installed copy of `ccl_chromium_reader`** — if a future session
    wants to resume, both fixes need to be reapplied (they're
    documented in detail above) or submitted upstream to
    github.com/obsidianforensics/ccl_chrome_indexeddb.
- **Root cause found and SOLVED (2026-08-03, round 4, same session):**
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
    describing the precise byte pattern we'd found by hand: Chromium
    prefixes a value with `0xFF` (Blink tag), then `0x11`
    (`kRequiresProcessingSSVPseudoVersion` — a *sentinel*, not a real wire
    version — this is what we'd been misreading as "blink_version 17" the
    whole time, since 0x11 = 17 decimal), then a **command byte**: `0x01`
    = `kReplaceWithBlob` (already handled), `0x02` =
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
    for the official Settings → Export Data full-history catch-up
    (roadmap #4).
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
    fully dependent on the manual export (#4). Practical implication:
    the manual export is not fully retired by #9 — it's now an
    occasional safety-net/catch-up (for browser-only or mobile-only
    chats, and for old conversations never reopened in the desktop app)
    rather than something needed after every session, as long as the
    user's day-to-day usage is mostly through the desktop app. A future
    idea, not yet started: apply the same local-cache-reading technique
    to a regular browser's own profile (Chrome/Edge's IndexedDB for
    claude.ai) to close this gap too.
  - **`cli.py sync` now collects from every local source first by
    default** (2026-08-03, see the "Always collect from local sources
    before syncing" commit) — `sync`, the web UI's sync buttons, and
    `--watch` all grab fresh local data (including this collector's
    output) automatically before pushing, so a user no longer needs to
    remember a separate `collect` step before syncing from a device.
  - **Same-id-different-hash bug: FIXED (2026-08-04)**. When the *same*
    conversation (same id) legitimately changes after first collection -
    a live conversation that's still growing, a re-export overwriting the
    raw file, or the claude-desktop collector catching a partial/cached
    rendering before a later full-export brings in the complete version -
    `store_session_with_hash()` used to only handle two cases (identical
    content-hash → skip as duplicate; new id → insert). A
    same-id-different-hash case hit a raw `sqlite3.IntegrityError: UNIQUE
    constraint failed: sessions.id` instead of updating the existing row.
    Worse, this wasn't just a noisy log line: it also meant
    `verify_archive()`'s content-hash check could **never self-heal** -
    the stale original hash stayed forever, so the archive stayed
    permanently "unhealthy" no matter how many times the affected
    session was collected, synced, or reprocessed. Found via real usage
    (this exact session's own live transcript kept getting flagged).
    **Fix**: `store_session_with_hash()` now detects an existing row with
    the same id but a different hash, updates it in place (refreshing
    `content_hash`/`title`/`updated_at`/message counts/`raw_file_path`)
    and resets `status` to `"new"` so it flows back through the normal
    (re)processing queue, instead of failing the insert. `run_collection()`
    now reports an `"updated"` count alongside `"new"`. Verified against
    the real affected sessions: `/health` went from permanently
    `healthy: false` to `healthy: true` immediately after a normal
    collect, with zero manual DB surgery.

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
