"""Leakage Detective v1.2 evaluation on data NO earlier evaluation has seen.

Why not rerun v1's partitions: eval2 and the 10 real_heldout tasks were read in run 1; scoring
changed code on them again would be a second look. So this run uses
  - eval3: a new planted partition (variants 9-11 per bug type, new seeds, same generator),
  - real_v3: the 10 unseen v3 datasets (findings adjudicated by hand in
    benchmarks/adjudication_real_v3.json, written AFTER seeing the findings and before any change),
  - dev: record only (tuning partition).
Ledger key = hash(thresholds + detector/role/probe source), claimed BEFORE running; one evaluation.
`leakage_v1.json` stays as the historical record for the v1 code and is marked superseded here.

Usage: python -m benchmarks.leakage_benchmark_v2
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from benchmarks.results_writer import RESULTS_DIR, Conditions, write_result
from benchmarks.tasks.registry import load_registry_v3
from leakage import ledger
from leakage.config import assert_frozen, load_thresholds
from leakage.detectors import detect
from leakage.evaluate import run_partition
from leakage.models import DetectionMeta, Severity

SEED = 0
RESULT_NAME = "leakage_v2"
CODE_FILES = [
    "leakage/detectors.py", "leakage/probes.py", "leakage/scoring.py", "leakage/config.py",
    "leakage/models.py", "datastory/roles.py", "datastory/profile.py", "leakage/thresholds.yaml",
]  # fmt: skip
ADJUDICATION = Path("benchmarks/adjudication_real_v3.json")


def code_hash(root: Path = Path(".")) -> str:
    h = hashlib.sha256(assert_frozen().encode())
    for rel in CODE_FILES:
        h.update(
            rel.encode()
            + hashlib.sha256((root / rel).read_bytes().replace(b"\r\n", b"\n")).digest()
        )
    return h.hexdigest()


def run_real_v3() -> dict[str, Any]:
    out: dict[str, Any] = {"tasks": {}, "exclusions": []}
    for spec in load_registry_v3():
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
        print(f"real_v3 {spec.name:36s} medium+high={out['tasks'][spec.name]['n_medium_or_high']}")
    return out


def main() -> int:
    key = f"leakage-code:{code_hash()}"
    partial_path = RESULTS_DIR / f"_partial_{RESULT_NAME}.json"
    partial: dict[str, Any] = {}
    if partial_path.exists():
        partial = json.loads(partial_path.read_text(encoding="utf-8"))
    elif ledger.is_spent(key):
        print("eval already spent for this detector code; refusing to run again")
        return 2
    else:
        ledger.claim(key, f"benchmarks/results/{RESULT_NAME}.json", ["dev", "eval3", "real_v3"])
    runners = {
        "dev": lambda: run_partition("dev", SEED),
        "eval3": lambda: run_partition("eval3", SEED),
        "real_v3": run_real_v3,
    }
    for part, fn in runners.items():
        if part in partial:
            continue
        partial[part] = fn()
        partial_path.write_text(json.dumps(partial, default=str), encoding="utf-8")
    results = {
        "code_hash": key, "thresholds": load_thresholds(), "supersedes": "leakage_v1.json",
        **partial,
        "notes": "dev = record only; eval3 and real_v3 never evaluated before this run",
    }  # fmt: skip
    cond = Conditions(
        llm="none", sandbox="none", n=partial["eval3"]["summary"]["n_variants"],
        notes="leakage v2 (detector fixes 84,85,90): unseen eval3 planted partition + 10 unseen "
        "real v3 datasets; v1 numbers are for the older code",
    )  # fmt: skip
    path = write_result(
        RESULT_NAME, results, cond, command="python -m benchmarks.leakage_benchmark_v2"
    )
    ledger.mark(key, "spent")
    partial_path.unlink(missing_ok=True)
    print("wrote", path)
    s = partial["eval3"]["summary"]
    print("eval3 recall", round(s["overall_recall"], 3), "twin FPR", round(s["twin_fpr"], 3))
    return 0


if __name__ == "__main__":
    sys.exit(main())
