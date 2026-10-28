# ADR-001: Architecture

Status: accepted (S1)

## Decision
A deterministic-code core with an LLM that proposes. Components: FastAPI API, arq worker with Postgres checkpoints, a separate scorer service that alone holds hidden labels, four MCP servers (sandbox-exec, data-tools, experiments, deploy), an LLM gateway, and a trajectory log that every stage writes to.

## Why
- Splits, metrics, scoring, leakage checks and claim verification must be reproducible, so they are code with fixed seeds.
- The hidden test set must be unreachable from agent paths, so it lives in its own service and volume.
- Every step emits a typed `TrajectoryEvent` from day one so P3 training data is not retrofitted.

## Consequences
Cross-service boundaries add setup cost (compose). In exchange, isolation is enforced by deployment, not promised by convention.
