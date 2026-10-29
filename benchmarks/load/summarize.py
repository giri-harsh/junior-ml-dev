"""Summarise locust CSVs (one set per concurrency level) into benchmarks/results/load_v1.json.

Usage: python -m benchmarks.load.summarize <dir> [--ci-run-id ID] [--out-dir DIR]
Reads <dir>/load_<users>_stats.csv. Numbers are copied from locust's aggregated rows.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Any

from benchmarks.results_writer import Conditions, write_result


def parse(path: Path) -> dict[str, Any]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    out: dict[str, Any] = {"endpoints": {}}
    for r in rows:
        rec = {
            "requests": int(r["Request Count"]),
            "failures": int(r["Failure Count"]),
            "rps": float(r["Requests/s"]),
            "p50_ms": float(r["50%"]),
            "p95_ms": float(r["95%"]),
            "p99_ms": float(r["99%"]),
        }
        rec["error_rate"] = rec["failures"] / rec["requests"] if rec["requests"] else 0.0
        if r["Name"] == "Aggregated":
            out["aggregate"] = rec
        else:
            out["endpoints"][r["Name"]] = rec
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--ci-run-id", default="")
    ap.add_argument("--out-dir", default=None)
    a = ap.parse_args(argv)
    levels: dict[str, Any] = {}
    for f in sorted(Path(a.dir).glob("load_*_stats.csv")):
        m = re.match(r"load_(\d+)_stats\.csv", f.name)
        if m:
            levels[m.group(1)] = parse(f)
    if not levels:
        print("no locust csv found", file=sys.stderr)
        return 2
    notes = (
        "locust against the predict-service container and the API container (docker compose app "
        f"profile) on a GitHub-hosted ubuntu runner; CI run {a.ci_run_id or 'unknown'}; "
        "20 s per level; not a capacity claim for other hardware"
    )
    write_result(
        "load_v1",
        {"concurrency": levels, "ci_run_id": a.ci_run_id},
        Conditions(llm="none", sandbox="none", n=len(levels), notes=notes),
        out_dir=Path(a.out_dir) if a.out_dir else None,
    )
    print({k: v["aggregate"] for k, v in levels.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
