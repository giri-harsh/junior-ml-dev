# Skipped / stubbed items

Revisit pass (S12-S14 run): each item below was re-checked against what is reachable without
Docker, Postgres, Redis, E2B or an LLM key; none became reachable.

| Item | Status | Why | Resume |
|---|---|---|---|
| Item | Status | Why | Resume |
|---|---|---|---|
| PRD S6 chart candidates (Vega-Lite/Altair) | DONE (run 10-11) | Implemented as NEW module in `datastory/charts/` with 9 templates, ranking, SVG export; integrated into data_story MCP endpoint (run 11, commit 43b5252) | HTML export with embedded specs (PRD S7.5) |
| PRD S9 React/Vite UI, Playwright e2e | PARTIAL (run 11) | Playwright e2e infrastructure added (commit 89532ab); 7 tests for existing viewer (login, runs list, navigation); upload UI (S9.1-S9.3) not yet implemented | scaffold upload/story pages per PRD S9.1-S9.3 |
| E2B backend, Docker sandbox execution, egress/escape tests | stub | No Docker, no E2B key | build image, `JMD_SANDBOX=docker`, add `integration` tests |
| arq + Redis job queue, Postgres run store/approvals/audit | stub (SQLite used) | Redis/Postgres unavailable | implement `ArqJobQueue`, run `tests/unit/test_queue.py` contract against it |
| Real LLM planner runs | NOT RUN | No provider key | set `GROQ_API_KEY` or `GEMINI_API_KEY`, record fixtures, run the LLM planner on <=3 dev tasks |
| Agent roles beyond planner + deterministic reviewer (LLM reviewer, critic) | skipped | Needs an LLM | PRD S15-S16 |
| Predict-in-sandbox scorer (agent supplies code that predicts inside the sandbox) | skipped | Needs working sandbox | PRD S11 |
| Explainability (permutation importance) | DONE | Implemented in `mcp_servers/experiments/service.py::explain_model` with honest refit-on-75% holdout; called in agent report | integrated into reports (already done) |
| PDF bundle (WeasyPrint) | partially done (run 11) | Code implemented (commit 500d0b8) but WeasyPrint needs system libs (GTK/Pango) not available on Windows dev machine; 13 unit tests written, cannot run locally | PRD S21: install GTK libs per https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows, or test in Docker/Linux CI where libs are available |
| Load test, tracing backend (OTel), dashboards | skipped | Needs services; logs, per-step trace JSON and /metrics exist | PRD S24 |
| Docker compose / container deploy start | NOT RUN | Docker unavailable | `docker compose -f data/deploy/<run>/<model>/docker-compose.yml up -d --build` |
| Ablations and stress runs of the agent benchmark | skipped | Eval-once: only one frozen evaluation exists | new freeze hash needs a new, unseen partition |

## Run 3 additions
| Item | Status | Why | Resume |
|---|---|---|---|
| S18 real LLM planner | DONE in run 4 (Groq gpt-oss primary, Gemini fallback; v3 LLM arm, bake-off, real-LLM injection eval; cassettes in tests/cassettes) | | |
| S19 Docker sandbox backend execution, E2B backend, scripted step that runs agent-written feature code in a sandbox | NOT RUN | No Docker, no E2B key | see KNOWN_GAPS (sandbox row) |
| S17 live compose, Postgres/arq/MinIO verification, container deploy test | NOT RUN | No Docker | see KNOWN_GAPS (infra row) |

## Run 4 additions
| Item | Status | Why | Resume |
|---|---|---|---|
| Docker work (compose up app, test-infra, docker-kill resume, container deploy) | WALL: Docker Desktop not installed | Run-4 rules forbid installing system software | install Docker Desktop yourself, then `python scripts/tasks.py up app` and `python scripts/tasks.py test-infra` |
| E2B backend | WALL: no E2B_API_KEY | needs an account/key | create a key at e2b.dev, set E2B_API_KEY, run the sandbox test suite against the E2B backend |
| v3 re-evaluation after any further change | not allowed | eval-once | needs a new unseen partition (v4) |

## Run 6 additions
| Item | Status | Why | Resume |
|---|---|---|---|
| S27 evasion DEV split with the real LLM | NOT RUN | 50-request budget is spent on the 41-case suite + 8 held-out payloads (49 requests); DEV payloads were already used to tune the scanner | extend `benchmarks/injection/llm_eval.py` with `evasion.DEV` and raise the cap |
| S27 "critic flag rate on injected runs" | NOT APPLICABLE | the critic reviews finished runs; injection cases are single-step proposals with no run to review | needs an end-to-end injected run harness |
| Docker / E2B / real MinIO | WALL | see NEEDS_HARSH.md 1-3 | |
| Stretch 8 dead-code removal | nothing to remove | vulture at confidence 80 reports nothing; 60% hits are FastAPI handlers | |
