# Resume bullets (verified numbers only)

**Project summary (header, 2 lines).** junior-ml-dev: an autonomous tabular-ML agent (15 MCP tools,
rule-based reviewer, leakage detector, injection guard, E2B sandbox backend) evaluated once on unseen
OpenML partitions from frozen commits; 672 tests, 92.6% coverage. Live demo: https://junior-ml-dev-demo.onrender.com (static examples: https://giri-harsh.github.io/junior-ml-dev-demo/)

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
neither beats FLAML (paired -0.011, CI includes 0). The live Render demo runs sample datasets with a scripted planner and with FLAML and the leakage
detectors disabled; the full pipeline is benchmarked separately (docs/RESULTS.md). CI on the private repo is currently not
running (Actions `startup_failure`), so the latest green CI run is v0.2.0-era.

Added for the live demo (run 11): **Engineered** a public Render free-tier deployment of the agent (512 MB, 0.1 vCPU): cut the web process from 225 MB to 63 MB, replaced per-run imports (44 s on that CPU) with a warm fork server, and verified live: 3/3 sample runs complete at a p50 of 52.0 s, admin endpoints 401, uploads 403, cold start 33 s to health and about 106 s to the first finished run. *Source: docs/METRICS.md "Demo" ([demo_render_v1.json](../benchmarks/results/demo_render_v1.json)). Cost of fitting the plan: FLAML off and leakage detectors skipped in the demo.*

Added for the demo redesign (run 12): **Built** a dependency-free demo front end for that deployment (plain HTML, CSS and a little JS, a CSS-only 3D figure, 35 KB per page load excluding fonts): a dataset picker with hash-verified CSV downloads, a live run page that polls the agent's real step log and leaderboard, and a plain-English report. All three bundled datasets finish inside the 60 s limit (diabetes 52 s, credit-g 38 s, wine quality 27 s). *Source: docs/METRICS.md "Demo" ([demo_render_v2.json](../benchmarks/results/demo_render_v2.json)).* There is still no upload: bring-your-own-CSV is marked coming soon.
