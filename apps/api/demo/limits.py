"""Light-weight demo invariants (no pandas/sklearn): the web process imports this, the heavy runner
module is imported only by the run subprocess."""

from __future__ import annotations

from harness.agent.models import RunConfig


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
