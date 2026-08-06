# Backlog

Small, real, deliberately-deferred items — decisions awaiting input, known
edge cases, or low-severity gaps not worth interrupting other work for. Not
future features (see [ROADMAP.md](ROADMAP.md) for those); not a history of
what's shipped (see [CHANGELOG.md](CHANGELOG.md) for that).

---

## Decided, closed

- **iOS chat capture — genuinely unsolved, decision made 2026-08-06.**
  Moved here from ROADMAP.md: this is a closed decision, not a future
  feature to build. Full investigation across 2026-08-02 and 2026-08-06
  (multiple research passes, see CHANGELOG.md) ruled out every real
  path: official export is desktop/web-only; unofficial API scraping
  and any automated interaction with claude.ai violate Anthropic's
  Consumer Terms (§3), actively enforced in 2026; iOS Shortcuts/
  Accessibility APIs have no hook to read a third-party app's screen
  content; forcing the desktop app to bulk-cache every conversation via
  Chrome DevTools Protocol automation was empirically tested and
  confirmed dead (the MSIX-packaged Windows app kills its process
  outright when launched with `--remote-debugging-port`); automating
  the official Export Data flow end-to-end is ToS-blocked, not just
  technically hard; a broad prior-art search (9 varied queries, by
  feature name and by mechanism) found zero evidence anyone has solved
  this for the native iOS app specifically — every real third-party
  Claude archive/backup tool that exists targets the website, never the
  app. **Asked Anthropic directly** via the in-app "Get help" channel —
  Fin (Anthropic's support agent) confirmed no sanctioned API or
  automated export method exists for consumer accounts (Free/Pro/Max);
  a Compliance API does exist but is Enterprise/Platform-only, not
  reachable by individual users; Anthropic has no visibility into
  whether a consumer-facing option is planned; Anthropic's own
  recommendation was to leave iOS conversations out of the archive for
  now. **Decision**: accept this. The iPhone is a search/reference
  client only (per CLAUDE.md Key Decision #5) — real conversation work
  happens on desktop/laptop, where official export works fine. Revisit
  only if Anthropic ships something new, or the phone gets jailbroken
  for unrelated reasons. Not worth checking back on a schedule.

- **Unredacted pre-fix summaries in `claude-search-data`'s git history —
  decision confirmed 2026-08-06.** The plan to make `claude-search-library`
  (code) public, with `claude-search-data` (the actual chat archive)
  staying private, resolves this: the history that would be exposed by a
  public code repo is the *code* repo's own history, checked directly
  (2026-08-06) and found clean — no real API keys/tokens, only placeholder
  syntax (`sk-ant-...`, etc.) in setup instructions. The data repo's
  unredacted pre-fix history stays private either way, so the original
  2026-08-05 call (leave it alone, reprocess going forward) still holds.
  Revisit only if the *data* repo itself is ever considered for public
  release — a different, much higher-stakes decision than the code repo.

## Known, low-severity, not currently worth fixing

- **Genuinely simultaneous (not just sequential) CRDT writes are proven
  safe** (deterministic convergence, no corruption) but only for one
  tested scenario: competing inserts of the same new row, verified via a
  real two-database E2E test (2026-08-05). Fine to leave as-is; revisit
  only if a real multi-device conflict ever looks wrong in practice — if
  that happens, compare against this baseline first: single scenario
  tested was two devices independently inserting a brand-new row with the
  same id before syncing; both survived, deterministic convergence,
  confirmed via `vendor/cr-sqlite/test_e2e_two_devices.py`. A conflict
  that looks wrong and *doesn't* match this pattern (e.g. involves an
  UPDATE, not an INSERT) is the first thing to distinguish when
  investigating.

(Mobile TOTP re-provisioning and browser-profile chat capture were moved
to [ROADMAP.md](ROADMAP.md) 2026-08-06 — both turned out to be real,
scopeable features worth tracking as future work rather than permanent
low-priority friction.)
