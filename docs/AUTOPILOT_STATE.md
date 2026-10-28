# AUTOPILOT STATE (read first on every resume)

Updated: S5 start. Baseline: main @ tag s4-done, 101 tests green, ruff/mypy clean.

## Sprint status
| Sprint | Status | Branch | Tag |
|---|---|---|---|
| S1-S4 | done | merged | s4-done |
| S5 leakage precision + label_noise | done (pending merge) | s5-leakage-precision | s5-thresholds-frozen, s5-done |
| S6 ingest + upload + Quality Scorecard | todo | | |
| S7+ | todo (PRD order) | | |

## Eval-once ledger (machine-readable copy: benchmarks/eval_ledger.json)
| thresholds hash | partitions evaluated | result file | status |
|---|---|---|---|
| 2ca20d85b8f7... (v0) | dev, eval_v0 (old name `eval`), real tasks | leakage_v0.json | SPENT |
| 0cde227f6327... (v1) | dev (record), eval2, real_heldout | leakage_v1.json | SPENT (run triggered early by a test bug; see ADR-007 lim. 6) |

## Last completed step
S5 complete: eval done, adjudicated, docs written. Next: merge, tag s5-done, start S6 (PRD S4/S5 map).

## Attempt counters / skipped
none yet (see docs/SKIPPED.md when created)

## Resume rule
Find first non-done row above; inspect `git status`, finish or redo idempotently. Never run an eval for a hash already in the ledger.
