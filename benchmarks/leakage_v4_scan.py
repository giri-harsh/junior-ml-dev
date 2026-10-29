"""Run the leakage detector over the v4 training data and list medium/high findings for hand
adjudication (benchmarks/adjudication_real_v4.json). A scan, not an eval-once headline: the
detector code is unchanged since leakage_v2.json. Usage: python -m benchmarks.leakage_v4_scan"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

from benchmarks.results_writer import Conditions, write_result
from benchmarks.tasks.registry import load_registry_v4
from leakage.detectors import detect
from leakage.models import DetectionMeta, Severity


def main() -> int:
    tasks: dict[str, Any] = {}
    for spec in load_registry_v4():
        df = pd.read_parquet(Path("data/tasks") / spec.name / "train.parquet").drop(
            columns=["row_id"], errors="ignore"
        )
        fs = detect(df, spec.target, DetectionMeta(seed=0))
        mh = [f.model_dump(mode="json") for f in fs if f.severity != Severity.LOW]
        for f in mh:
            f["evidence"] = {k: v for k, v in f["evidence"].items() if k != "suspect_indices"}
        tasks[spec.name] = {"n_rows": len(df), "medium_high": mh}
        print(f"{spec.name:34s} medium+high={len(mh)}", flush=True)
    write_result(
        "leakage_v4_scan",
        {"tasks": tasks},
        Conditions(
            llm="none",
            sandbox="none",
            n=len(tasks),
            notes="scan of unseen v4 data; hand-adjudicated",
        ),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
