# AUTOPILOT STATE (read first on every resume)

Updated: S5 start. Baseline: main @ tag s4-done, 101 tests green, ruff/mypy clean.

## Sprint status
| Sprint | Status | Branch | Tag |
|---|---|---|---|
| S1-S4 | done | merged | s4-done |
| S5 leakage precision + label_noise | done (pending merge) | s5-leakage-precision | s5-thresholds-frozen, s5-done |
| S6 ingest + upload + Quality Scorecard | done | s6-ingest-quality | s6-done |
| S7 insights + claim verifier | done | s7-insights-verifier | s7-done |
| S8 LLM gateway (mock/recorded) | done | s8-llm-gateway | s8-done |
| S9 sandbox interface + code policy | done | s9-sandbox-policy | s9-done |
| S10 reviewer checks + injection defence | done | s10-review-injection | s10-done |
| S11 approvals + audit chain + harness state | todo | | |
| rest of PRD (charts, UI, deploy MCP, load, observability, full benchmarks, E2B, arq/Postgres) | skipped, see SKIPPED.md | | |

## Eval-once ledger (machine-readable copy: benchmarks/eval_ledger.json)
| thresholds hash | partitions evaluated | result file | status |
|---|---|---|---|
| 2ca20d85b8f7... (v0) | dev, eval_v0 (old name `eval`), real tasks | leakage_v0.json | SPENT |
| 0cde227f6327... (v1) | dev (record), eval2, real_heldout | leakage_v1.json | SPENT (run triggered early by a test bug; see ADR-007 lim. 6) |

## Last completed step
S10 complete. Next: S11 approvals + audit chain.

## Attempt counters / skipped
none yet (see docs/SKIPPED.md when created)

## Resume rule
Find first non-done row above; inspect `git status`, finish or redo idempotently. Never run an eval for a hash already in the ledger.
