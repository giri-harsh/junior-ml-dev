# STATE (re-read at the start of every session)

Source plan: `PRD.md` (S1â€“S28). Spec: **missing** (see DECISIONS #1).
Current branch: `sprint-2-scorer-core`. S1 merged to main; current sprint: **S2 Task registry + scorer core** (done, pending merge).

## S1 â€” Foundations
- [x] S1.1 skeleton, uv, ruff, mypy, pytest, Makefile + tasks.py
- [~] S1.2 compose micro/full files written â€” **unvalidated, Docker not installed** (BLOCKED-SOFT)
- [x] S1.3 CI workflow, .gitleaks.toml, pre-commit hook, regex fallback
- [x] S1.4 TrajectoryEvent, JSONL writer, events table (SQLAlchemy + Alembic 0001), emit()
- [x] S1.5 results_writer with conditions stamp
- [x] S1.6 reference-machine.md, README skeleton, ADR-001, ADR-015

## S2 — done
- [x] S2.1 registry (10 tasks, 3 imbalanced, 2 p3_heldout) · [x] S2.2 fetch (all 10 from OpenML, licence/id in source.json; DVC not used, see DECISIONS) · [x] S2.3 splits · [x] S2.4 metrics · [x] S2.5 scorer API + compose isolation · [x] S2.6 p3 partition + ADR-004 stub
- Acceptance measured: splits byte-identical across two runs for all 10; metrics match hand-computed fixtures; compose test shows only `scorer` mounts `scorer_data`. Runtime check that a *container* cannot see it is blocked (no Docker).

## Unmet S1 acceptance criteria
- "compose healthy from clean clone": not measurable, no Docker.
- "CI green on a PR" and "pushed fake secret caught by gitleaks in CI": need a GitHub remote (DECISIONS #11). Local equivalent: `test_secret_scan.py`.

## Next action
Start S3 (baselines + planted-bug generator). Docker/remote items above remain open.
