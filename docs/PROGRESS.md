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
