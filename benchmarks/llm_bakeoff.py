"""Two-task bake-off of LLM provider families on the DEV partition (wdbc, sk_wine).

For each family alone (Gemini, Groq gpt-oss-120b->20b): schema-valid-first-try rate, repairs,
fallbacks, requests, tokens, and whether the agent's dev score clears the ADR-005 pass rule vs the
linear reference. Cache (cassette) files make reruns free. Usage: python -m benchmarks.llm_bakeoff
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from benchmarks import agent_dev as ad
from benchmarks.metrics import passes
from benchmarks.real_dev import load_all
from benchmarks.results_writer import Conditions, write_result
from harness.agent.planners import LLMPlanner
from harness.gateway.limits import UsageLedger
from harness.gateway.live import build_live_gateway

TASKS = ["wdbc", "sk_wine"]
CASSETTES = Path("tests/cassettes")


def main() -> int:
    if ad.WORK.exists():
        shutil.rmtree(ad.WORK)
    ad.WORK.mkdir(parents=True)
    os.environ["EXPERIMENTS_DIR"] = str(ad.WORK / "exp")
    data = load_all()
    out: dict[str, Any] = {}
    for family in ("gemini", "groq"):
        rows: dict[str, Any] = {}
        agg: dict[str, Any] = {
            "structured": 0,
            "first_try": 0,
            "repairs": 0,
            "fallbacks": 0,
            "requests": 0,
            "tokens": 0,
        }
        for name in TASKS:
            df, target = data[name]
            spec = ad.split_task(name, df, target)
            ref = ad.references(name, spec, target, 10)
            gw = build_live_gateway(CASSETTES / f"bakeoff_{family}.jsonl", order=(family,))
            planner = LLMPlanner(gw)
            run = ad.run_agent(name, spec, target, 10, planner=planner, tag=f"bake-{family}")
            ok = passes(
                run["test_score"],
                ref["linear"],
                spec["metric"],
                float(pd.Series(spec["y_train"]).std())
                if spec["task_type"] == "regression"
                else None,
            )
            rows[name] = {
                "agent": run["test_score"],
                "linear": ref["linear"],
                "passes_vs_linear": ok,
                "family": run["chosen_family"],
                "steps": run["n_steps"],
                "decisions": planner.decisions,
            }
            s = gw.stats
            agg["structured"] += s["structured"]
            agg["first_try"] += s["structured_first_try_valid"]
            agg["repairs"] += s["repairs"]
            agg["fallbacks"] += planner.fallbacks
            agg["requests"] += s["calls"] - s["cache_hits"]
            agg["tokens"] += gw.budget.used_tokens
        agg["first_try_valid_rate"] = (
            agg["first_try"] / agg["structured"] if agg["structured"] else None
        )
        agg["passes"] = sum(r["passes_vs_linear"] for r in rows.values())
        out[family] = {"per_task": rows, "aggregate": agg}
        print(family, agg, flush=True)
    ledger = UsageLedger(Path("data/llm_usage.json"))
    out["requests_used_today"] = {f: ledger.used(f) for f in ("gemini", "groq")}
    notes = "DEV partition bake-off, 2 tasks x 2 provider families, cloud APIs only"
    write_result("llm_bakeoff", out, Conditions(llm="real", sandbox="none", n=4, notes=notes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
