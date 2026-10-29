"""Run the leakage detector over the v4 training data and list medium/high findings for hand
adjudication (benchmarks/adjudication_real_v4.json). A scan, not an eval-once headline: the
detector code is unchanged since leakage_v2.json. Usage: python -m benchmarks.leakage_v4_scan"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

from benchmarks.results_writer import Conditions, write_result
from benchmarks.tasks.registry import partition
from leakage.detectors import detect_with_status
from leakage.models import DetectionMeta, Severity


def main(argv: list[str] | None = None) -> int:
    name = (argv or sys.argv[1:] or ["v4"])[0]
    tasks: dict[str, Any] = {}
    for spec in partition(name):
        df = pd.read_parquet(Path("data/tasks") / spec.name / "train.parquet").drop(
            columns=["row_id"], errors="ignore"
        )
        fs, partial = detect_with_status(df, spec.target, DetectionMeta(seed=0))
        mh = [f.model_dump(mode="json") for f in fs if f.severity != Severity.LOW]
        for f in mh:
            f["evidence"] = {k: v for k, v in f["evidence"].items() if k != "suspect_indices"}
        tasks[spec.name] = {"n_rows": len(df), "medium_high": mh, "partial": partial}
        print(f"{spec.name:34s} medium+high={len(mh)} partial={partial}", flush=True)
    write_result(
        f"leakage_{name}_scan",
        {"tasks": tasks},
        Conditions(
            llm="none",
            sandbox="none",
            n=len(tasks),
            notes=f"leakage v3 scan of unseen {name} data; hand-adjudicated",
        ),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
