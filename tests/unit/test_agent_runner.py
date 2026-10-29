from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from harness.agent.models import RunBudget, RunConfig, RunTask
from harness.agent.planners import ScriptedPlanner
from harness.agent.runner import AgentRunner
from harness.agent.store import RunStore
from harness.security.audit import AuditLog
from trajectory import emit

ROOT = Path(__file__).resolve().parents[2]
FAST = RunBudget(flaml_budget_s=0, tune_trials=2)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("DATA_TOOLS_ROOTS", str(root))
    monkeypatch.setenv("EXPERIMENTS_DIR", str(tmp_path / "exp"))
    emit.configure(tmp_path / "traj")
    return root


def make_csv(root: Path, name: str = "d.csv", n: int = 400, **mut: Any) -> Path:
    rng = np.random.default_rng(0)
    a, b = rng.normal(size=n), rng.normal(size=n)
    df = pd.DataFrame(
        {
            "a": a, "b": b, "cat": rng.choice(["u", "v", "w"], n),
            "y": (a + 0.5 * b + rng.normal(scale=0.6, size=n) > 0).astype(int),
        }
    )  # fmt: skip
    for k, v in mut.items():
        df[k] = v(df) if callable(v) else v
    p = root / name
    df.to_csv(p, index=False)
    return p


def cfg_for(path: Path, run_id: str = "run1", **kw: Any) -> RunConfig:
    task = RunTask(
        name="t1", data_path=str(path), target=kw.pop("target", "y"),
        task_type=kw.pop("task_type", "binary"), metric=kw.pop("metric", "roc_auc"),
    )  # fmt: skip
    return RunConfig(run_id=run_id, task=task, budget=kw.pop("budget", FAST), **kw)


def runner(tmp_path: Path, **kw: Any) -> AgentRunner:
    return AgentRunner(
        RunStore(tmp_path / "runs.db"), ScriptedPlanner(), run_root=tmp_path / "runs", **kw
    )


def test_scripted_run_end_to_end(env: Path, tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.db")
    res = runner(tmp_path, audit=audit).run(cfg_for(make_csv(env)))
    assert res["status"] == "done" and res["planner"] == "scripted" and res["llm_mode"] == "none"
    assert res["val_score"] > 0.75 and res["review"] == "APPROVE" and not res["failures"]
    assert Path(res["report"]["html"]).exists() and Path(res["trace_path"]).exists()
    html = Path(res["report"]["html"]).read_text(encoding="utf-8")
    assert "planner=scripted" in html and "<svg" in html
    actions = [e["action"] for e in audit.entries()]
    assert set(actions) == {"tool_call"} and len(actions) == res["n_steps"]
    assert audit.verify_chain() == (True, None)
    trace = json.loads(Path(res["trace_path"]).read_text(encoding="utf-8"))
    assert {s["server"] for s in trace["steps"]} >= {"data-tools", "experiments", "agent"}


def test_leaky_column_is_dropped_and_decision_recorded(env: Path, tmp_path: Path) -> None:
    p = make_csv(
        env, leak=lambda d: d["y"] * 1.0 + np.random.default_rng(1).normal(0, 0.01, len(d))
    )
    res = runner(tmp_path).run(cfg_for(p))
    assert "leak" in res["dropped"] and res["val_score"] < 0.97
    assert res["unresolved"] == []


@pytest.mark.parametrize(
    ("name", "mutate", "expect"),
    [
        ("constant_target", {"y": 1}, "degenerate"),
        ("all_missing", {"empty": np.nan}, "done"),
        ("high_card_ids", {"uid": lambda d: [f"id{i}" for i in range(len(d))]}, "done"),
    ],
)
def test_chaos_data_never_crashes(
    env: Path, tmp_path: Path, name: str, mutate: dict[str, Any], expect: str
) -> None:
    res = runner(tmp_path).run(cfg_for(make_csv(env, f"{name}.csv", **mutate), run_id=name))
    assert res["status"] == expect
    if expect == "done":
        assert res["val_score"] > 0.7


def test_tiny_dataset_degenerates_gracefully(env: Path, tmp_path: Path) -> None:
    res = runner(tmp_path).run(cfg_for(make_csv(env, n=12), run_id="tiny"))
    assert res["status"] == "degenerate" and res["failures"]


def test_malformed_csv_degenerates_gracefully(env: Path, tmp_path: Path) -> None:
    p = env / "bad.csv"
    p.write_bytes(b"a,b\n\x00\x00,\xff\xfe\n1,2,3,4,5\n")
    res = runner(tmp_path).run(cfg_for(p, run_id="bad"))
    assert res["status"] == "degenerate" and res["n_steps"] > 0


def test_step_budget_triggers_wrapup_with_best_so_far(env: Path, tmp_path: Path) -> None:
    budget = RunBudget(max_steps=5, flaml_budget_s=0, tune_trials=2)
    res = runner(tmp_path).run(cfg_for(make_csv(env), budget=budget))
    assert res["status"] == "budget_exhausted" and res["budget_exhausted"]["steps"] == 5
    assert res["chosen_family"] in {"dummy", "linear"} and res["report"]


def test_wall_clock_budget_with_fake_clock(env: Path, tmp_path: Path) -> None:
    t = [0.0]

    def clock() -> float:
        t[0] += 100.0  # every reading advances 100 "seconds"
        return t[0]

    budget = RunBudget(max_wall_s=250, flaml_budget_s=0, tune_trials=2)
    res = runner(tmp_path, clock=clock).run(cfg_for(make_csv(env), budget=budget))
    assert res["status"] == "budget_exhausted" and res["budget_exhausted"]["wall_s"] > 250


def test_rerun_of_finished_run_is_idempotent(env: Path, tmp_path: Path) -> None:
    cfg = cfg_for(make_csv(env))
    r = runner(tmp_path)
    first = r.run(cfg)
    assert r.run(cfg) == first


def test_blocked_path_is_refused_by_policy(env: Path, tmp_path: Path) -> None:
    bad = env / "scorer_data" / "x.csv"
    bad.parent.mkdir()
    make_csv(bad.parent, "x.csv")
    res = runner(tmp_path).run(cfg_for(bad, run_id="blk"))
    assert res["status"] == "degenerate"
    assert all("path" in v or "denied" in v or "not" in v or "access" in v
               for v in res["failures"].values())  # fmt: skip


def test_deploy_without_approval_is_blocked(env: Path, tmp_path: Path) -> None:
    from harness.agent.models import Step

    r = runner(tmp_path)
    cfg = cfg_for(make_csv(env), run_id="dep")
    from harness.agent.tools import ToolCtx

    err = r._guard(cfg, Step(tool="deploy_local", args={"model_id": "m"}), ToolCtx(cfg, {}))
    assert err == "blocked:approval_required"


def test_resume_after_hard_kill_matches_uninterrupted_run(env: Path, tmp_path: Path) -> None:
    csv = make_csv(env)
    cfg = cfg_for(csv, run_id="killme")
    cfg_file = tmp_path / "cfg.json"
    cfg_file.write_text(cfg.model_dump_json(), encoding="utf-8")
    base = [sys.executable, "-m", "harness.agent.cli", "run", "--config", str(cfg_file)]
    envv = {
        **os.environ, "DATA_TOOLS_ROOTS": str(env), "EXPERIMENTS_DIR": str(tmp_path / "exp"),
        "TRAJECTORY_DIR": str(tmp_path / "traj"), "PYTHONPATH": str(ROOT),
    }  # fmt: skip

    def go(db: str, root: str, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*base, "--db", str(tmp_path / db), "--run-root", str(tmp_path / root), *extra],
            capture_output=True, text=True, env=envv, cwd=ROOT, timeout=300,
        )  # fmt: skip

    killed = go("k.db", "kr", "--crash-after", "6")
    assert killed.returncode == 137  # died mid-run
    store = RunStore(tmp_path / "k.db")
    assert store.status("killme") == "running" and len(store.checkpoints("killme")) == 6
    resumed = go("k.db", "kr")
    assert resumed.returncode == 0, resumed.stderr[-500:]
    out = json.loads(resumed.stdout.strip().splitlines()[-1])
    assert out["status"] == "done" and out["resumed"] is True
    idxs = [r.idx for r, _ in store.checkpoints("killme")]
    assert idxs == list(range(len(idxs)))  # no step repeated, none missing
    clean_cfg = cfg.model_copy(update={"run_id": "clean"})
    clean = AgentRunner(
        RunStore(tmp_path / "c.db"), ScriptedPlanner(), run_root=tmp_path / "cr"
    ).run(clean_cfg)
    assert out["val_score"] == clean["val_score"] and out["chosen_family"] == clean["chosen_family"]


def test_ties_within_tolerance_go_to_the_simpler_model() -> None:
    from harness.agent.tools import simplicity_order

    models = {
        "h": {"family": "hgb", "val_score": 0.9100},
        "l": {"family": "linear", "val_score": 0.9080},  # 0.2% below best: a tie
        "r": {"family": "rf", "val_score": 0.8900},
    }
    assert simplicity_order(["h", "l", "r"], models) == ["l", "h", "r"]
    models["l"]["val_score"] = 0.9000  # 1.1% below: a real difference
    assert simplicity_order(["h", "l", "r"], models) == ["h", "l", "r"]
    assert simplicity_order([], {}) == []


def test_reviewer_does_not_approve_when_leakage_detection_failed() -> None:
    from harness.agent.models import RunConfig, RunTask
    from harness.agent.tools import ToolCtx, review

    task = RunTask(name="t", data_path="x", target="y", task_type="binary", metric="roc_auc")
    cfg = RunConfig(run_id="r", task=task)
    state = {
        "models": {
            "l": {
                "family": "linear",
                "val_score": 0.9,
                "train_score": 0.91,
                "fit_on": "train_split",
            },
            "d": {"family": "dummy", "val_score": 0.5, "train_score": 0.5, "fit_on": "train_split"},
        },
        "leaderboard": [{"model_id": "l"}, {"model_id": "d"}],
        "failures": {"detect_leakage": "GuardError: time budget of 60.0s exceeded"},
        "findings": [],
        "dropped": [],
    }
    res = review(ToolCtx(cfg, state), {})
    assert res["verdict"] == "REQUEST_CHANGES" and not res["checks"]["leakage_checked"]["passed"]


def test_one_se_rule_prefers_the_simpler_model_inside_the_standard_error() -> None:
    from harness.agent.tools import simplicity_order

    def m(f: str, v: float, se: float) -> dict[str, Any]:
        return {"family": f, "val_score": v, "cv_se": se, "selection": "cv"}

    models = {
        "h": m("hgb", 0.920, 0.010),
        "l": m("linear", 0.912, 0.012),
        "r": m("rf", 0.880, 0.01),
    }
    assert simplicity_order(["h", "l", "r"], models) == ["l", "h", "r"]  # 0.008 <= 1 SE of the best
    models["l"] = m("linear", 0.905, 0.012)  # 0.015 > 0.010: a real difference
    assert simplicity_order(["h", "l", "r"], models) == ["h", "l", "r"]


def test_report_shows_top_features(env: Path, tmp_path: Path) -> None:  # noqa: F811
    res = runner(tmp_path).run(cfg_for(make_csv(env), run_id="expl"))
    html = Path(res["report"]["html"]).read_text(encoding="utf-8")
    assert "Top features" in html and "permutation importance" in html
    assert "## Top features" in Path(res["report"]["md"]).read_text(encoding="utf-8")
