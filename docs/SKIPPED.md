# Skipped / stubbed items

| Item | Why | Resume |
|---|---|---|
| PRD S6 chart candidates + Vega-Lite/Altair rendering, S7.5 HTML export | Not reached; large surface, no verifier dependency | `uv add altair vl-convert-python`, then implement `datastory/charts/` per PRD S6 |
| PRD S9 React/Vite UI, Playwright e2e | No node toolchain exercised; UI is outside the autopilot's verifiable scope | scaffold `apps/web` per PRD S9 |
| PRD S10 E2B backend, S11 predict-in-sandbox, S12 experiments/deploy MCP, S14 arq+Postgres harness, S15-S16 agent runs, S19-S21 explainability/deploy/bundle, S24 observability/load, S25-S28 agent benchmarks | Need E2B/Docker/Postgres/Redis/LLM keys (none available) or depend on agent runs | see KNOWN_GAPS.md for service-specific verify commands |
