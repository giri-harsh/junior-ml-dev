# STATE (re-read at the start of every session)

Source plan: `PRD.md` (S1–S28). Spec: **missing** (see DECISIONS #1).
Current branch: `sprint-1-foundations`. Current sprint: **S1 Foundations**.

## S1 — Foundations
- [x] S1.1 skeleton, uv, ruff, mypy, pytest, Makefile + tasks.py
- [~] S1.2 compose micro/full files written — **unvalidated, Docker not installed** (BLOCKED-SOFT)
- [x] S1.3 CI workflow, .gitleaks.toml, pre-commit hook, regex fallback
- [x] S1.4 TrajectoryEvent, JSONL writer, events table (SQLAlchemy + Alembic 0001), emit()
- [x] S1.5 results_writer with conditions stamp
- [x] S1.6 reference-machine.md, README skeleton, ADR-001, ADR-015

## Unmet S1 acceptance criteria
- "compose healthy from clean clone": not measurable, no Docker.
- "CI green on a PR" and "pushed fake secret caught by gitleaks in CI": need a GitHub remote (DECISIONS #11). Local equivalent: `test_secret_scan.py`.

## Next action
Install Docker Desktop (human-only), or create the GitHub remote, then close the two items above. Otherwise start S2 (task registry + scorer core).
