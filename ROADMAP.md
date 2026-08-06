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

## Android + iOS chat capture via ADB + accessibility tree, using Android as a bridge (HIGH — core mechanism proven end-to-end)
- **This entry now covers both Android and iOS.** iOS was previously
  closed as genuinely unsolved (see CHANGELOG.md's 2026-08-06 entries)
  — that finding was correct for "automate something on the iPhone
  itself," but missed a real angle: **claude.ai conversations are one
  cloud-synced account across every mobile client, not siloed per
  platform** (confirmed via Anthropic's own Help Center docs on
  Android/iOS app usage; the only documented siloing is Desktop app vs.
  mobile/web, which doesn't apply here). A conversation started on
  iPhone shows up on Android under the same account, in seconds, no
  manual action needed. **Verified live, 2026-08-06**: started a real,
  new conversation on the user's iPhone, and within seconds it appeared
  at the top of "Recents" on the Android test phone — opened it there
  and confirmed the full message text (both the user's message and
  Claude's reply) was completely extractable via `uiautomator dump`.
  This means an Android-side capture mechanism captures iOS-originated
  conversations too, automatically, as a side effect of the account
  being shared — no iOS-side automation needed at all, no jailbreak, no
  ToS violation, since nothing ever touches the iPhone or claude.ai's
  servers directly.
- Problem (both platforms): the Claude Android and iOS apps have no
  export/read capability (confirmed: App Actions/widgets/Shortcuts are
  send-only on both; official export is desktop/web-only on both,
  confirmed directly by Anthropic). Android doesn't require
  jailbreaking or violating Anthropic's Consumer Terms to solve this,
  though — the OS itself exposes a real, legitimate mechanism that
  never touches claude.ai's servers at all, and per the account-sync
  finding above, this single mechanism now closes the gap for iOS too.
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
  research pass identified as needing real hardware to answer. The
  follow-up cross-device test (a real iPhone conversation → visible and
  fully extractable on Android within seconds) settles the second real
  unknown: whether Android-side capture would actually reach
  iOS-originated content, not just Android-originated content.
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
- **History note**: iOS chat capture was previously researched
  exhaustively (2026-08-02 and 2026-08-06, multiple passes — see
  CHANGELOG.md) and correctly closed as unsolved *for iOS-side
  automation specifically* — every technical path was either dead
  (Shortcuts/Accessibility has no third-party read hook, CDP automation
  of the desktop app is empirically confirmed dead) or ToS-blocked
  (automating the official export flow). That research was thorough and
  correct on its own terms; it just hadn't yet considered that the
  fix didn't need to touch iOS at all. The account-sync discovery above
  reopens the outcome without invalidating any of that earlier work —
  it's a different mechanism entirely (Android as a bridge), not a hole
  in the prior research.
