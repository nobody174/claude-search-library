# Roadmap

Real future features, not yet started. For small deferred decisions/known
edge cases see [BACKLOG.md](BACKLOG.md); for what's already shipped see
[CHANGELOG.md](CHANGELOG.md).

---

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
