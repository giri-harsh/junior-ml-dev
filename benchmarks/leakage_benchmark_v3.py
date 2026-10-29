"""Leakage Detective v3 evaluation: new planted partition eval4 (24 old-type variants + 6
linear_combo variants at several noise levels, each with a clean twin), once per detector-code hash.

dev is recorded only. Brazilian_houses/ailerons (burned v4) were used only as regression checks.
Usage: python -m benchmarks.leakage_benchmark_v3
"""

from __future__ import annotations

import json
import sys
from typing import Any

from benchmarks.leakage_benchmark_v2 import SEED, code_hash
from benchmarks.results_writer import RESULTS_DIR, Conditions, write_result
from leakage import ledger
from leakage.config import load_thresholds
from leakage.evaluate import run_partition

RESULT_NAME = "leakage_v3"


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
        ledger.claim(key, f"benchmarks/results/{RESULT_NAME}.json", ["dev", "eval4"])
    for part in ("dev", "eval4"):
        if part not in partial:
            partial[part] = run_partition(part, SEED)
            partial_path.write_text(json.dumps(partial, default=str), encoding="utf-8")
    results = {
        "code_hash": key, "thresholds": load_thresholds(), "supersedes": "leakage_v2.json",
        **partial, "notes": "dev = record only (tuned); eval4 never evaluated before this run",
    }  # fmt: skip
    cond = Conditions(
        llm="none", sandbox="none", n=partial["eval4"]["summary"]["n_variants"],
        notes="leakage v3: linear-combination/separator detector + adaptive budget; unseen eval4",
    )  # fmt: skip
    path = write_result(
        RESULT_NAME, results, cond, command="python -m benchmarks.leakage_benchmark_v3"
    )
    ledger.mark(key, "spent")
    partial_path.unlink(missing_ok=True)
    s = partial["eval4"]["summary"]
    print(
        "wrote",
        path,
        "eval4 recall",
        round(s["overall_recall"], 3),
        "twin FPR",
        round(s["twin_fpr"], 3),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
