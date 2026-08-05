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
- **On-device accessibility/Shortcuts automation — researched and ruled
  out (2026-08-06, via research agent).** Genuinely investigated, not
  assumed: no "read screen content" Shortcuts action exists for
  third-party apps (the closest, "Receive What's On Screen," only
  works with a handful of Apple-blessed apps that explicitly opt in —
  Claude's iOS app doesn't); Claude's official App Intent
  ([Anthropic's own docs](https://support.claude.com/en/articles/10263469-using-claude-app-intents-shortcuts-and-widgets-on-ios))
  exposes exactly one action, "Ask Claude" (send-only, no read/export
  action, none found to be planned); iOS 26's new Accessibility Reader
  is a manual, interactive UI feature with no scriptable hook. A real
  working alternative does exist — screen-record while scrolling +
  on-device OCR, the same technique a live App Store app (TextPort)
  already uses for other chat apps — but it requires the user to
  manually trigger and scroll through each conversation, every time.
  **Rejected for the same reason as the one-tap-save idea above**: it
  reduces labor but doesn't remove the "user has to remember to do it
  per chat" failure mode that's the actual problem. Apple's sandboxing
  model has no unattended/scheduled path into another app's content
  without jailbreaking, and nothing in current iOS changes that.
- **Forcing the desktop app to bulk-cache every conversation via CDP
  automation — researched and ruled out empirically (2026-08-06).** The
  desktop app's local IndexedDB cache (what `collect_from_claude_desktop()`
  reads) only populates for a conversation once a human opens it — so
  scripting the desktop app to auto-open every sidebar conversation
  (via Chrome DevTools Protocol, e.g. Puppeteer/Playwright) would force
  full history into the existing collector's data source, unattended.
  Directly tested, not assumed: launching the installed Windows
  Claude.exe (MSIX-packaged) with `--remote-debugging-port=9222`
  produces zero surviving processes every time (vs. a clean multi-process
  launch without the flag) — confirmed reproducible. MSIX's app-container
  sandboxing rejects the flag outright. Dead end on this platform.
- **Automating Anthropic's official "Export your Claude data" flow
  end-to-end (trigger + retrieve, zero human interaction) — researched
  and ruled out (2026-08-06).** This export is account-wide, including
  iPhone-originated conversations — the one path that would have
  actually closed the iPhone gap specifically. Blocked by law/policy,
  not technology: Anthropic's Consumer Terms (§3) ban "automated or
  non-human means" of accessing claude.ai with no exception for a user
  automating access to their own account/data, and 2026 enforcement
  (the "OpenClaw" crackdown on third-party harnesses) shows this is
  actively policed, not a dead-letter clause. Confirmed separately: the
  export is delivered by email only (no in-website download panel
  found), 24-hour link expiry, so even the one easy-to-automate piece
  (IMAP polling for the download link) can't stand alone — it doesn't
  solve triggering the export in the first place, which is the actually
  -prohibited step.
- **Checked whether anyone else has solved this — genuinely unsolved,
  not a known problem with a known fix this project missed (2026-08-06).**
  Anthropic's own Help Center is explicit: "Export is available on the
  web app and Claude Desktop only. iOS and Android do not currently
  support exports." No hidden Shortcuts/App Intent read capability
  found. No consumer community forum for claude.ai (only the
  developer-focused `anthropics/claude-code` repo, which has 3 separate
  open feature requests asking for cross-surface history access -
  #12858, #30673, #55787 - confirming this is a known pain point
  Anthropic hasn't shipped a fix for, not something obscure). Reddit
  searches returned nothing. Every existing third-party export tool
  operates on the desktop/browser session, never the iOS app.
- **Two things remain, not yet done:**
  - **Draft message to Anthropic, parked as a genuine last resort** (not
    sent yet — see below) asking whether a legitimate, ToS-sanctioned
    consumer export/sync API for iOS is available or planned. Worth
    trying since every self-built automated path is now confirmed
    either technically dead or ToS-blocked - this is the one lead never
    actually attempted.
  - Reconsidering scope: is capturing *phone-originated* conversations
    actually required, vs. using the phone purely as a search/reference
    client (per the original CLAUDE.md Key Decision #5) and doing all
    real conversation work on desktop/laptop where official export
    works fine? With all three researched automation directions now
    ruled out (2 technical, 1 legal), this is the practical fallback if
    Anthropic has no plans here — not a first resort, but a real one.
- Do not schedule implementation work here until a specific approach is
  chosen — this entry exists to make sure the gap stays visible instead
  of being silently dropped.

### Draft message to Anthropic (not sent — parked for if/when this becomes the last resort)

> Subject: Legitimate/sanctioned way to export or sync Claude iOS conversation history?
>
> Hi — I'm building a personal, local-first tool that archives and
> searches my own Claude chat history across the devices I use (desktop
> app, Claude Code, Cowork). It works well for everything except the
> iOS app: Settings → Export Data is desktop/web-only, and the iOS
> Shortcuts "Ask Claude" App Intent is send-only (no read/export
> action). I've deliberately ruled out unofficial API scraping and any
> automated interaction with claude.ai's web session, since your
> Consumer Terms §3 explicitly prohibit automated/non-human access with
> no exception I could find for a user accessing their own data.
>
> Is there, or is there planned to be, any sanctioned way for a
> consumer account to programmatically retrieve their own conversation
> history from the iOS app — e.g. a scoped API endpoint gated by a real
> API key, or an export trigger reachable outside the manual
> Settings → Export Data + email-link flow? I'd rather ask directly than
> build something that risks violating your terms.
>
> Thanks for your time.

*(Adjust tone/detail before actually sending — this is a first draft,
not final copy. Send via Anthropic's support channel, not a public
GitHub issue, since it's an account-specific question, not a bug
report.)*
