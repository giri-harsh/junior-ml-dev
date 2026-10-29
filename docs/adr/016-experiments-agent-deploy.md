# ADR-016: experiments server, agent harness, deploy server (S12-S16)

Status: accepted. Decisions 66-80 in DECISIONS.md.

## Shape
- `mcp_servers/experiments`: train / tune / evaluate / predict / compare. Service layer is pure
  Python (unit-testable); `server.py` wraps it with the official MCP SDK over stdio.
- `harness/agent`: `Planner` protocol -> `Step` (a tool name + args). The executor owns guardrails,
  budgets, checkpoints and audit; planners only propose steps. Two planners: `ScriptedPlanner`
  (deterministic, no LLM) and `LLMPlanner` (gateway + structured output, falls back to the script
  when output is invalid or the budget is gone).
- Tools are called in-process through a registry that points at the same service functions the MCP
  servers expose. One stdio smoke test per server proves the wire path; the in-process path avoids
  four subprocess startups per run.
- `mcp_servers/deploy`: package best model into a bundle (model, FastAPI predict service,
  Dockerfile, compose file, model card). `deploy_local` is gated by a single-use approval token.
- Run state: `RunStore` (SQLite) holds run row + one checkpoint per completed step. A killed
  process resumes at the first step with no checkpoint. Interface `JobQueue`; SQLite in-process
  implementation here, arq+Postgres is a STUB (no Redis/Postgres on this machine).

## Evaluation protocol
- Dev partition: 5 `data/real_dev` datasets, disjoint from the 10 benchmark tasks, scored on a
  seeded internal holdout (no scorer). Agent design decisions are allowed to look at these.
- Final: the 10 benchmark tasks through the scorer service, once per agent freeze hash
  (planner config + prompts + code policy + experiments config). Ledger entry before the run.
- Normalized score uses dummy/FLAML references from `baselines_v0.json` (code-written). The agent
  has its own, shorter FLAML budget, so "agent vs FLAML" is a comparison of two budgets, stated
  in the conditions block.

## Limitations
- Planner (a) is scripted: results are NOT LLM-agent results and are labelled so everywhere.
- No real LLM or real sandbox was used; model code runs in-process in the experiments service
  (trusted code), not in agent-supplied sandbox code.

## Results and what they do and do not show (agent_v1.json, scripted planner, no LLM)
- One frozen evaluation (hash 66e3796c63e0, ledger status `evaluated`, no infra retries).
- Agent normalized score 1.037 [0.994, 1.085] over 10 tasks; paired difference vs linear +0.213 [0.030, 0.394]; vs FLAML +0.037 [-0.006, 0.085] (indistinguishable: FLAML at the same 30 s is one of the agent's candidates, so this is largely FLAML's score, selected against linear/HGB/RF on a validation split).
- Pass rule vs linear (ADR-005): 6/10. Validation-based selection picked the linear recipe on 3 tasks (adult, credit-g, vehicle), where the agent therefore equals linear exactly and cannot clear the 2% margin.
- The reviewer returned REQUEST_CHANGES on churn and wine_quality for exactly the two known leakage false positives (group probe; ordinal-target label noise). The agent did not drop columns for them (not droppable types), so the carried leakage limitations surface as unresolved findings.
- wine_quality (lower is better): agent 0.420, FLAML baseline 0.400, linear 0.563. The agent picked its own FLAML model; it trains FLAML on the 80% train split and does not refit (decision 68), while the baseline FLAML uses all rows, so the agent's FLAML-family score is expected to sit slightly below the baseline's. Not retuned.
- CPU was shared with other work (tests, lint) during part of the run; FLAML's wall-clock budget makes it mildly load-sensitive. Not rerun (eval-once).
- Not shown: any LLM-agent capability. The LLM planner path was tested only with a mock provider.
