# ADR-013: Approval tokens, audit hash chain and admin login (PRD S23)

Status: accepted (S11 of this run)

## Decision
- **Approvals** (`harness/security/approvals.py`): a gated action creates a request; a human approves via the admin API and receives an HMAC-signed token over `(approval_id, action, run_id, payload_hash, exp)`, TTL 10 minutes. `consume` validates signature, binding and expiry, then marks the row used with one atomic `UPDATE ... WHERE used_at IS NULL AND expires_at > now`; exactly one concurrent caller wins (8-thread test). Replay gives 409, wrong action/run/payload 403, expired 410, forged 401. Failed attempts do not burn the token.
- **Audit** (`harness/security/audit.py`): `hash = SHA256(prev_hash || canonical_json(record))`, appends serialised with `BEGIN IMMEDIATE`, UPDATE/DELETE blocked by triggers for the app connection. `verify_chain` pinpoints the first bad row after edits (row 3 in the test) and after deletions, even when the triggers are dropped by a privileged attacker. Tamper-evident, not tamper-proof: a full rewrite needs the head hash anchored externally (`GET /v1/audit/verify` returns it).
- **Admin login** (`harness/security/auth.py`, `apps/api/routes/admin.py`): `ADMIN_USER` + argon2 `ADMIN_PASSWORD_HASH`; HS256 JWT in an httpOnly, SameSite=Strict cookie, 30 min. No default credentials or secrets: if unset, login and approvals return 503.

## Gaps
SQLite backs both stores (unit-test engine). The PRD main profile is Postgres with `REVOKE UPDATE, DELETE` for the app role; the SQL is portable but the Postgres variant is NOT RUN. The deploy MCP server (PRD S20) does not exist, so no real gated action consumes these tokens yet; `harness/policies/actions.guard` is wired to the validator and tested. Audit coverage of every tool call (PRD S23.4) is not wired: only login, failed login and approval grants are written.
