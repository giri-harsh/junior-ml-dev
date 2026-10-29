"""The sandboxed feature-engineering step end to end, on the local subprocess backend (CI runs the
same through Docker in tests/infra)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from harness.agent.models import RunBudget
from harness.agent.planners import ScriptedPlanner
from harness.agent.runner import AgentRunner
from harness.agent.store import RunStore
from harness.agent.tools import FEATURE_CODE
from harness.policies.code_policy import check_code
from tests.unit.test_agent_runner import cfg_for
from tests.unit.test_agent_runner import env as env  # noqa: F401


def test_feature_code_passes_the_code_policy() -> None:
    assert check_code(FEATURE_CODE.format(target="y")).allowed


def _skewed(root: Path, n: int = 400) -> Path:
    rng = np.random.default_rng(0)
    a = rng.exponential(size=n) * 10
    df = pd.DataFrame({"a": a, "b": rng.normal(size=n), "y": (np.log1p(a) > 1.5).astype(int)})
    df.loc[::25, "b"] = np.nan
    p = root / "skew.csv"
    df.to_csv(p, index=False)
    return p


def test_agent_run_with_sandboxed_feature_step(  # noqa: F811
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JMD_SANDBOX", "local-unsafe")
    csv = _skewed(env)
    cfg = cfg_for(csv, sandbox_features=True, budget=RunBudget(flaml_budget_s=0, tune_trials=0))
    res = AgentRunner(RunStore(tmp_path / "r.db"), ScriptedPlanner(), run_root=tmp_path / "r").run(
        cfg
    )
    assert res["status"] == "done" and not res["failures"]
    eng = RunStore(tmp_path / "r.db").checkpoints(cfg.run_id)[-1][1]["engineered"]
    assert eng["n_columns_after"] > eng["n_columns_before"]  # a log1p feature was added
    assert eng["sandbox"] == "SubprocessSandbox"


def test_feature_step_without_a_configured_sandbox_fails_safe(  # noqa: F811
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("JMD_SANDBOX", raising=False)
    cfg = cfg_for(
        _skewed(env), sandbox_features=True, budget=RunBudget(flaml_budget_s=0, tune_trials=0)
    )
    res = AgentRunner(RunStore(tmp_path / "r.db"), ScriptedPlanner(), run_root=tmp_path / "r").run(
        cfg
    )
    assert res["status"] == "done"  # the run continues on the raw data
    assert any("no sandbox backend" in v for v in res["failures"].values())
