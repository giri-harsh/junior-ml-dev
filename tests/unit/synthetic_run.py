"""Shared helper: an LLM-planner run on the deterministic synthetic CSV (used by tests and by
scripts/record_cassette.py so the recorded prompts match the replayed ones)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from harness.agent.models import RunBudget
from harness.agent.planners import LLMPlanner
from harness.agent.runner import AgentRunner
from harness.agent.store import RunStore
from harness.gateway.gateway import Gateway
from tests.unit.test_agent_runner import cfg_for, make_csv


def run_synthetic_llm_run(tmp: Path, gateway: Gateway) -> tuple[dict[str, Any], LLMPlanner]:
    data = tmp / "data"
    data.mkdir(exist_ok=True)
    os.environ["DATA_TOOLS_ROOTS"] = str(data)
    os.environ["EXPERIMENTS_DIR"] = str(tmp / "exp")
    csv = make_csv(data)
    cfg = cfg_for(
        csv, planner="llm", llm_mode="real",
        budget=RunBudget(flaml_budget_s=0, tune_trials=2),
    )  # fmt: skip
    planner = LLMPlanner(gateway)
    runner = AgentRunner(RunStore(tmp / "r.db"), planner, run_root=tmp / "runs")
    return runner.run(cfg), planner
