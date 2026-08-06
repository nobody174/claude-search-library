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

## Android chat capture via ADB + accessibility tree (HIGH — core mechanism proven)
- Problem: same underlying gap as iOS (see BACKLOG.md's closed iOS
  entry) — the Claude Android app has no export/read capability
  (confirmed: App Actions/widgets are send-only, same as iOS; official
  export is desktop/web-only on Android too, confirmed directly by
  Anthropic). Unlike iOS, though, Android doesn't require jailbreaking
  or violating Anthropic's Consumer Terms to solve this — the OS itself
  exposes a real, legitimate mechanism that never touches claude.ai's
  servers at all.
- **Core mechanism empirically proven working, 2026-08-06, on a real
  device** (Samsung Galaxy Note20 Ultra, Android 13, connected via `adb
  connect <phone-ip>:<port>` over WiFi — same wireless-debugging setup
  used for the Dungeon Clicker 9000 Android builds). Opened a real
  Claude conversation on the phone, ran `adb shell uiautomator dump`
  (Android's built-in, zero-cost UI-inspection tool — no paid apps, no
  root, no jailbreak-equivalent needed) and confirmed the dumped XML
  contains the **complete, exact message text** of every visible
  message — not a custom-rendered opaque canvas hiding content from
  accessibility tools, which was the real open risk research had
  flagged. This settles the one empirical unknown the 2026-08-06
  research pass identified as needing real hardware to answer.
- **What's proven vs. what still needs building:**
  - Proven: `adb connect` over WiFi works reliably (reused a prior
    working setup, reconnected in seconds once given the phone's
    current IP:port); Claude launches via `adb shell monkey -p
    com.anthropic.claude ...`; `uiautomator dump` reliably extracts
    real conversation text from an opened chat.
  - Not yet built/tested: reliable programmatic scrolling to page
    through a long conversation and detect "reached the top" (the one
    scroll attempt during this test session didn't visibly move the
    screen — needs real iteration, not a blocker, just unproven);
    looping through the full conversation list automatically (tap each
    item, dump, scroll-and-dump-until-done, back out, next); parsing
    the accessibility-tree XML into a clean transcript (user/assistant
    turns aren't explicitly labeled in the raw dump — same kind of
    structural inference `collect_from_claude_code()` already does for
    its JSONL format, not a new problem class for this project);
    feeding parsed output into the existing collector/normalize_session
    pipeline.
- **Real advantage over the Tasker+AutoInput path the initial research
  suggested**: `uiautomator` is already free and built into every
  Android device — no paid app purchase needed at all (confirmed
  2026-08-06 per the user's explicit preference not to require buying
  apps). The whole pipeline can live as a Python script on the desktop
  side, driving the phone entirely via `adb shell` commands (dump,
  tap, swipe) — consistent with how this project already treats other
  devices as remote-controllable via existing tooling, not something
  that needs an on-phone app installed and configured by hand.
- **Real complication to solve during implementation**: `adb connect`
  requires the phone's current WiFi IP:port, which changes whenever the
  phone reconnects to WiFi or the router reassigns DHCP leases — not
  persistent across sessions. A real collector would need either a
  documented manual reconnect step (check Settings → Developer options
  → Wireless debugging, same as this test did) or investigate whether
  ADB's mDNS auto-discovery (seen automatically pairing a second
  `adb-tls-connect._tcp` entry during this test) can be relied on to
  find the phone without a human re-entering the IP each time.
- Not yet scheduled for implementation — this entry documents the
  proven mechanism and real scope; actual build work (scroll/loop
  logic, XML-to-transcript parsing, a real `collect_from_claude_android()`
  in `src/collector.py`) hasn't started.

---

*iOS chat capture was researched exhaustively — see [BACKLOG.md](BACKLOG.md)'s
"Decided, closed" section — and moved there 2026-08-06 as a settled
decision, not a future feature: no automated path exists that doesn't
violate Anthropic's Consumer Terms or require jailbreaking, confirmed
directly by Anthropic's own support channel. Android's real advantage
(see above) is exactly the OS-level accessibility mechanism iOS
structurally lacks.*
