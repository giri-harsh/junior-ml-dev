"""The demo agent runner and its subprocess entry point.

`DemoAgentRunner` is the normal `AgentRunner` with the sandbox and deploy tools removed from its
registry, so a planner that proposes them gets `unknown_tool` and nothing executes. The scripted
planner is the only planner the demo constructs; no LLM client is ever created.

Entry point (spawned by the service so a hung run can be killed):
    python -m apps.api.demo.run_job <job.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from apps.api.demo.config import BLOCKED_TOOLS
from harness.agent.models import RunConfig
from harness.agent.planners import ScriptedPlanner
from harness.agent.runner import AgentRunner
from harness.agent.store import RunStore


class DemoAgentRunner(AgentRunner):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["approvals"] = None  # no approval flow exists in the demo
        kwargs["extra_tools"] = None
        super().__init__(*args, **kwargs)
        self.tools = {k: v for k, v in self.tools.items() if k not in BLOCKED_TOOLS}


def enforce_demo_config(cfg: RunConfig, *, max_wall_s: float, flaml_s: float) -> RunConfig:
    """Re-assert the demo invariants on a config, whatever produced it."""
    if cfg.planner != "scripted" or cfg.llm_mode != "none":
        raise ValueError("demo runs use the scripted planner only")
    if cfg.deploy or cfg.sandbox_features:
        raise ValueError("deploy and sandboxed code are disabled in the demo")
    b = cfg.budget
    if b.max_wall_s > max_wall_s or b.flaml_budget_s > flaml_s or b.max_tokens != 0:
        raise ValueError("budget exceeds the demo limits")
    return cfg


def execute(job_file: Path) -> dict[str, Any]:
    job = json.loads(job_file.read_text(encoding="utf-8"))
    cfg = RunConfig.model_validate(job["config"])
    run_dir = Path(job["run_dir"])
    enforce_demo_config(cfg, max_wall_s=float(job["max_wall_s"]), flaml_s=float(job["flaml_s"]))
    runner = DemoAgentRunner(
        RunStore(run_dir / "agent.db"), ScriptedPlanner(), run_root=run_dir / "out", audit=None
    )
    result = runner.run(cfg)
    (run_dir / "result.json").write_text(json.dumps(result, default=str), encoding="utf-8")
    return result


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m apps.api.demo.run_job <job.json>", file=sys.stderr)
        return 2
    execute(Path(argv[1]))
    return 0
