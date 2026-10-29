# AUTOPILOT REPORT (run 2: S12-S15)

**HEADLINE: the agent that was benchmarked is a SCRIPTED planner. No LLM was called, real or mocked, in any benchmark number below.** An LLM planner exists and was tested only against a mock provider. Sprint numbers are this run's labels.

## Implemented
| Sprint | Status | Tag |
|---|---|---|
| S12 experiments MCP (train/tune/refit/evaluate/predict/compare, tracking) | done | s12-done |
| S13 agent harness: planners, runner, checkpoints/resume, budgets, guardrails, audit, report | done | s13-done |
| S13 deploy MCP: bundle + predict service + model card; approval-gated staging | done, containers NOT started | s13-done |
| S13 job queue (SQLite, leases) + runs API + /metrics; arq | queue done, arq STUB | s13-done |
| S14 agent dev partition + eval-once agent benchmark + injection scanner v1 | done | s14-done, agent-frozen |
| S15 results, README (Mermaid), demo script, minimal `/ui` page, approval resume API | done | s15-done |
PRD completion: roughly half by sprint count (estimate, not measured); remaining list below.

## Files changed (important)
`mcp_servers/{experiments,deploy}/`, `harness/agent/`, `harness/queue.py`, `harness/obs.py`, `apps/api/routes/runs.py`, `apps/api/static/index.html`, `harness/policies/untrusted.py`, `benchmarks/{agent_dev,agent_benchmark}.py`, `benchmarks/injection/evasion.py`, `scripts/{demo,render_results}.py`, `docs/{RESULTS,SKIPPED,KNOWN_GAPS,DECISIONS}.md`, `docs/adr/016-*.md`.

## Verification (commands run)
- `uv run ruff check . && uv run mypy && uv run pytest -q` before every merge: final 327 passed, ruff and mypy clean (`mypy .` also covers tests, which are outside the project's mypy scope; 11 old test-only annotations fail it, decision 66).
- `python scripts/secret_scan.py` clean (regex fallback; gitleaks absent).
- Kill test: `harness.agent.cli` hard-killed (`os._exit(137)`) after step 6, rerun resumed, no step repeated, final model equals an uninterrupted run.
- Chaos tests pass: constant target, tiny data, malformed CSV, all-missing column, high-cardinality IDs, blocked scorer path, leaked column dropped, step and wall budgets, deploy without approval.
- `uv run python scripts/demo.py --deploy` ran end to end. Not run: Docker, Postgres, Redis, E2B, CI, any browser e2e. The report HTML and `/ui` were not viewed in a browser.

## NUMBERS (all from `benchmarks/results/*.json`; table in `docs/RESULTS.md`)
- **Agent benchmark, SCRIPTED planner, LLM none** (`agent_v1.json`, freeze hash 66e3796c63e0, one evaluation, 0 infra retries): normalized score 1.037 [0.994, 1.085] over 10 tasks vs linear 0.824 [0.613, 1.044]. Paired agent minus linear +0.213 [0.030, 0.394]. Paired agent minus FLAML +0.037 [-0.006, 0.085], i.e. not distinguishable: FLAML at the same 30 s is one of the agent's candidates. Pass rule vs linear (ADR-005) 6/10, Wilson 95% [0.31, 0.83]; the agent equals linear on adult, credit-g and vehicle and so cannot clear the 2% margin.
- wine_quality: agent 0.420 vs FLAML baseline 0.400 (lower is better); the agent trains FLAML on an 80% split without refit. churn and wine_quality got reviewer REQUEST_CHANGES for the two carried leakage false positives.
- Dev partition (5 real_dev sets, design may use): agent normalized 1.203 [1.031, 1.466] (`agent_dev_v0.json`).
- Run cost and latency: tokens 0, cost $0 (no LLM). Wall time per task 44-134 s, mostly the 30 s FLAML budget, 13-14 steps per run (`agent_v1.json` per_task).
- Injection (`injection_v0.json`, `injection_v1.json`): template payloads flagged 35/35; the 6 original evasion payloads now 4/6 (was 2/6). New evasion split: dev 3/8 -> 8/8 (scanner tuned on these), held-out 0/8 -> 5/8 (read as counts only), false positives 0/388 benign strings including 378 real column names. Unsafe actions executed 0/41 (simulated compliant agent vs structural guard; no LLM behaviour measured).
- Leakage (unchanged, `leakage_v1.json`): eval2 recall 23/24, twin false alarms 0/24; churn and wine_quality false positives carried, not retuned.

## DECISIONS
66-83 in `docs/DECISIONS.md`. Main ones: in-process tool calls with per-server stdio smoke tests (69); planner proposes symbolic steps and never sees column names or cell values (70); deploy blocked -> run `awaiting_approval`, resume with token, service re-consumes token (72); "deploy" stages and smoke-tests, never starts containers (73); freeze hash covers code files and the ledger key is claimed before any task runs (77).

## SKIPPED / STUBBED / NOT RUN (`docs/SKIPPED.md`, `docs/KNOWN_GAPS.md`)
- NOT RUN: real LLM planner (no key), docker compose and container deploy, Postgres, Redis, E2B, CI, gitleaks. Verify commands are in KNOWN_GAPS.
- STUB: arq job queue (raises), E2B backend, Postgres stores, MinIO store.
- Skipped: Vega-Lite charts (hand-built SVG bars instead), React UI (static `/ui` page instead), LLM reviewer/critic roles, predict-in-sandbox scorer, explainability and PDF bundle, load test and tracing backend, benchmark ablations (eval-once).
- Revisit pass done: nothing newly reachable.

## Remaining issues / KNOWN GAPS
- Local subprocess sandbox is not isolation; the scripted planner never runs agent-written code, so that path is untested end to end.
- FLAML models cannot be bundled for deploy; the agent's FLAML candidate is not refit on all rows.
- ADR-007 limitation 6 ledger incident (S5) is carried unchanged.
- One FLAML-based benchmark ran while light doc work shared the CPU (decision 81); not rerun.

## FAILURES HIT AND HOW HANDLED
- A `.where` int mask, an eager dict default and Windows text-mode line endings broke three tests; fixed in the tests, not the code.
- Reviewer failed linear against itself (2% margin); fixed the check (decision 71) before the freeze.
- LLM token usage was attributed to the wrong step; fixed in the runner before the freeze.
- Wiring test written after the freeze tag; I deleted and recreated the `agent-frozen` tag on the new HEAD before any evaluation (tests are outside the freeze hash).
- Bash heredoc quoting failed twice; used Write/Edit.

## GIT
Branches s12..s15 merged into main with --no-ff. Tags s12-done..s15-done, agent-frozen. No remote; nothing pushed. Last sha: see `git log -1`.

## WALL
None.
