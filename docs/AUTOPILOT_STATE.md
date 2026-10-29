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
| S11 approvals + audit chain + admin login | done | s11-approvals-audit | s11-done |
| S12 experiments MCP server | done | s12-experiments | s12-done |
| S13 agent harness + planners + deploy MCP + queue + runs API + report | done | s13-agent-harness | s13-done |
| S14 agent dev partition, eval-once agent benchmark, injection scanner v1, README/demo/UI | done (benchmark result: see ledger row) | s14-agent-benchmark | s14-done, agent-frozen |
| rest of PRD (see SKIPPED.md) | skipped/stub | | |

## Eval-once ledger (machine-readable copy: benchmarks/eval_ledger.json)
| thresholds hash | partitions evaluated | result file | status |
|---|---|---|---|
| 2ca20d85b8f7... (v0) | dev, eval_v0 (old name `eval`), real tasks | leakage_v0.json | SPENT |
| 0cde227f6327... (v1) | dev (record), eval2, real_heldout | leakage_v1.json | SPENT (run triggered early by a test bug; see ADR-007 lim. 6) |

| agent:66e3796c63e0... (scripted planner freeze) | 10 benchmark tasks | agent_v1.json | CLAIMED before run; see benchmarks/eval_ledger.json for final status |

## Last completed step
S14 merged; agent-frozen tag set; final agent benchmark launched once (ledger claimed). Next: collect agent_v1.json, render docs/RESULTS.md, update AUTOPILOT_REPORT.md. If the benchmark crashed, resume ONLY with `python -m benchmarks.agent_benchmark --final --resume` (reruns unfinished tasks, never finished ones).

## Attempt counters / skipped
none yet (see docs/SKIPPED.md when created)

## Resume rule
Find first non-done row above; inspect `git status`, finish or redo idempotently. Never run an eval for a hash already in the ledger.
