"""Collect GitHub Actions evidence (run ids, conclusions, durations) into
benchmarks/results/ci_evidence.json so docs/METRICS.md can cite it.

    uv run python scripts/collect_ci_evidence.py [--limit 30]
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from typing import Any

from benchmarks.results_writer import Conditions, write_result


def _runs(limit: int) -> list[dict[str, Any]]:
    out = subprocess.run(
        ["gh", "run", "list", "-L", str(limit), "--json",
         "databaseId,workflowName,conclusion,headSha,createdAt,updatedAt,event,displayTitle"],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    rows: list[dict[str, Any]] = json.loads(out)
    return rows


def _secs(r: dict[str, Any]) -> float:
    f = "%Y-%m-%dT%H:%M:%SZ"
    return (
        datetime.strptime(r["updatedAt"], f) - datetime.strptime(r["createdAt"], f)
    ).total_seconds()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30)
    a = ap.parse_args(argv)
    runs = _runs(a.limit)
    res: dict[str, Any] = {}
    for wf in sorted({r["workflowName"] for r in runs}):
        last = next(r for r in runs if r["workflowName"] == wf)  # newest first
        res[f"latest {wf}"] = (
            f"{last['conclusion']} - run {last['databaseId']} ({_secs(last):.0f} s) on "
            f"`{last['headSha'][:7]}` ({last['displayTitle']})"
        )
    ok = sum(1 for r in runs if r["conclusion"] == "success")
    res["runs sampled"] = f"{len(runs)} most recent, {ok} success"
    write_result(
        "ci_evidence", res, Conditions(llm="none", sandbox="none", n=len(runs)),
        command="scripts/collect_ci_evidence.py",
    )  # fmt: skip
    print("wrote ci_evidence.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
