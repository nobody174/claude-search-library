# Backlog

Small, real, deliberately-deferred items — decisions awaiting input, known
edge cases, or low-severity gaps not worth interrupting other work for. Not
future features (see [ROADMAP.md](ROADMAP.md) for those); not a history of
what's shipped (see [CHANGELOG.md](CHANGELOG.md) for that).

---

## Awaiting a decision

- **Unredacted pre-fix summaries still live in `claude-search-data`'s git
  history.** Every summary pushed *before* the 2026-08-05 redaction fix
  (see CHANGELOG.md) is still unredacted in that repo's commit history,
  even though current summaries are redacted going forward. Decided
  2026-08-05: leave git history alone (private repo, Fernet-encrypted,
  real exposure is low) rather than rewrite it — reprocessing existing
  sessions through the now-fixed pipeline was done instead (56 of 62
  succeeded; see the "no readable raw file" item below for the other 6).
  Revisit only if a real history rewrite is actually wanted later — it's
  destructive (force-push, breaks any existing clones) so treat as a real
  decision each time, not a default.

## Known, low-severity, not currently worth fixing

- **5 real sessions have no readable raw file**, so their pre-redaction-fix
  summaries can't be regenerated through the reprocessing pipeline.
  Pre-existing, not new — `/health` has flagged these as "no readable raw
  file" all along. Nothing to do unless the original raw exports turn up
  somewhere.

- **Genuinely simultaneous (not just sequential) CRDT writes are proven
  safe** (deterministic convergence, no corruption) but only for one
  tested scenario: competing inserts of the same new row, verified via a
  real two-database E2E test (2026-08-05). Fine to leave as-is; revisit
  only if a real multi-device conflict ever looks wrong in practice.

- **Mobile TOTP sync/setup friction** — getting Google Authenticator's
  TOTP secret onto a phone during device setup is more manual than ideal.
  An SMS-code alternative was considered as a fallback if TOTP
  distribution proves too complex in practice, but hasn't been revisited
  since — current flow (scan QR during setup) works, just not
  frictionless.

- **The Claude desktop app collector only reads this Windows machine's
  own local Chromium profile** — no visibility into conversations opened
  only via a browser tab at claude.ai, or via mobile. A future idea, not
  started: apply the same local-cache-reading technique (see CHANGELOG.md's
  "Claude desktop app chat capture" investigation) to a regular browser's
  own profile (Chrome/Edge's IndexedDB for claude.ai) to close this gap
  too. Not scheduled — the manual export (Web Chat Import) already covers
  this as an occasional safety net.
