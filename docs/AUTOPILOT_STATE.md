# AUTOPILOT STATE (read first on every resume)

Updated: S5 start. Baseline: main @ tag s4-done, 101 tests green, ruff/mypy clean.

## Sprint status
| Sprint | Status | Branch | Tag |
|---|---|---|---|
| S1-S4 | done | merged | s4-done |
| S5 leakage precision + label_noise | in_progress | s5-leakage-precision | - |
| S6 ingest + upload + Quality Scorecard | todo | | |
| S7+ | todo (PRD order) | | |

## Eval-once ledger (machine-readable copy: benchmarks/eval_ledger.json)
| thresholds hash | partitions evaluated | result file | status |
|---|---|---|---|
| 2ca20d85b8f7... (v0) | dev, eval_v0 (old name `eval`), real tasks | leakage_v0.json | SPENT |

## Last completed step
S5 step 0: state file created.

## Attempt counters / skipped
none yet (see docs/SKIPPED.md when created)

## Resume rule
Find first non-done row above; inspect `git status`, finish or redo idempotently. Never run an eval for a hash already in the ledger.
