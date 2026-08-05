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
