# Skipped / stubbed items

Revisit pass (S12-S14 run): each item below was re-checked against what is reachable without
Docker, Postgres, Redis, E2B or an LLM key; none became reachable.

| Item | Status | Why | Resume |
|---|---|---|---|
| PRD S6 chart candidates (Vega-Lite/Altair) | skipped | Run report uses hand-built inline SVG bars instead; no declarative chart pipeline or claim-verified chart captions | `uv add altair vl-convert-python`, implement `datastory/charts/` per PRD S6 |
| PRD S9 React/Vite UI, Playwright e2e | replaced by a minimal static page `/ui` | No node toolchain exercised; the static page covers login, upload, run, status, approval, report; no browser e2e was run | scaffold `apps/web` per PRD S9 |
| E2B backend, Docker sandbox execution, egress/escape tests | stub | No Docker, no E2B key | build image, `JMD_SANDBOX=docker`, add `integration` tests |
| arq + Redis job queue, Postgres run store/approvals/audit | stub (SQLite used) | Redis/Postgres unavailable | implement `ArqJobQueue`, run `tests/unit/test_queue.py` contract against it |
| Real LLM planner runs | NOT RUN | No provider key | set `GROQ_API_KEY` or `GEMINI_API_KEY`, record fixtures, run the LLM planner on <=3 dev tasks |
| Agent roles beyond planner + deterministic reviewer (LLM reviewer, critic) | skipped | Needs an LLM | PRD S15-S16 |
| Predict-in-sandbox scorer (agent supplies code that predicts inside the sandbox) | skipped | Needs working sandbox | PRD S11 |
| Explainability (SHAP/permutation importance), PDF bundle | skipped | Not on the P1-P8 priority list | PRD S19-S21 |
| Load test, tracing backend (OTel), dashboards | skipped | Needs services; logs, per-step trace JSON and /metrics exist | PRD S24 |
| Docker compose / container deploy start | NOT RUN | Docker unavailable | `docker compose -f data/deploy/<run>/<model>/docker-compose.yml up -d --build` |
| Ablations and stress runs of the agent benchmark | skipped | Eval-once: only one frozen evaluation exists | new freeze hash needs a new, unseen partition |
