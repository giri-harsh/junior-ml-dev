# ADR-015: Scope cuts

Status: accepted (S1). Source: PRD §0.

| Area | Decision |
|---|---|
| MCP servers | 4: sandbox-exec, data-tools (viz merged), experiments (MLflow), deploy |
| Durability | arq + Postgres checkpoints, step key `(run_id, step)`, DB heartbeat reaper |
| Sandbox | E2B (internet off) with a LocalDocker backend for dev and fallback |
| Infra | docker-compose `micro` and `full` profiles only. No K8s, Loki, Temporal |
| Auth | single env-configured admin; single-use approval tokens; hash-chained audit log |
| Benchmark | tabular classification and regression; normalized score vs FLAML; no Kaggle percentile |
| Stretch | Ask-your-data, fairness, drift, ticket-to-PR, UMAP, docs-rag, github MCP, time-series/text, K8s |

## Why
Depth and measured honesty beat breadth. Each cut removes a surface that would need its own tests and security review.
