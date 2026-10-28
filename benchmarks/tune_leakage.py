"""Tuning view for leakage thresholds: planted `dev` + `real_dev` ONLY.

There is deliberately no flag to select other partitions (eval_v0 is spent, eval2 and the 10
real_heldout tasks are reserved for the single post-freeze evaluation).

Usage: python -m benchmarks.tune_leakage [--verbose]
Real-data findings are adjudicated by hand in benchmarks/adjudication_real_dev.json
({"<dataset>|<finding type>|<columns>": {"verdict": "false_positive"|"true_leak", "reason": ...}}).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from benchmarks.real_dev import load_all
from leakage.detectors import detect
from leakage.evaluate import run_partition
from leakage.models import DetectionMeta, Severity

PARTITION = "dev"  # hard-coded on purpose
ADJUDICATION = Path("benchmarks/adjudication_real_dev.json")


def finding_key(dataset: str, f: Any) -> str:
    return f"{dataset}|{f.type.value}|{','.join(f.columns)}"


def run_real_dev(seed: int = 0) -> dict[str, Any]:
    adj = json.loads(ADJUDICATION.read_text()) if ADJUDICATION.exists() else {}
    rows: dict[str, Any] = {}
    for name, (df, target) in load_all().items():
        t0 = time.perf_counter()
        findings = detect(df, target, DetectionMeta(seed=seed))
        confirmed = [f for f in findings if f.severity != Severity.LOW]
        rows[name] = {
            "seconds": round(time.perf_counter() - t0, 1),
            "medium_high": [
                {
                    "key": finding_key(name, f),
                    "severity": f.severity.value,
                    "evidence": f.evidence,
                    "verdict": adj.get(finding_key(name, f), {}).get("verdict", "UNADJUDICATED"),
                }
                for f in confirmed
            ],
            "low_notes": len(findings) - len(confirmed),
        }
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--verbose", action="store_true")
    a = p.parse_args(argv)
    res = run_partition(PARTITION)
    s = res["summary"]
    for bt, v in s["by_bug_type"].items():
        print(f"{bt:16s} recall {v['hits']}/{v['n']} column_hit={v['column_hit_rate']}")
    print(f"twin false alarms: {s['twin_false_alarm_n']}/{s['n_variants']}")
    for r in res["rows"]:
        if r["twin_false_alarm"] or (a.verbose and not r["hit"]):
            print("  ", r["variant_id"], "hit" if r["hit"] else "MISS", r["twin_findings"])
    real = run_real_dev()
    fps = 0
    for _name, r in real.items():
        for f in r["medium_high"]:
            print(f"real_dev {f['key']} [{f['severity']}] verdict={f['verdict']}")
            if a.verbose:
                print("     ", json.dumps(f["evidence"])[:300])
            fps += f["verdict"] in {"false_positive", "UNADJUDICATED"}
    print(f"real_dev datasets={len(real)} medium/high false-or-unadjudicated={fps}")
    print("max seconds per dataset:", max(r["seconds"] for r in real.values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
