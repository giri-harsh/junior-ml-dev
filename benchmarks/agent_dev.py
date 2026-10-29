"""Agent development partition: 5 real_dev datasets (disjoint from the 10 benchmark tasks).

Each dataset is split 70/30 with a fixed seed; the agent sees only the 70% (and the 30% features
for prediction). Reference models (dummy, linear, FLAML) are fit on the same 70% through the same
experiments service. Design decisions MAY look at these numbers; the benchmark tasks must not.

Usage: python -m benchmarks.agent_dev [--flaml-budget 20] [--out-name agent_dev_v0]
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from apps.scorer.metrics import compute
from benchmarks.metrics import bootstrap_ci, normalized_score, paired_bootstrap_ci
from benchmarks.real_dev import load_all
from benchmarks.results_writer import Conditions, write_result

DEV_TASKS = ["wdbc", "kc1", "sk_wine", "sk_diabetes_reg", "kin8nm"]
WORK = Path("data/agent_dev")
SEED = 0


def classify(y: pd.Series) -> tuple[str, str]:
    if pd.api.types.is_numeric_dtype(y) and y.nunique() > 15:
        return "regression", "rmse"
    return ("binary", "roc_auc") if y.nunique() == 2 else ("multiclass", "f1_macro")


def split_task(name: str, df: pd.DataFrame, target: str) -> dict[str, Any]:
    task_type, metric = classify(df[target])
    if name == "kc1":
        metric = "pr_auc"  # imbalanced binary
    strat = df[target] if task_type != "regression" else None
    tr, te = train_test_split(df, test_size=0.3, random_state=SEED, stratify=strat)
    d = WORK / name
    d.mkdir(parents=True, exist_ok=True)
    tr = tr.reset_index(drop=True)
    te = te.reset_index(drop=True)
    tr.to_parquet(d / "train.parquet")
    te.drop(columns=[target]).assign(row_id=np.arange(len(te))).to_parquet(
        d / "test_features.parquet"
    )
    return {
        "task_type": task_type, "metric": metric, "dir": d,
        "y_test": te[target], "y_train": tr[target],
    }  # fmt: skip


def score_predictions(spec: dict[str, Any], preds: pd.DataFrame) -> float:
    pred = preds.sort_values("row_id")["pred"].to_numpy()
    y = spec["y_test"].reset_index(drop=True)
    if spec["task_type"] != "regression" and spec["metric"] in {"roc_auc", "pr_auc"}:
        pos = str(sorted(spec["y_train"].astype(str).unique())[-1])
        return compute(spec["metric"], (y.astype(str) == pos).astype(int), pred)
    if spec["task_type"] != "regression":
        return compute(spec["metric"], y.astype(str), pred.astype(str))
    return compute(spec["metric"], y, pred)


def _norm(v: float, ref: dict[str, float], spec: dict[str, Any]) -> float | None:
    return normalized_score(v, ref["dummy"], ref["flaml"], spec["metric"])


def references(
    name: str, spec: dict[str, Any], target: str, flaml_budget: float
) -> dict[str, float]:
    from mcp_servers.experiments import service as ex

    out: dict[str, float] = {}
    base: dict[str, Any] = {
        "data_path": str(spec["dir"] / "train.parquet"), "target": target,
        "task_type": spec["task_type"], "metric": spec["metric"], "seed": SEED,
    }  # fmt: skip
    for fam in ("dummy", "linear", "flaml"):
        rid = f"ref-{name}"
        rec = ex.train_model(
            ex.TrainRequest(**base, run_id=rid, family=fam, time_budget_s=max(1, flaml_budget))
        )
        final = (
            rec if fam == "flaml"
            else ex.refit_full(ex.RefitRequest(run_id=rid, model_id=rec.model_id))
        )  # fmt: skip
        res = ex.predict(
            ex.PredictRequest(
                run_id=rid, model_id=final.model_id,
                features_path=str(spec["dir"] / "test_features.parquet"), out_name=f"{fam}.csv",
            )
        )  # fmt: skip
        out[fam] = score_predictions(spec, pd.read_csv(res.out_path))
    return out


def run_agent(
    name: str,
    spec: dict[str, Any],
    target: str,
    flaml_budget: float,
    planner: Any = None,
    tag: str = "dev",
) -> dict[str, Any]:
    from harness.agent.models import RunBudget, RunConfig, RunTask
    from harness.agent.planners import ScriptedPlanner
    from harness.agent.runner import AgentRunner
    from harness.agent.store import RunStore

    cfg = RunConfig(
        run_id=f"{tag}-{name}",
        planner="llm" if planner is not None else "scripted",
        llm_mode="real" if planner is not None else "none",
        task=RunTask(
            name=name, data_path=str(spec["dir"] / "train.parquet"), target=target,
            task_type=spec["task_type"], metric=spec["metric"], seed=SEED,
            test_features_path=str(spec["dir"] / "test_features.parquet"),
        ),
        budget=RunBudget(flaml_budget_s=flaml_budget), mode="dev",
    )  # fmt: skip
    runner = AgentRunner(
        RunStore(WORK / "runs.db"), planner or ScriptedPlanner(), run_root=WORK / "runs"
    )
    res = runner.run(cfg)
    res["test_score"] = score_predictions(spec, pd.read_csv(res["predictions_path"]))
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--flaml-budget", type=float, default=20.0)
    ap.add_argument("--out-name", default="agent_dev_v0")
    ap.add_argument("--tasks", default=",".join(DEV_TASKS))
    args = ap.parse_args(argv)
    if WORK.exists():
        shutil.rmtree(WORK)  # dev scratch only (under data/, never results or ledgers)
    WORK.mkdir(parents=True)
    os.environ["EXPERIMENTS_DIR"] = str(WORK / "exp")
    os.environ.setdefault("TRAJECTORY_DIR", str(WORK / "traj"))
    data = load_all()
    per: dict[str, Any] = {}
    for name in args.tasks.split(","):
        df, target = data[name]
        spec = split_task(name, df, target)
        t0 = time.perf_counter()
        ref = references(name, spec, target, args.flaml_budget)
        run = run_agent(name, spec, target, args.flaml_budget)

        per[name] = {
            "task_type": spec["task_type"], "metric": spec["metric"], "dummy": ref["dummy"],
            "linear": ref["linear"], "flaml": ref["flaml"], "agent": run["test_score"],
            "agent_family": run["chosen_family"], "status": run["status"],
            "dropped": run["dropped"], "reviewer": run["review"],
            "agent_latency_s": run["latency_s"], "agent_steps": run["n_steps"],
            "agent_normalized": _norm(run["test_score"], ref, spec),
            "linear_normalized": _norm(ref["linear"], ref, spec),
            "wall_s": round(time.perf_counter() - t0, 1),
        }  # fmt: skip
        print(name, per[name]["agent"], per[name]["linear"], per[name]["flaml"], flush=True)
    ok = [
        r for r in per.values()
        if r["agent_normalized"] is not None and r["linear_normalized"] is not None
    ]  # fmt: skip
    agg: dict[str, Any] = {"n_defined": len(ok)}
    if ok:
        a = [r["agent_normalized"] for r in ok]
        lin = [r["linear_normalized"] for r in ok]
        agg["agent_normalized_mean_ci95"] = bootstrap_ci(a)
        agg["linear_normalized_mean_ci95"] = bootstrap_ci(lin)
        agg["agent_minus_linear_paired_ci95"] = paired_bootstrap_ci(a, lin)
    notes = (
        "DEV partition (real_dev, 70/30 split seed 0); scripted planner, NO LLM; references fit "
        "on the same 70%; design decisions may use these numbers"
    )
    path = write_result(
        args.out_name,
        {"per_task": per, "aggregate": agg, "flaml_budget_s": args.flaml_budget},
        Conditions(llm="none", sandbox="none", n=len(per), notes=notes),
    )
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
