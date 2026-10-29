"""One-command demo: scripted agent on a bundled real dataset, end to end, in a temp directory.

    uv run python scripts/demo.py [--deploy]

Everything runs offline: profile -> leakage check -> baselines -> model search -> reviewer -> refit
-> report (+ optional approval-gated deploy staging). The planner is SCRIPTED (no LLM). The
dataset is `data/real_dev/wdbc.parquet`; run `python -m benchmarks.real_dev` first if it is absent.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deploy", action="store_true", help="also stage a deploy (demo approval)")
    args = ap.parse_args(argv)
    src = ROOT / "data" / "real_dev" / "wdbc.parquet"
    if not src.exists():
        print("missing data/real_dev/wdbc.parquet; run: uv run python -m benchmarks.real_dev")
        return 2
    work = Path(tempfile.mkdtemp(prefix="jmd-demo-"))
    (work / "data").mkdir()
    os.environ.update(
        DATA_TOOLS_ROOTS=str(work / "data"), EXPERIMENTS_DIR=str(work / "exp"),
        DEPLOY_DIR=str(work / "deploy"), TRAJECTORY_DIR=str(work / "traj"),
    )  # fmt: skip
    import pandas as pd

    from harness.agent.models import RunBudget, RunConfig, RunTask
    from harness.agent.planners import ScriptedPlanner
    from harness.agent.runner import AgentRunner
    from harness.agent.store import RunStore
    from harness.security.approvals import ApprovalStore
    from harness.security.audit import AuditLog

    df = pd.read_parquet(src)
    target = "Class" if "Class" in df.columns else df.columns[-1]
    csv = work / "data" / "wdbc.parquet"
    df.to_parquet(csv)
    cfg = RunConfig(
        run_id="demo", mode="test", deploy=args.deploy,
        task=RunTask(name="wdbc", data_path=str(csv), target=target, task_type="binary",
                     metric="roc_auc"),
        budget=RunBudget(flaml_budget_s=10),
    )  # fmt: skip
    approvals = ApprovalStore(work / "approvals.db", "demo-only-secret")  # not a real secret
    audit = AuditLog(work / "audit.db")

    def runner(token: str | None) -> AgentRunner:
        return AgentRunner(RunStore(work / "runs.db"), ScriptedPlanner(), run_root=work / "runs",
                           audit=audit, approvals=approvals, approval_token=token)  # fmt: skip

    res = runner(None).run(cfg)
    if res["status"] == "awaiting_approval":
        aid = res["pending_approval"]["approval_id"]
        print(f"deploy needs approval {aid}; demo approves it (single-use token, audit-logged)")
        res = runner(approvals.approve(aid)).run(cfg)
    print(f"status={res['status']} planner={res['planner']} (scripted, no LLM)")
    print(f"chosen={res['chosen_family']} validation {cfg.task.metric}={res['val_score']:.4f}")
    print(f"reviewer={res['review']} dropped={res['dropped']} steps={res['n_steps']}")
    print(f"report: {res['report']['html']}")
    print(f"audit chain intact: {audit.verify_chain()[0]}")
    return 0 if res["status"] in {"done", "budget_exhausted"} else 1


if __name__ == "__main__":
    sys.exit(main())
