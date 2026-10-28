"""`run_benchmark --leakage`: frozen-threshold evaluation. The eval partition runs once.

Order: assert thresholds match the frozen hash -> dev -> eval -> clean twins (inside each
partition) -> the 10 real baseline tasks -> write benchmarks/results/leakage_v0.json.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sklearn

from benchmarks.results_writer import RESULTS_DIR, Conditions, write_result
from benchmarks.tasks.registry import load_registry
from leakage.config import assert_frozen, load_thresholds
from leakage.detectors import detect
from leakage.evaluate import run_partition
from leakage.models import DetectionMeta, Severity

SEED = 0
RESULT_NAME = "leakage_v0"


def _real_tasks() -> tuple[dict[str, Any], list[dict[str, str]]]:
    out: dict[str, Any] = {}
    exclusions: list[dict[str, str]] = []
    for spec in load_registry():
        path = Path("data/tasks") / spec.name / "train.parquet"
        if not path.exists():
            exclusions.append({"task": spec.name, "reason": "train.parquet missing"})
            continue
        df = pd.read_parquet(path).drop(columns=["row_id"], errors="ignore")
        findings = detect(df, spec.target, DetectionMeta(seed=SEED))
        out[spec.name] = {
            "n_rows": len(df),
            "findings": [f.model_dump(mode="json") for f in findings],
            "n_medium_or_high": sum(f.severity != Severity.LOW for f in findings),
        }
        print(f"real {spec.name:34s} medium+high={out[spec.name]['n_medium_or_high']}", flush=True)
    return out, exclusions


def run_leakage_benchmark(allow_overwrite: bool = False) -> int:
    target = RESULTS_DIR / f"{RESULT_NAME}.json"
    if target.exists() and not allow_overwrite:
        print(f"{target} exists; eval already ran once. Refusing (use --allow-overwrite).")
        return 2
    frozen = assert_frozen()
    dev = run_partition("dev", SEED)
    ev = run_partition("eval", SEED)
    real, exclusions = _real_tasks()
    results = {
        "thresholds_sha256": frozen,
        "thresholds": load_thresholds(),
        "dev": dev,
        "eval": ev,
        "real_tasks": real,
        "exclusions": exclusions,
        "environment": {
            "seed": SEED,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
        },
    }
    cond = Conditions(
        llm="none",
        sandbox="none",
        n=ev["summary"]["n_variants"],
        notes="leakage detectors on 24 dev + 24 eval planted variants and their clean twins; "
        "eval run once after thresholds were frozen; real tasks use agent-visible train split",
    )
    path = write_result(
        RESULT_NAME, results, cond, command="python -m benchmarks.run_benchmark --leakage"
    )
    print("wrote", path)
    for name, part in (("dev", dev), ("eval", ev)):
        s = part["summary"]
        print(
            name,
            "overall recall",
            round(s["overall_recall"], 3),
            "twin FPR",
            round(s["twin_fpr"], 3),
        )
    return 0
