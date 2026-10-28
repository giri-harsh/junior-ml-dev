# STATE (re-read at the start of every session)

Source plan: `PRD.md` (S1â€“S28). Spec: **missing** (see DECISIONS #1).
Current branch: `sprint-3-baselines-bugs`. S1, S2 merged to main; current sprint: **S3 Baselines + bug generator** (done, pending merge).

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

## S3 — done
- [x] S3.1 baselines (dummy/linear/FLAML 30 s, scored via scorer code path) · [x] S3.2 normalized score, pass rule + ceiling, bootstrap CI · [x] S3.3 8 bug types with clean twins + labels.json · [x] S3.4 dev/eval partition (3/3 per type) · [x] S3.5 run_benchmark skeleton, `baselines_v0.json`, ADR-005
- Acceptance measured: baselines for 10/10 tasks with conditions block; generator manifest stable across two runs (test); naive-CV bugged > twin for all 30 leakage variants (`planted_bugs_v0.json`). Margin is thin for group_leak_00 (+0.015 AUC) and varies by variant.

## Unmet S1 acceptance criteria
- "compose healthy from clean clone": not measurable, no Docker.
- "CI green on a PR" and "pushed fake secret caught by gitleaks in CI": need a GitHub remote (DECISIONS #11). Local equivalent: `test_secret_scan.py`.

## Next action
Start S4 (ingest + profile + quality scorecard). Docker/remote items above remain open.
