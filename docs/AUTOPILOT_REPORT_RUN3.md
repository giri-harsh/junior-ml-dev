# AUTOPILOT REPORT, run 3 (S16-S19)

**Planners behind every number: SCRIPTED (deterministic, no LLM). No real LLM was called and none was available (no keys, no Ollama). The mock-LLM planner path is unit-tested only.**

## Capability probe
Docker/compose: no. GROQ/GEMINI/ANTHROPIC/OPENAI/E2B keys: none. Ollama, gitleaks, act: none. Disk 38.8 GB free, 16 cores, 15.6 GB RAM. Consequence: S17 and S19 became code plus tests that auto-skip, S18 was skipped.

## Implemented
| Sprint | Status | Tag |
|---|---|---|
| S16 correctness: FLAML refit on all rows, FLAML bundle, simplicity tie-break, detector fix #1, v2 benchmark | done | s16-done, agent-frozen-v2 |
| S17 infra: SQL (Postgres) run store, arq queue + worker, MinIO store, compose api+worker, infra tests | code + unit tests done; live services NOT RUN | s17-done |
| S18 real LLM planner | SKIPPED (no key, no Ollama) | none |
| S19 sandbox + CI: Windows job-object limits, CI workflow | partial: Docker/E2B backends NOT RUN; CI YAML only validated | s19-done |

## Verification (commands run)
- `ruff check . && ruff format --check . && mypy && pytest -q -m "not infra"` before the merge: 356 passed, 5 infra deselected, clean (one format nit fixed, then re-linted).
- Secret scan clean (regex fallback). Real eval ledger guarded by an mtime test; agent_v1.json untouched.
- Dev-partition recheck of the leakage change (`benchmarks.tune_leakage`): recall unchanged (23/24 group_leak 2/3 as before), twin false alarms 0/24, real_dev 0 medium/high.
- FLAML bundle loaded and predicted identically for 20 rows in a fresh `python -I` process.
- NOT run: docker compose, Postgres, Redis, MinIO, `docker kill` resume test, container deploy test, `act`, any live LLM. Commands in KNOWN_GAPS.

## Numbers (agent_v1.json, agent_v2.json; scorer test scores; scripted planner)
| | v1 (headline) | v2 (post-hoc, fixes informed by v1 failures) |
|---|---|---|
| Agent normalized, 10 tasks | 1.037 [0.994, 1.085] | 1.053 [1.008, 1.105] |
| Agent minus linear (paired) | +0.213 [0.030, 0.394] | +0.228 [0.049, 0.409] |
| Agent minus FLAML (paired) | +0.037 [-0.006, 0.085] | +0.053 [0.008, 0.105] |
| Pass vs linear (ADR-005) | 6/10 | 6/10 |
- Paired v2 minus v1: +0.015 [-0.0001, 0.037], n=10: no reliable improvement. Gains: wine_quality 0.420 -> 0.398 (MAE), blood-transfusion 0.459 -> 0.472 (PR-AUC); other tasks within 0.001.
- v2 still equals linear on adult, credit-g, vehicle; tie-break did not change those (linear already simplest and best by validation).
- v2 agent minus FLAML now excludes 0, but FLAML at the same 30 s is one of the agent's candidates (now refit on all rows), so this reflects FLAML plus selection, not a stronger method.
- v2 churn still got REQUEST_CHANGES (group_leakage on number_customer_service_calls). Diagnosis after v2: the id-name regex matched "customer" inside a measure name; fixed afterwards (decision 90), so v2 does not include that fix.
- v2 cpu_act: detect_leakage exceeded its 60 s budget, so no leakage check ran and the reviewer approved anyway; fixed afterwards (new `leakage_checked` reviewer check). Not rerun.
- Dev partition: v1 agent 1.203 [1.031, 1.466]; v2 agent in `agent_dev_v1.json`.
- Cost/latency: 0 tokens, $0. Per-task agent time 44-134 s in v1 (per_task.latency_s in each file). No real-LLM, no llm_v1, no real-LLM injection numbers. Injection headline remains the simulated-agent number (0/41 unsafe executed; scanner v1 held-out evasion 5/8, 0/388 benign false positives).
- Infra resume test (Postgres + arq + docker kill): NOT RUN. The scripted-runner kill/resume test on SQLite still passes.

## Decisions
84-94 in `docs/DECISIONS.md`: numeric-group role floor (84), ordinal label_noise skip (85), FLAML refit via max_iter=1 starting point + bundle (86), 0.5% relative simplicity tie-break fixed a priori (87), FLAML n_jobs fixed at 4 (88), v2 labelling (89), post-v2 fixes (90), SqlRunStore (91), arq (92), Windows job limits (93), S18 skipped (94).

## Skipped / stubbed / not run
S18 entirely; Docker/E2B sandbox; live Postgres/arq/MinIO/compose/container deploy; `act`; gitleaks binary. Resume commands: `docs/SKIPPED.md` (Run 3 additions) and `docs/KNOWN_GAPS.md`.

## Remaining issues
- Subprocess sandbox: job limits only, NOT isolation. README states this.
- minio healthcheck in compose uses `curl` (image may lack it); arq re-delivery delay after a worker kill is unverified.
- Post-v2 fixes (strict id naming, `leakage_checked`) are unevaluated on held-out; a v3 would need a new unseen partition.
- Leakage detector v1 held-out numbers (`leakage_v1.json`) predate detector fixes 84-85 and 90; the headline file was not rerun.

## Failures hit and how handled
- I ran `ruff format .` repo-wide while the v2 benchmark was running; it only touched my in-progress files, the running process and the tagged commit were unaffected, and I then restricted formatting to touched files.
- A shell `sed` with `\r\n` mangled a test; repaired with Python and chr-free bytes literals.
- arq raised redis errors instead of OSError and retried 5 times; producer now fails fast and catches `RedisError` (lazy import so the base install works).
- Benchmark `uv run` rebuilds during v2 were light; FLAML timing may still be mildly load-sensitive (cpu_act leakage timeout above).

## Git
Branches s16-correctness, s17-s19-infra merged into main with --no-ff. Tags s16-done, s17-done, s19-done, agent-frozen-v2 (no s18 tag). Last commit: see `git log -1` on main (merge 7bc2ab0 plus this report). Tree clean after the report commit. No remote, nothing pushed.

## Wall
None.

## Next steps
1. Provide a provider key or Ollama and run S18 (resume command in SKIPPED.md).
2. On a machine with Docker: `python scripts/tasks.py up app` then `test-infra`.
3. v3 only with a new unseen partition: cover the two post-v2 fixes.

## Estimated PRD completion
About 55% by sprint count (estimate, not measured): the agent, servers, benchmark and safety layers exist and run offline with a scripted planner; the real-LLM, real-sandbox and live-infra parts are written but never run.
