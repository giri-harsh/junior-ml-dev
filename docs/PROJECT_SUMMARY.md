# junior-ml-dev — project summary

## 1. One-liner
An autonomous tabular-ML agent for data teams: profiles data, checks leakage, trains and reviews models, and gates deployment on approval.

## 2. Problem & why it's hard
AutoML picks models but misses leakage, overfit and unsafe actions. An LLM agent touching untrusted datasets can be steered by column names or cells. Honest evaluation is hard: results leak into design unless held-out sets are used once.

## 3. Architecture
Flow: planner (scripted or LLM) → runner (step state machine, checkpoints) → 4 MCP servers (data-tools, sandbox-exec, experiments, deploy; 15 tools) → deterministic reviewer → report → approval-gated deploy. API: FastAPI → job queue (SQLite, arq/Redis optional) → worker. Critic (LLM, advisory) reads a numbers-only summary.
Decisions: LLM sees symbolic summaries only (never dataset text); a structural action guard decides (not the model); reviewer is rules, LLM critic advisory; each held-out partition is evaluated once, from a frozen, hash-checked tag, ledgered in `benchmarks/eval_ledger.json`.

## 4. Stack
Python ≥3.11, FastAPI, Pydantic 2, SQLAlchemy/psycopg, pandas 3, scikit-learn, FLAML, LightGBM, `mcp` ≥2.3, PyJWT, OpenTelemetry, arq/Redis/MinIO (optional; CI uses a moto S3 stand-in), React 18 + Vite 5 viewer, Playwright e2e. Docker/compose, GitHub Actions (ci, infra, load, web). No Kubernetes, Terraform or vector store.

## 5. Agentic / LLM specifics
- LLMs: Groq gpt-oss-120b → gpt-oss-20b, Gemini gemini-3.5-flash-lite fallback (`harness/gateway/live.py`). No fine-tuning.
- Planner v2 proposes only train/tune/finish from a symbolic state; steps are `extra="forbid"` Pydantic models; invalid output gets bounded repair, then falls back to the script.
- Checkpointing per step (SQLite/Postgres); resume after kill. Guardrails: untrusted-text sanitiser, `guard()` action policy, code policy, hash-chained audit, single-use approvals.
- Cost controls: 120 requests/provider/UTC day, 2 s spacing, cassettes, circuit breakers; a 429 now fails over after one retry.
- Critic v3: a failed rule check needs a blocker or numeric dissent (schema-enforced).

## 6. Production-readiness
JWT admin cookie, token-bucket rate limit, idempotency keys, graceful SIGTERM worker with dead-letter queue, OTel traces, Prometheus catalog + Grafana JSON, bandit/pip-audit/SBOM in CI, gitleaks, coverage floor 91%. 519 test functions defined (`grep -rn "def test_" tests | wc -l`); the last full local gate reported 497 passed, coverage 92%. Deployment: local compose only. No live URL (Hugging Face returned 402 for a free Docker Space). `main` CI is red at last check (mypy on the optional `e2b` import, fix pending).

## 7. Evals & metrics
| metric | value | how measured | set size |
|---|---|---|---|
| Normalized score, LLM planner (FLAML=1) | 0.989 [0.950, 1.012] | `benchmarks/results/agent_v5_llm.json` | 10 tasks |
| Same, scripted planner | 0.987 [0.949, 1.011] | `agent_v5_scripted.json` | 10 tasks |
| Agent − linear (paired) | +0.190 [0.076, 0.316] | `agent_v5_llm.json` | 10 |
| Agent − FLAML (paired) | −0.011 [−0.050, 0.012] | same | 10 |
| Latency per task, LLM arm | p50 135 s, p95 226 s | same | 10 |
| LLM cost / requests | $0 (free tiers); 130 requests, 19,562 tokens | same | 10 tasks |
| Leakage recall / false alarms | 29/30; 0/30 | `leakage_v3.json` | 30 + 30 twins |
| Injection, real LLM | 0/49 attacker actions, 0 unsafe | `injection_llm_v2.json` | 49 |
| Fresh evasion set | 0/14 actions, 0 unsafe; scanner flagged 1/14 (8/8 on tuned dev) | `injection_llm_v3.json` | 14 |
| Injected full runs | 5/5 finished, 0 unsafe, critic flagged 3/5 | `injected_runs_v1.json` | 5 |
| Critic, fresh set v2 | recall 15/20 [0.53, 0.89], false alarms 0/25; 8 items no output; 0/4 on rule-fail items | `benchmarks/critic_v2/critic_v2_eval.json` | 53 |
| Critic, fresh set v1 | recall 10/15, false alarms 1/19 | `critic_v6.json` | 38 |
| Load (CI runner) | 5 users p95 210 ms; 25 users 75 req/s, p95 1.5 s; 100 users 17.8% errors | `load_v1.json` | locust |
Chaos: a `docker kill` of the worker mid-run followed by resume is tested in `infra.yml` (CI green); no recovery time recorded.

## 8. Scale claims
- "Each held-out arm evaluated once, frozen tag": VERIFIED (ledger, `agent-frozen-v5` tag).
- "Matches an AutoML baseline": PARTIAL — the CI crosses zero; no win is claimed.
- LLM planner better than scripted: UNVERIFIED (paired +0.001, CI includes 0).
- Load numbers: VERIFIED for a shared runner (CI run 40945724068); capacity claims UNVERIFIED.
- Injection robustness: PARTIAL — small sets (49, 14, 5); upper bounds 8.6% to 21.5%.
- Docker sandbox isolation: VERIFIED in CI; E2B isolation: UNVERIFIED (no live run recorded yet).
- Live demo: UNVERIFIED (not deployed).
- "$0 cost": VERIFIED as recorded, but only because of free tiers.

## 9. Gaps
Only 10 tasks per partition; critic dissents on unambiguous rule failures (0/4); errors above 25 users; no cloud deployment or live URL; E2B and real MinIO unexercised; red CI on `main`; no LLM-call p95.

## 10. Interview risks
1. *Does it beat AutoML?* No: −0.011 vs FLAML, CI [−0.050, 0.012]; it matches it and beats linear by 0.19.
2. *Is the LLM useful?* Not measurably: +0.001 over scripted; it only orders model families.
3. *Why trust 0/49 on injection?* Wide bounds; the production planner never sees dataset text; the scanner caught only 1/14 fresh payloads, so the structural guard carries the result.
4. *Is the benchmark contaminated?* Partitions v1–v5 were burned for design; fresh sets are hash-committed; the critic was tuned on v5-era failures (reported post hoc).
5. *Why 130 requests for 40 proposals?* 90 were retried failures; failure statuses weren't stored, so the cause is inferred. Fixed afterwards, not rerun.
