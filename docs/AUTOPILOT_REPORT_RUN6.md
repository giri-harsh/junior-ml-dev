# Autopilot report - run 6 (S25-S30 + stretch)

Probe: keys by name present for Groq/Gemini only; no Docker/E2B/Ollama; gh authenticated; CI green at start.

## Implemented
| Item | Tag | Notes |
|---|---|---|
| S25 leakage v3 | s25-done | linear-combination detector, adaptive bounded detection |
| S26 critic calibration | s26-done | critic v2, family-aware gap ratios |
| S27 real-LLM injection rerun | s27-done | suite + held-out, planner-v2-style prompt |
| S28 v5 benchmark | agent-frozen-v5 | scripted + real-LLM arms, run once |
| S29 hardening | - | rate limit, idempotency, audit, load test, React viewer |
| S30 metrics + docs | - | docs/METRICS.md, README, CI evidence collector |
| Stretch 1-6 | stretch-1..6 | security CI, coverage floor, MCP docs, reliability, observability, DX |
| Stretch 8 | stretch-8 | vulture clean at conf 80; B613 fixed; nothing dead to remove |
| Stretch 7 | see below | v0.1.0 release |

## Verification
- Local gate (final): ruff + format + mypy clean, 432 passed, coverage 92.04% (floor 91).
- CI: stretch merge ci 40953422203 success, infra 40953422200 success; final push ci 40999208372, infra 40999208368 (see METRICS.md for the latest status).
- Actions budget: about 12 runs this run (limit 25).

## Leakage v3 (eval4)
Recall 29/30 (0.967), clean-twin false alarms 0/30 (Wilson upper 0.114). Source: benchmarks/results/leakage_v3.json.

## Critic
Dev calibration: v2 caught 11/11 rule-flagged mutations (critic_calibration.json). v5 agreement: 18/20 (Wilson 0.70-0.97); both misses are rule=REQUEST_CHANGES where the critic approved (critic_v5.json).

## Injection rerun (real LLM)
Attacker action proposed 0/49 (suite 0/41, held-out 0/8; Wilson upper 0.086 / 0.324), unsafe executed 0. Critic flag rate on injected runs: not applicable (no runs). Evasion DEV split: not run (budget). The held-out set was also used in injection_llm_v1, so it is not a fresh partition.

## v5 numbers (normalized, FLAML = 1)
| Arm | Score | Paired vs linear | Paired vs FLAML | Pass vs linear |
|---|---|---|---|---|
| scripted | 0.987 [0.949, 1.011] | 0.189 [0.075, 0.315] | -0.013 [-0.051, 0.011] | 7/10 |
| LLM planner v2 | 0.989 [0.950, 1.012] | 0.190 [0.076, 0.316] | -0.011 [-0.050, 0.012] | 8/10 |
Linear baseline 0.798. LLM minus scripted 0.001 [-0.001, 0.004]. LLM arm: 130 requests, 19.6k tokens, $0, p50 135 s / p95 226 s per task. Ran from a worktree at agent-frozen-v5 (hash 681f3126...).

## Load test / governance / UI
Load (CI run 40945724068): 5 users 36 rps no errors; 100 users 17.8% errors (hosted runner). Auth, audit chain, rate limit, idempotency, dead letters, graceful SIGTERM in place. MinIO not pullable: moto stand-in kept. React viewer built in CI (web run 40945730802), served at /app.

## Decisions
119-135 in docs/DECISIONS.md (cap enforcement, adaptive detection, critic v2, v5 partition, rate limit, idempotency, worker contract, B613 fix).

## NEEDS_HARSH / skipped
docs/NEEDS_HARSH.md (Docker, E2B, MinIO, release go-ahead); docs/SKIPPED.md (evasion DEV split, injected-run critic rate, Docker/E2B).

## Remaining issues
Three one-off flaky points fixed (list_runs rate limiter isolation). Load test errors at 100 users. Dead-code removal found nothing.

## Failures + handling
Worktree lacked data/scorer_data/ledger: junctions and exclusions added, arm resumed (ledger entry written once, no requests wasted). Injection run hit AllProvidersDown on 20 cases: rerun replayed cache and answered the rest.

## Git
agent-frozen-v5 points at the original freeze commit 1a3a3d8 (verified; no frozen file changed since). Tags force-moved this run: stretch-1..stretch-6 were re-created at merge 2a8bec9 (they were first created this run; old SHAs not recorded). Attribution grep over the last 40 commits: empty. All pushed to origin/main.

## Budgets
LLM requests today (UTC 2026-10-30): groq 120, gemini 71 (caps 120). CI runs ~12, minutes well under 350.

## Next steps
Install Docker to run the infra suite locally; real MinIO; fresh partition for any further agent evaluation; extend injection eval to a harness that produces full injected runs.

## Estimated PRD complete
About 90%.
