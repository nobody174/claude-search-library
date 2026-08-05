# Roadmap

Real future features, not yet started. For small deferred decisions/known
edge cases see [BACKLOG.md](BACKLOG.md); for what's already shipped see
[CHANGELOG.md](CHANGELOG.md).

---

## Mobile TOTP re-provisioning (MEDIUM)
- Problem: setting up a *new* device (`--join-device`) already shows the
  TOTP QR code as part of the flow, but there's no way to get that QR
  back onto a phone later without redoing full device setup — e.g. a lost
  phone, a phone reset, or wanting to add Google Authenticator on a
  second phone. Moved here from BACKLOG.md 2026-08-06: this was
  previously "not currently worth fixing," but with the mobile access
  flow (README's "Access from Mobile" section) being a real, actively
  used part of the project, it's worth actually solving rather than
  leaving as permanent friction.
- `src/crypto.py` already derives/holds the TOTP secret for an
  already-set-up device — the missing piece is a way to re-display that
  secret's QR code on demand (a CLI command, e.g. `cli.py show-totp-qr`,
  or a button in the web UI's device settings) without re-running the
  full `--join-device` flow.
- Security note: re-displaying an existing TOTP secret is different from
  generating a new one — should require the same passphrase+TOTP
  confirmation `--join-device` already demands before showing anything,
  not be reachable without proving you already have access.

## Browser-profile chat capture (LOW — only if there's real demand)
- Problem: the Claude desktop app collector (`collect_from_claude_desktop()`,
  see CHANGELOG.md's full investigation) only reads the Windows desktop
  app's own local Chromium profile — it has no visibility into
  conversations opened only via a regular browser tab at claude.ai. The
  current user doesn't use claude.ai via browser (Claude Code + desktop
  app only), so this gap doesn't affect their own usage — but if this
  project goes public, other users' workflows may lean on the browser
  more, and Web Chat Import's manual-export safety net is a worse
  experience for someone used to the desktop app's automatic capture.
- Same underlying technique as the already-solved desktop-app collector
  (LevelDB + Snappy + V8 SerializedScriptValue decode, see CHANGELOG.md's
  "Claude desktop app chat capture" investigation) — Chrome/Edge's own
  IndexedDB storage for the claude.ai origin, same copy-before-read
  discipline (browsers hold a LevelDB single-writer lock while running).
  The hard part (the Snappy-compression bug in `ccl_chromium_reader`)
  is already solved and the fix already lives in `src/collector.py`'s
  `_idb_ssv_decode()` — a browser-profile collector would likely reuse
  that decoder directly, with a different profile-path lookup per
  browser instead of the MSIX-specific Electron path.
- Real complication not present in the desktop-app case: a regular
  browser profile is shared across every site the user visits, not just
  claude.ai — the IndexedDB database lookup needs to correctly scope to
  the `https://claude.ai` origin specifically (the desktop app's profile
  only ever has that one origin, simplifying the original collector).
- Not scheduled until there's a real signal it's wanted (a public user
  request, or the current user's own usage pattern changing) — Web Chat
  Import already covers this as a manual safety net in the meantime.

## iOS chat capture — UNSOLVED, needs a real automated path (HIGH)
- Problem: there is currently no way to get conversations out of the
  Claude iOS app into this archive without the user manually
  copy/pasting each chat by hand. A manual step "gets forgotten, or not
  done" (user's words) — if collection depends on manual labor, the
  phone is effectively out of scope for this whole project, since it
  defeats the "collects from all Claude interfaces" goal in CLAUDE.md.
- Researched and ruled out (2026-08-02, via research agent — see
  CHANGELOG.md for the session this happened in):
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
