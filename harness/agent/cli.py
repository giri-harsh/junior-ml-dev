"""CLI: `python -m harness.agent.cli run --config run.json --db runs.db [--crash-after N]`.

The config is a RunConfig JSON. Re-running the same command after a crash resumes the run.
The scripted planner is the default; `--planner llm` needs a gateway and uses recorded/mocked
responses unless provider keys are present (never in this offline build).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness.agent.models import RunConfig
from harness.agent.planners import ScriptedPlanner
from harness.agent.runner import AgentRunner
from harness.agent.store import RunStore


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="harness.agent.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--config", required=True)
    run.add_argument("--db", default="data/runs.db")
    run.add_argument("--run-root", default="data/runs")
    run.add_argument("--crash-after", type=int, default=None, help="failure injection (tests)")
    args = ap.parse_args(argv)
    cfg = RunConfig.model_validate_json(Path(args.config).read_text(encoding="utf-8"))
    runner = AgentRunner(
        RunStore(args.db), ScriptedPlanner(), run_root=args.run_root, crash_after=args.crash_after
    )
    result = runner.run(cfg)
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("status") in {"done", "budget_exhausted"} else 2


if __name__ == "__main__":
    sys.exit(main())
