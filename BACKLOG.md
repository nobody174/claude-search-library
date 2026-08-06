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

## Decided, closed (continued)

- **R-2/R-3 — Security Auditor pass, 2026-08-06.** R-2 (`/review/reprocess`
  unbounded cost) fixed: added `MAX_REPROCESS_PER_CALL` hard cap (50) plus
  a required `"confirm": true` whenever `session_ids` is omitted (the
  actually dangerous "reprocess everything" default), paired with the
  same treatment for `/import`'s session-count (`MAX_IMPORT_SESSIONS_PER_
  CALL`) and a global `MAX_CONTENT_LENGTH`. R-3 (shared static Argon2
  salt) reviewed and left as-is: Argon2id's own cost parameters
  (`time_cost=3, memory_cost=64MiB, parallelism=4`) make precomputation
  economically similar to a per-target attack regardless of salt sharing,
  and the derived key additionally depends on a random ~160-bit TOTP
  secret with no feasible precomputed table against it — brute-force
  resistance was never resting on salt secrecy. Also fixed in the same
  pass: `/devices` switched from `SELECT *` to an explicit column
  allowlist so future schema columns aren't auto-exposed, and the
  IP-keyed `/setup` lockout got a comment documenting it breaks (global
  lockout, not per-user) if this server is ever put behind a reverse
  proxy without trusted-proxy header handling.

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
