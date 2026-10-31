# PROGRESS (run 3, S16-S19). Read this + `git log -5` first on resume.

## Capability probe (2026-10-29 run start)
docker: NO | compose: NO | GROQ/GEMINI/ANTHROPIC/OPENAI/E2B keys: all NO | ollama: NO | gitleaks: NO | act: NO
disk free 38.8 GB | cores 16 | RAM 15.6 GB
=> S17: code + infra-marked tests + compose syntax only. S18: skipped (no key, no ollama). S19: harden subprocess sandbox + CI yml (YAML validated only).

## Status
| Sprint | Status | Next |
|---|---|---|
| S16 correctness | in progress | items 1-3 then 4, then v2 benchmark |
S16: items 1-4,6 done on branch s16-correctness (detector fixes, FLAML refit+bundle, tie-break); dev partition rerun -> benchmarks/results/agent_dev_v1.json. NEXT: gate, merge, tag s16-done + agent-frozen-v2, run `python -m benchmarks.agent_benchmark --final --version v2` ONCE (resume only with --resume), then render results, then S17.
S16 merged (s16-done, tag agent-frozen-v2 @08c3217). v2 benchmark launched ONCE (ledger agent:197c7b2b..), log /tmp/bench_v2.log; if crashed: `python -m benchmarks.agent_benchmark --final --version v2 --resume`.
S17/S19 code written on main working tree (uncommitted until v2 finishes): sql_store, queue_arq, minio_store, compose api/worker, infra tests, winjob, CI yml. NEXT after v2: `uv lock` (infra extra), full gate, branch s17-s19-infra commit/merge, tags s17-done s19-done, S18 skipped (log), render results, report.
RUN 3 COMPLETE: S16 done (s16-done, agent-frozen-v2; agent_v2.json), S17/S19 code merged (s17-done, s19-done), S18 skipped (no key/ollama). Report: docs/AUTOPILOT_REPORT_RUN3.md. Nothing in progress.
RUN 4 COMPLETE: s18-done, agent-frozen-v3, eval-v3-done, s20-done; pushed to private origin giri-harsh/junior-ml-dev. Docker/E2B items are WALL (see docs/AUTOPILOT_REPORT_RUN4.md). Nothing in progress.

## RUN 5 (S21-S24) - STOPPED EARLY: usage limit reached
Done (local, committed on main, NOT pushed, full gate NOT run since the CV/LLM-v2 changes):
- S21: ci.yml + infra.yml pushed earlier (fa7b1d1..fc63b67). CI runs used so far this run: ~6 (ids 40826418285, 40826419757, 40826494410/488, 40826606193/194), all failed or cancelled; fixes found by CI: YAML colon in step name, MinIO image tag missing on Docker Hub/quay (now quay latest, unpushed), mypy extra deps + numpy stubs (fixed), compose needs SCORER_SECRET (fixed), runner path guard rejected absolute paths on Linux (fixed locally, unpushed). Infra/compose jobs have NEVER passed yet.
- Docker sandbox hardening, sandboxed `engineer_features` step (opt-in), kill/resume acceptance test written; none run in Docker.
- S22 code: CV selection (k=5/3, 1-SE rule) in experiments + agent; LLM planner v2 (symbolic state, dedupe re-prompt, min-exploration) with unit tests. Dev before/after NOT run. LLM requests used today: groq 80, gemini 8.
Not started: S23 (v4 partition, agent-frozen-v4, evals), S24 (explainability, LLM reviewer, OTel), README update, run-5 report.
Next: run full gate, push, `gh run list`, fix infra.yml failures; then S22 dev runs (python -m benchmarks.agent_dev --planner llm1/llm2 --selection ...), S23, S24.
RUN 5 COMPLETE: S21-S24 done and pushed; see docs/AUTOPILOT_REPORT_RUN5.md. CI runs ~18, ~77 min.

## RUN 6 (S25-S30 + stretch) - started 2026-10-30
Budgets: CI runs used 0->2 (S25 push); LLM requests today: see data/llm_usage.json (cap 120/family/UTC day).
S25 DONE (tag s25-done): leakage v3 (linear_combination detector, adaptive bounded detection, eval4: recall 29/30, twin FA 0/30). Cap bug fixed (gateway max_requests).
NEXT: S28 non-LLM parts now (v5 partition, baselines, freeze, scripted arm); LLM parts (S27 injection rerun, v5 LLM arm, critic eval) after UTC reset at 00:00 UTC (05:30 IST): Gemini 107/120 and Groq 120/120 used on 2026-10-29 UTC.
S26 DONE (tag s26-done).
S28: agent-frozen-v5 tagged at 1a3a3d8; scripted arm launched (log /tmp/v5_scripted.log, chain /tmp/v5_chain.log). If it crashed: python -m benchmarks.agent_benchmark --final --version v5 --planner scripted --resume. LLM arm AFTER UTC reset.
RUN 6 RESUME (2026-10-30 UTC): stretch 1-6 merged+tagged, CI green (ci 40953422203, infra 40953422200). agent-frozen-v5 NOT re-pointed (still 1a3a3d8; no FREEZE_FILES changed since). v5 LLM arm running from worktree ../jmd-v5-frozen, log /tmp/v5_llm.log; if crashed: cd ../jmd-v5-frozen && python -m benchmarks.agent_benchmark --final --version v5 --planner llm --resume. Afterwards copy benchmarks/results/agent_v5_llm.json, tests/cassettes/v5_llm.jsonl and benchmarks/eval_ledger.json to main, commit results only, remove worktree.
RUN 7 (2026-10-30): item 1 request inflation fixed+merged (tag r7-item1-done, decision 136); item 2 critic v3 + fresh set results merged (r7-item2-done, decision 137). Item 3 code committed on branch injection-completion (fresh set hash e45a51c0, injected_runs harness); LLM parts WAIT for UTC reset (Gemini 111/120, Groq 120/120 on 2026-10-30): background chain /c/tmp/r7_chain.sh waits for 2026-10-31 00:00 UTC then runs `python -m benchmarks.injection.llm_eval --fresh` and `python -m benchmarks.injection.injected_runs` (logs /c/tmp/r7_fresh.log, /c/tmp/r7_runs.log, /c/tmp/r7_chain.log). If it died: rerun those two commands after reset. Nothing pushed yet this run. Then: item 4 RESUME_BULLETS, item 5 docs, gate, merge, push, v0.2.0.
RUN 7 RESUME COMMANDS (after 00:00 UTC 2026-10-31; caps: Groq/Gemini 120 each; chain script /c/tmp/r7_chain.sh may have already run them, check benchmarks/results for injection_llm_v3.json and injected_runs_v1.json first):
 - evasion DEV + fresh held-out (run once, <=40 req): `PYTHONUTF8=1 uv run python -m benchmarks.injection.llm_eval --fresh`
 - 5 injected full agent runs (<=30 req): `PYTHONUTF8=1 uv run python -m benchmarks.injection.injected_runs`
 - follow-up docs/release (v0.2.1): `uv run python scripts/render_metrics.py && uv run python scripts/render_results.py`, add the injection numbers to README/RESUME_BULLETS/KNOWN_GAPS, run the gate, merge --no-ff, tag v0.2.1, `gh release create v0.2.1`.
RUN 9 (multi-agent, started 2026-10-30 06:25 UTC): LIVE_E2B=no, LIVE_HF=no, LLM_AVAILABLE=no. Agents A (ws-a-e2b), B (ws-b-demo), D (ws-d-critic) dispatched in worktrees; merge order A -> B -> D -> C via branch `integration`, verifier E per branch. Stale r7 waiter killed. Budget ledger: `uv run python scripts/budget.py status`.
Agent C (injection) waits for the cap reset: a one-shot session cron fires 2026-10-31 05:37 IST (00:07 UTC). If the session is gone, dispatch C by hand after 00:00 UTC 2026-10-31: worktree branch ws-c-injection from main, verify `python -m benchmarks.injection.fresh_v2` == benchmarks/injection/fresh_v2.sha256 (e45a51c0...), `python scripts/budget.py reserve gemini 25` (and groq), then `PYTHONUTF8=1 python -m benchmarks.injection.llm_eval --fresh` then `PYTHONUTF8=1 python -m benchmarks.injection.injected_runs`, commit results (injection_llm_v3.json, injected_runs_v1.json, cassettes), verify, merge, docs refresh, `gh release create v0.3.1`. D's eval: command in docs/ws/D.md after merge.


## RUN 10 (gap closure, started 2026-10-31)
Priority order: (1) complete Run 9 integration merge (done), (2) PRD S6 charts, (3) PRD S9 web UI, (4) explainability/PDF, (5) other PRD gaps not blocked.
Budgets: Groq 25/120, Gemini 25/120 used (Run 9 Agent C), CI 0/20, e2b 0/60, hf_build 0/6.
STATUS: S6 DONE (commit 4787e3f), 15 tests passing. NEXT: S9 React/Vite scaffold.


## RUN 10 SUMMARY
Completed 2026-10-31:
- Run 9 integration merged to main (commits: A=E2B backend, B=HF demo, D=critic v2 eval, C=injection completion)
- PRD S6 declarative charts: 9 Altair/Vega-Lite templates, ranking, SVG export (15 tests passing)
- Explainability verified: permutation importance already implemented in experiments MCP
- Documentation updated: SKIPPED.md and PROGRESS.md reflect current state
- Budget used: Groq 25/120, Gemini 25/120 (Run 9 Agent C only)

Next priorities for future runs:
1. PDF generation (WeasyPrint) per PRD S21
2. Playwright e2e tests for web UI per PRD S9.5
3. Integration of S6 charts into data story endpoint
4. Other PRD gaps not blocked by missing services
