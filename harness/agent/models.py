"""Typed run configuration, steps and budgets for the agent harness."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SLUG = r"^[A-Za-z0-9_\-]{1,64}$"
TOOL_SERVER = {
    "profile_dataset": "data-tools",
    "detect_leakage": "data-tools",
    "train_model": "experiments",
    "tune_model": "experiments",
    "refit_full": "experiments",
    "compare_models": "experiments",
    "predict": "experiments",
    "explain_model": "experiments",
    "evaluate_model": "experiments",
    "package_model": "deploy",
    "deploy_local": "deploy",
    "check_code_policy": "sandbox-exec",
    "engineer_features": "sandbox-exec",
    "decide_leakage": "agent",
    "review": "agent",
    "report": "agent",
}


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunTask(_Base):
    name: str = Field(pattern=SLUG)
    data_path: str
    target: str
    task_type: Literal["binary", "multiclass", "regression"]
    metric: Literal["roc_auc", "pr_auc", "f1_macro", "rmse", "mae"]
    test_features_path: str | None = None
    seed: int = 0
    dummy_ref: float | None = None
    flaml_ref: float | None = None


class RunBudget(_Base):
    max_steps: int = Field(default=30, ge=1, le=200)
    max_wall_s: float = Field(default=900.0, gt=0, le=7200)
    max_tokens: int = Field(default=20_000, ge=0, le=2_000_000)
    flaml_budget_s: float = Field(default=20.0, ge=0, le=120)
    tune_trials: int = Field(default=4, ge=0, le=12)
    step_retries: int = Field(default=1, ge=0, le=3)
    selection: Literal["holdout", "cv"] = "cv"  # CV mean + 1-SE simplicity rule (decision 114)


class RunConfig(_Base):
    run_id: str = Field(pattern=SLUG)
    task: RunTask
    budget: RunBudget = Field(default_factory=RunBudget)
    planner: Literal["scripted", "llm"] = "scripted"
    llm_mode: Literal["none", "mocked", "recorded", "real"] = "none"
    deploy: bool = False
    sandbox_features: bool = False  # run agent-written feature code through the sandbox
    mode: Literal["dev", "benchmark", "test"] = "dev"


class Step(_Base):
    """One proposed tool call. Args are symbolic: paths/targets are bound by the harness."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default="", max_length=300)
    critical: bool = False

    @property
    def server(self) -> str:
        return TOOL_SERVER.get(self.tool, "unknown")


class StepRecord(_Base):
    idx: int
    step: Step
    ok: bool
    result: dict[str, Any]
    error: str | None = None
    latency_s: float
    tokens: int = 0
    cost_usd: float = 0.0
    attempts: int = 1
