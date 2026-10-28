"""Benchmark runner skeleton. S3: baselines on all registry tasks -> results/baselines_v0.json.

Usage: python -m benchmarks.run_benchmark --baselines [--time-budget 30] [--tasks a,b]
Agent runs are added in S16; the record shape here is what `score_run` extends in S25.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

from benchmarks.baselines import fit_predict, score_via_scorer
from benchmarks.metrics import bootstrap_ci, normalized_score
from benchmarks.results_writer import Conditions, write_result
from benchmarks.tasks.registry import TaskSpec, load_registry


def run_baselines_for_task(spec: TaskSpec, time_budget: int) -> dict[str, Any]:
    rec: dict[str, Any] = {"metric": spec.metric, "task_type": spec.task_type, "role": spec.role}
    for kind in ("dummy", "linear", "flaml"):
        t0 = time.perf_counter()
        preds, info = fit_predict(kind, spec, time_budget=time_budget)
        rec[kind] = score_via_scorer(spec, preds, run_id=f"baseline-{kind}-{spec.name}")
        rec[f"{kind}_fit_s"] = round(time.perf_counter() - t0, 2)
        rec.update({f"{kind}_{k}": v for k, v in info.items()})
    rec["linear_normalized"] = normalized_score(
        rec["linear"], rec["dummy"], rec["flaml"], spec.metric
    )
    return rec


def aggregate(per_task: dict[str, dict[str, Any]]) -> dict[str, Any]:
    vals = [r["linear_normalized"] for r in per_task.values() if r["linear_normalized"] is not None]
    excluded = [k for k, r in per_task.items() if r["linear_normalized"] is None]
    out: dict[str, Any] = {"normalized_linear_defined_n": len(vals), "excluded_tasks": excluded}
    if vals:
        mean, lo, hi = bootstrap_ci(vals, n_resamples=10_000, seed=0)
        out["normalized_linear_mean"] = mean
        out["normalized_linear_ci95"] = [lo, hi]
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--baselines", action="store_true")
    p.add_argument("--leakage", action="store_true", help="S4: leakage detectors (eval runs once)")
    p.add_argument("--allow-overwrite", action="store_true")
    p.add_argument("--time-budget", type=int, default=30, help="FLAML seconds per task")
    p.add_argument("--tasks", default="", help="comma-separated subset")
    p.add_argument("--out-name", default="baselines_v0")
    a = p.parse_args(argv)
    if a.leakage:
        from benchmarks.leakage_benchmark import run_leakage_benchmark

        return run_leakage_benchmark(a.allow_overwrite)
    if not a.baselines:
        p.error("need --baselines or --leakage")
    wanted = {t for t in a.tasks.split(",") if t}
    specs = [s for s in load_registry() if not wanted or s.name in wanted]
    per_task: dict[str, dict[str, Any]] = {}
    for s in specs:
        per_task[s.name] = run_baselines_for_task(s, a.time_budget)
        r = per_task[s.name]
        print(
            f"{s.name:34s} {s.metric:9s} dummy={r['dummy']:.4f} linear={r['linear']:.4f} "
            f"flaml={r['flaml']:.4f}",
            flush=True,
        )
    results = {
        "flaml_time_budget_s": a.time_budget,
        "per_task": per_task,
        "aggregate": aggregate(per_task),
    }
    cond = Conditions(
        llm="none",
        sandbox="none",
        n=len(specs),
        notes=f"baselines; FLAML time_budget={a.time_budget}s/task, 3-fold CV, seed 0; "
        "scored via scorer code path (in-process)",
    )
    path = write_result(
        a.out_name,
        results,
        cond,
        command="python -m "
        + " ".join(["benchmarks.run_benchmark", *(argv if argv is not None else sys.argv[1:])]),
    )
    print("wrote", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
