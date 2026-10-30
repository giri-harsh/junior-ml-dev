# Resume bullets (verified numbers only)

**Project summary (header, 2 lines).** junior-ml-dev: an autonomous tabular-ML agent (15 MCP tools,
deterministic reviewer, leakage detector, injection guard) evaluated once on unseen OpenML
partitions from frozen commits; CI-gated at 92% coverage.

- **Engineered** an autonomous tabular-ML agent on 15 MCP tools across 4 servers with CV-based model
  selection and a deterministic reviewer; on 10 unseen OpenML tasks (frozen commit, evaluated once)
  it matched an AutoML baseline (0.989 normalized vs FLAML = 1, 95% CI 0.950-1.012) and beat a
  linear baseline by +0.190 (paired CI 0.076-0.316), passing 8/10 tasks at a p50 of 135 s per task.
  *Source: docs/METRICS.md "Agent benchmark v5" ([agent_v5_llm.json](../benchmarks/results/agent_v5_llm.json)).*
- **Pioneered** a leakage detector with near-deterministic-target and linear-combination checks and
  adaptive time-bounded detection: 29 of 30 planted leaks found (96.7% recall) on an unseen
  partition with 0 of 30 false alarms on clean twins.
  *Source: docs/METRICS.md "Leakage detector" ([leakage_v3.json](../benchmarks/results/leakage_v3.json)).*
- **Spearheaded** prompt-injection defences (untrusted-text sanitiser plus a structural action
  guard): in a real-LLM red team over 49 payloads (41-case suite + 8 held-out, run 6) the model
  proposed 0 attacker actions and 0 unsafe actions executed (Wilson upper bound 8.6% on the 41-case
  suite; the 8-payload held-out set is smaller).
  *Source: docs/METRICS.md "Injection defence" ([injection_llm_v2.json](../benchmarks/results/injection_llm_v2.json)).*
- **Engineered** production hardening for the API: JWT admin auth, hash-chained audit log, token-bucket
  rate limiting, idempotency keys, graceful-SIGTERM workers with a dead-letter queue and OTel traces;
  a hosted-runner load test held p95 at 210 ms with 5 users and 1.5 s at 25 users (75 req/s, 0%
  errors), with 17.8% errors at 100 users reported as a limit.
  *Source: docs/METRICS.md "Load test" ([load_v1.json](../benchmarks/results/load_v1.json), CI run 40945724068).*
- **Engineered** CI/CD quality gates (438 tests, 92% coverage against a 91% floor, ruff, mypy, bandit,
  pip-audit, CycloneDX SBOM) plus an advisory LLM critic that, on a fresh hash-committed planted
  set, flagged 10 of 15 planted issues with 1 false alarm in 19 clean runs (Wilson 95% CI 0.42-0.85
  recall, 0.01-0.25 false-alarm rate).
  *Source: docs/METRICS.md "Critic" ([critic_v6.json](../benchmarks/results/critic_v6.json)); CI run 41008428375.*

Not claimed: the LLM planner does not beat the scripted planner (paired +0.001, CI includes 0) and
neither beats FLAML (paired -0.011, CI includes 0).
