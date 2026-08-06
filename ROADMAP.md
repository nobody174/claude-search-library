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
- **Checked whether anyone else has solved this, twice — once by feature
  name, once by mechanism (2026-08-06).** First pass (searching
  "export"/"sync"/"backup" phrasing) found nothing. Broadened on the
  reasonable suspicion that a real solution would be described by *what
  was built*, not by matching feature-request wording — 9 varied
  queries (screen-scraping/OCR + Claude iOS, casual "backup my chats"
  phrasing, GitHub code search for `UIAccessibility`/`AXUIElement`/
  `ReplayKit` + claude.ai, Tasker/MacroDroid + Claude on Android, HN's
  own search engine, unofficial Discord). Found 7+ real, working
  third-party tools (claude-archive, claude-backup, ClaudeKeep,
  Tampermonkey userscripts, browser extensions) — every single one
  targets the **claude.ai website** via Playwright/unofficial web
  API/browser extension. Zero touch the native iOS app's sandboxed
  content. Anthropic's own Help Center is explicit: "Export is
  available on the web app and Claude Desktop only. iOS and Android do
  not currently support exports." 3 open feature requests on
  `anthropics/claude-code` (#12858, #30673, #55787) confirm cross-
  surface history access is a known, unshipped pain point — not
  something obscure. **Verdict: a genuine, non-obvious gap with no
  known implementation by anyone, anywhere that surfaces publicly** —
  not a search-phrasing failure on this project's part.
- **Found the real contact channel (2026-08-06)**: no public feedback
  board or standalone support email exists for consumer Claude.ai/iOS
  product questions. The only real channel is in-app: claude.ai → your
  name/initials (bottom left) → "Get help" → "Send us a message" (Fin,
  the AI support bot, escalates to a human Product Support rep by email
  if it can't answer). See the drafted message below.
- **What's actually being asked for, made explicit** (three variants,
  in order of how good an answer would be):
  1. Best case: a real, documented API endpoint (gated by an actual API
     key — the sanctioned channel Anthropic already has a carve-out
     for) that lets a consumer pull their own stored conversation
     history. Distinct from the existing developer Messages API, which
     is stateless and has no concept of claude.ai's stored history at
     all.
  2. Good enough: an export trigger reachable via a real API call
     instead of a manual web/desktop click — still something this
     project would call once a day via `cli.py sync`, just not banned
     by §3 the way scripting the web UI is.
  3. Minimum useful answer: just confirmation of whether iOS/Android
     export is planned at all. Even "no, not planned" is useful — it
     turns the scope-reconsideration fallback below from "open-ended
     hope" into a confident, final decision.
- **The two live options below are one decision, not two separate
  items** — ask Anthropic first; whatever they say determines whether
  building resumes or the phone permanently stays a read/search-only
  client:
  - **Send the drafted message** (below) via the in-app channel found
    above. Worth trying since every self-built automated path is now
    confirmed either technically dead or ToS-blocked — this is the one
    lead never actually attempted, and costs nothing to ask.
  - **If the answer is no / no reply / nothing planned**: fall back to
    reconsidering scope — accept that phone-originated conversations
    aren't capturable right now, treat the phone purely as a
    search/reference client (per the original CLAUDE.md Key Decision
    #5), and do real conversation work on desktop/laptop where official
    export already works fine. Not a first resort, but the honest
    landing point if Anthropic has nothing to offer.
- Do not schedule implementation work here until Anthropic's answer (or
  lack of one) resolves which branch above applies — this entry exists
  to make sure the gap stays visible instead of being silently dropped.

### Draft message to Anthropic (not sent — send via the in-app "Get help" flow above)

> Hi — I'm building a personal, local-first tool that archives and
> searches my own Claude chat history across the devices I use (desktop
> app, Claude Code, Cowork). It works well for everything except the
> iOS app.
>
> I know Settings → Export Data is desktop/web-only today, and that the
> iOS Shortcuts "Ask Claude" integration is send-only with no way to
> read or export existing conversations. I've deliberately ruled out
> unofficial API scraping and any automated interaction with the
> claude.ai web session, since your Consumer Terms explicitly prohibit
> automated/non-human access and I couldn't find an exception for a
> user accessing their own data.
>
> Is there, or is there any plan for, a sanctioned way for a consumer
> account to retrieve their own conversation history from the iOS app —
> e.g. an API endpoint gated by a real API key, or an export trigger
> reachable outside the manual web/desktop + email-link flow? Even
> knowing it's not planned would be genuinely useful — I'd rather ask
> directly than build something that risks violating your terms.
>
> Thanks for your time!

*(This is a first draft to send through claude.ai's "Get help" chat,
not a formal email — no subject line needed, tone can be adjusted
before sending. Real conversational back-and-forth with Fin/a human rep
may be needed rather than one message landing a full answer.)*

*(Adjust tone/detail before actually sending — this is a first draft,
not final copy. Send via Anthropic's support channel, not a public
GitHub issue, since it's an account-specific question, not a bug
report.)*
