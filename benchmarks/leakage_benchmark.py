"""`run_benchmark --leakage` (v1): frozen-threshold evaluation, once per thresholds hash.

Order: assert frozen hash -> claim the eval slot in the ledger (BEFORE running) -> dev (record)
-> eval2 (bugged + clean twins) -> real_heldout (the 10 benchmark tasks) -> write
benchmarks/results/leakage_v1.json -> mark the ledger spent.

Crash safety: each finished part is saved to `_partial_leakage_v1.json`; a rerun resumes from
it and only computes the missing parts. A rerun never recomputes a finished part.
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sklearn

from benchmarks.results_writer import RESULTS_DIR, Conditions, write_result
from benchmarks.tasks.registry import load_registry
from leakage import ledger
from leakage.config import assert_frozen, load_thresholds
from leakage.detectors import detect
from leakage.evaluate import run_partition
from leakage.models import DetectionMeta, Severity

SEED = 0
VERSION = "v1"
RESULT_NAME = f"leakage_{VERSION}"
PARTS = ("dev", "eval2", "real_heldout")


def run_real_heldout() -> dict[str, Any]:
    out: dict[str, Any] = {"tasks": {}, "exclusions": []}
    for spec in load_registry():
        path = Path("data/tasks") / spec.name / "train.parquet"
        if not path.exists():
            out["exclusions"].append({"task": spec.name, "reason": "train.parquet missing"})
            continue
        df = pd.read_parquet(path).drop(columns=["row_id"], errors="ignore")
        findings = detect(df, spec.target, DetectionMeta(seed=SEED))
        out["tasks"][spec.name] = {
            "n_rows": len(df),
            "findings": [f.model_dump(mode="json") for f in findings],
            "n_medium_or_high": sum(f.severity != Severity.LOW for f in findings),
        }
        n_mh = out["tasks"][spec.name]["n_medium_or_high"]
        print(f"real_heldout {spec.name:34s} medium+high={n_mh}")
    return out


def run_leakage_benchmark() -> int:
    frozen = assert_frozen()
    partial_path = RESULTS_DIR / f"_partial_{RESULT_NAME}.json"
    final_path = RESULTS_DIR / f"{RESULT_NAME}.json"
    partial: dict[str, Any] = {}
    if partial_path.exists():
        partial = json.loads(partial_path.read_text())
        if partial.get("thresholds_sha256") != frozen:
            raise RuntimeError("partial results belong to different thresholds")
    elif ledger.is_spent(frozen) or final_path.exists():
        print("eval already spent for these thresholds; refusing to run again")
        return 2
    else:
        ledger.claim(frozen, f"benchmarks/results/{RESULT_NAME}.json", list(PARTS))
    partial["thresholds_sha256"] = frozen
    runners = {
        "dev": lambda: run_partition("dev", SEED),
        "eval2": lambda: run_partition("eval2", SEED),
        "real_heldout": run_real_heldout,
    }
    for part in PARTS:
        if part in partial:
            print("resuming: reusing finished part", part)
            continue
        partial[part] = runners[part]()
        partial_path.parent.mkdir(parents=True, exist_ok=True)
        partial_path.write_text(json.dumps(partial, default=str))
    results = {
        "thresholds_sha256": frozen,
        "thresholds": load_thresholds(),
        "dev": partial["dev"],
        "eval2": partial["eval2"],
        "real_heldout": partial["real_heldout"],
        "environment": {
            "seed": SEED,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "notes": "dev was used for tuning (record only); eval2 and real_heldout evaluated once",
    }
    cond = Conditions(
        llm="none",
        sandbox="none",
        n=partial["eval2"]["summary"]["n_variants"],
        notes="leakage v1: eval2 planted variants + twins, 10 real heldout tasks; "
        "thresholds frozen at tag s5-thresholds-frozen",
    )
    path = write_result(
        RESULT_NAME, results, cond, command="python -m benchmarks.run_benchmark --leakage"
    )
    ledger.mark(frozen, "spent")
    partial_path.unlink(missing_ok=True)
    print("wrote", path)
    for name in ("dev", "eval2"):
        s = partial[name]["summary"]
        print(
            name,
            "overall recall",
            round(s["overall_recall"], 3),
            "twin FPR",
            round(s["twin_fpr"], 3),
        )
    return 0
