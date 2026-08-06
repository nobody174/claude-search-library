# Backlog

Small, real, deliberately-deferred items — decisions awaiting input, known
edge cases, or low-severity gaps not worth interrupting other work for. Not
future features (see [ROADMAP.md](ROADMAP.md) for those); not a history of
what's shipped (see [CHANGELOG.md](CHANGELOG.md) for that).

---

## Decided, closed

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

## Awaiting the Security Auditor step (pre-release gauntlet, 2026-08-06)

Project Reviewer explicitly recommended taking these two as primary input
for the dedicated Security Auditor pass rather than fixing them blind
during the Implementer/Fixer step — both are security-posture decisions,
not simple bugs.

- **R-2: `/review/reprocess` (server.py:634) has no per-call cost cap.**
  Defaults to reprocessing EVERY pending/needs_review session if no
  `session_ids` given — real accidental-cost risk (each session costs real
  Claude API spend) for any authenticated caller. No dollar/session-count
  ceiling, dry-run flag, or confirmation step exists today.

- **R-3: shared static Argon2 salt** (`ARGON2_SALT` in crypto.py) is a
  deliberate design choice for deterministic cross-device key derivation
  — but going public means every installation shares the same salt, so a
  single precomputed attack investment amortizes across all public users,
  not just one target. Not discussed anywhere in CLAUDE.md's Security
  section.

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

- **`show-totp-qr` (crypto.py's `show_totp_qr_again()`) has no rotation/
  revocation flow** if the displayed QR leaks (screen recording, shoulder
  surfing) — found by Project Reviewer during the pre-public-release
  gauntlet, 2026-08-06 (R-5). The function now prints a warning before
  displaying, but the underlying gap (no way to invalidate the existing
  TOTP secret and issue a new one without redoing full device setup on
  every device) is unbuilt. Low severity today (single-user, TOTP secret
  never leaves the local machine except this on-screen display) — revisit
  if this project ever supports multiple people/accounts, where a leaked
  secret would need to be revocable without disrupting other users.

- **`show-totp-qr` is CLI-only, no web UI equivalent** (F-3, Project
  Reviewer 2026-08-06) — asymmetric with the project's stated multi-device/
  phone-access goals, since re-provisioning a lost/broken phone currently
  requires shell access to a *different* already-set-up device rather than
  being reachable from the web UI itself. Deferred: the CLI path already
  fully solves the "I lost my phone" scenario this exists for (see
  CHANGELOG.md's TOTP re-provisioning entry), and a web-reachable version
  would need its own security review (displaying a raw TOTP secret over
  HTTP to a browser is a materially different exposure than a local
  terminal).

(Mobile TOTP re-provisioning and browser-profile chat capture were moved
to [ROADMAP.md](ROADMAP.md) 2026-08-06 — both turned out to be real,
scopeable features worth tracking as future work rather than permanent
low-priority friction.)
