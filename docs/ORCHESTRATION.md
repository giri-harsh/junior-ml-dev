# Run 9 orchestration

Probe at start (2026-10-30 06:25 UTC): LIVE_E2B=no, LIVE_HF=no, LLM_AVAILABLE=no (Groq 120/120, Gemini
111/120; reset 2026-10-31 00:00 UTC). Shared budget ledger: `.budget/ledger.json` via
`scripts/budget.py`. Agents report to the orchestrator; only the orchestrator edits this file.

| Agent | Branch | Worktree | Owned paths | Status | Blocker |
|---|---|---|---|---|---|
| A E2B sandbox | ws-a-e2b | (isolated) | harness/sandbox/**, tests/sandbox*/**, tests/e2b/**, benchmarks/results/e2b_v1.json, docs/ws/A.md | dispatching (prep-only) | no E2B_API_KEY |
| B live demo | ws-b-demo | (isolated) | Dockerfile.space, .spaceignore, apps/api/demo/**, apps/web/**, scripts/deploy_space.py, tests/demo/**, docs/ws/B.md | dispatching (prep-only) | no HF_TOKEN |
| C injection | ws-c-injection | (isolated) | benchmarks/injection/**, injection_llm_v3.json, injected_runs_v1.json, their cassettes, docs/ws/C.md | waiting for LLM reset | caps spent until 2026-10-31 00:00 UTC |
| D critic set v2 | ws-d-critic | (isolated) | benchmarks/critic_v2/**, benchmarks/results/critic_v4.json, tests/critic_v2/**, docs/ws/D.md | dispatching (authoring now, run after reset) | caps for the run |
| E verifier | none | read-only | none | on demand per branch | |
