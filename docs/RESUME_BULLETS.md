# Resume bullets (verified numbers only)

**Project summary (header, 2 lines).** junior-ml-dev: an autonomous tabular-ML agent (15 MCP tools,
rule-based reviewer, leakage detector, injection guard, E2B sandbox backend) evaluated once on unseen
OpenML partitions from frozen commits; 672 tests, 92.6% coverage. Static demo: https://giri-harsh.github.io/junior-ml-dev-demo/

- **Engineered** an autonomous tabular-ML agent on 15 MCP tools across 4 servers with CV-based model
  selection and a deterministic reviewer; on 10 unseen OpenML tasks (frozen commit, evaluated once)
  it matched an AutoML baseline (0.989 normalized vs FLAML = 1, 95% CI 0.950-1.012) and beat a
  linear baseline by +0.190 (paired CI 0.076-0.316), passing 8/10 tasks at a p50 of 135 s per task.
  *Source: docs/METRICS.md "Agent benchmark v5" ([agent_v5_llm.json](../benchmarks/results/agent_v5_llm.json)).*
- **Pioneered** a leakage detector (near-deterministic-target and linear-combination checks, adaptive
  time-bounded detection): 29 of 30 planted leaks found (96.7% recall) on an unseen partition with
  0 of 30 false alarms on clean twins; added an advisory LLM critic that, on a fresh hash-committed
  53-item planted set, flagged 18 of 23 planted issues with 0 false alarms in 30 clean runs (Wilson
  95% CI recall 0.58-0.90), and I report its known miss: 0 of 4 rule-failed baseline margins.
  *Source: docs/METRICS.md "Leakage detector", "Critic" ([leakage_v3.json](../benchmarks/results/leakage_v3.json), [critic_v2_eval.json](../benchmarks/critic_v2/critic_v2_eval.json)).*
- **Spearheaded** prompt-injection defences (untrusted-text sanitiser plus a structural action
  guard): in real-LLM red teams the model proposed 0 attacker actions over 49 payloads (run 6) and 0
  over a fresh hash-committed set of 14 novel evasions (95% upper bound 21.5%), with 0 unsafe actions
  executed; the prompt scanner caught only 1 of those 14, so I treat the guard as the boundary.
  *Source: docs/METRICS.md "Injection defence" ([injection_llm_v2.json](../benchmarks/results/injection_llm_v2.json), [injection_llm_v3.json](../benchmarks/results/injection_llm_v3.json)).*
- **Engineered** an E2B-backed per-exec sandbox (fresh microVM per execution, internet disabled, forced
  kill on timeout, only needed files transferred): 20/20 live executions at p50 1.87 s and p95 2.67 s
  end to end (n=20, one machine), 8 live isolation/execution tests passing.
  *Source: docs/METRICS.md "E2B sandbox backend" ([e2b_v1.json](../benchmarks/results/e2b_v1.json)).*
- **Engineered** production hardening and CI/CD gates: JWT admin auth, hash-chained audit log,
  token-bucket rate limiting, idempotency keys, graceful-SIGTERM workers with a dead-letter queue, OTel
  traces; 672 tests at 92.6% coverage with a 91% floor, bandit, pip-audit and a CycloneDX SBOM; a
  hosted-runner load test held p95 at 210 ms with 5 users and 1.5 s at 25 users (75 req/s, 0%
  errors), with 17.8% errors at 100 users reported as a limit.
  *Source: docs/METRICS.md "Load test" ([load_v1.json](../benchmarks/results/load_v1.json), CI run 40945724068); local gate on this commit (coverage 92.60%).*

Not claimed: the LLM planner does not beat the scripted planner (paired +0.001, CI includes 0) and
neither beats FLAML (paired -0.011, CI includes 0). The live demo is a static precomputed site; a live
Hugging Face Space was not possible on a free account. CI on the private repo is currently not
running (Actions `startup_failure`), so the latest green CI run is v0.2.0-era.
