# Autopilot report - run 7 (final quality pass -> v0.2.0)

## CI
- Start: ci 41000366212 success. Item 3 merge: ci 41008428375, infra 41008428394 success.
- Docs merge: ci 41010939801 success; final commit ci 41012173499 success; v0.2.0 tagged on it; local gate 438 passed, coverage 92.04% (floor 91).
- Actions budget this run: 6 runs, about 40 min (limit 15 / 200).

## 1. Request inflation (fixed, decision 136)
| Arm | Requests | Proposals | Repairs | Failed attempts | Per task |
|---|---|---|---|---|---|
| v4 LLM | 50 | 39 | 1 | 10 | 5.0 |
| v5 LLM | 130 | 40 | 0 | 90 | 13.0 |
v5 had no repair, re-prompt or critic calls: 90 of 130 were failed attempts retried by the gateway
(7 of 10 tasks cost exactly 16 = 3 failed attempts per proposal). The failure statuses were never
stored, so 429-vs-5xx cannot be proven for v5 (not rerun; reported as-is in RESULTS.md).
Fix: failed attempts are recorded by status (`llm_error_statuses`, `llm_retries`), a 429 fails over
after one retry; regression tests added. The frozen gateway changed, so the next agent evaluation
gets a new freeze hash.

## 2. Critic v3 (decision 137)
Schema rejects silent approval of a failed rule check (blocker naming the check, or numeric dissent;
one repair, else default to the rules). Fresh planted set, 38 items (15 planted), hash-committed
before any call (`6595774668473af9`). Recall 10/15 (Wilson 0.42-0.85); false alarms 1/19 clean
(0.01-0.25); 4 clean items not run (40-request cap, Gemini 429 bursts forced a completion pass with
the same prompt). By type: unresolved leakage 3/3, tiny test 2/2, partial leakage 2/2, gap beyond
range 2/3, CV instability 1/2, rule-fail baseline margin 0/3.
Set-design flaw: I generated the three rule-fail items with random margins the model could defend
numerically, so it dissented (allowed by the schema). Reported as is; v5 agreement (18/20) is burned
and post-hoc.

## 3. Injection completion: PENDING (decision 138)
Groq 120/120 and Gemini 111/120 used on 2026-10-30 UTC. Fresh 14-payload evasion set is
hash-committed (`e45a51c0`), unread. A background chain (`/c/tmp/r7_chain.sh`) waits for 00:00 UTC
2026-10-31; resume commands are in docs/PROGRESS.md:
- `PYTHONUTF8=1 uv run python -m benchmarks.injection.llm_eval --fresh` (DEV + fresh, run once)
- `PYTHONUTF8=1 uv run python -m benchmarks.injection.injected_runs` (5 full runs, critic flag rate)
Run-6 numbers stand: 0/49 attacker actions, 0 unsafe executed.

## Resume bullets (verbatim, docs/RESUME_BULLETS.md)
See the file: 5 bullets (v5 benchmark 0.989 vs FLAML = 1 CI 0.950-1.012 "matched", +0.190 over
linear; leakage 29/30 and 0/30; injection 0/49 and 0 unsafe; load p95 210 ms / 1.5 s; 438 tests, 92%
coverage, critic 10/15 and 1/19). No win claimed where a CI crosses zero.

## Decisions
136 request inflation fix; 137 critic v3 and the fresh set; 138 release split (v0.2.0 now, injection
as v0.2.1); 139 run-8 keys missing.

## Skipped / NEEDS_HARSH
Skipped: injection completion (cap), 4 clean critic items (cap). NEEDS_HARSH: E2B key, HF token
(run 8), real MinIO, cloud-deploy account.

## Git
Tags (all new, no `-f`): r7-item1-done, r7-item2-done, r7-item3-code, r7-docs-done. Attribution grep
over the last 60 commits: empty. Pushed to origin/main.

## Budgets
LLM today (UTC 2026-10-30): groq 120, gemini 111 (critic 40, earlier runs). CI as above.

## Estimated PRD complete
About 91%.
