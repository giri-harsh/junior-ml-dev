"""Evaluation of the detectors on the planted-bug suite (labels used here, never in detectors)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from benchmarks.metrics import bootstrap_ci
from leakage.detectors import detect
from leakage.models import DetectionMeta, Finding, Severity

PLANTED_ROOT = Path("data/planted_bugs")
COUNTING = {Severity.MEDIUM, Severity.HIGH}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def list_variants(partition: str, root: Path = PLANTED_ROOT) -> list[Path]:
    out = []
    for d in sorted(root.iterdir()):
        if d.is_dir() and json.loads((d / "labels.json").read_text())["partition"] == partition:
            out.append(d)
    return out


def counting(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity in COUNTING]


def evaluate_variant(d: Path, seed: int = 0) -> dict[str, Any]:
    """Run detectors on one bugged/twin pair and compare with its ground truth."""
    labels = json.loads((d / "labels.json").read_text())
    target = labels["target"]
    meta = DetectionMeta(seed=seed)
    bugged = counting(detect(pd.read_parquet(d / "bugged.parquet"), target, meta))
    twin = counting(detect(pd.read_parquet(d / "twin.parquet"), target, meta))
    expected = labels["expected_detector"]
    fams = {f.family for f in bugged}
    cols = {c for f in bugged if f.family == expected for c in f.columns}
    want = set(labels["columns"]) - {"<all rows>"}
    return {
        "variant_id": labels["variant_id"],
        "bug_type": labels["bug_type"],
        "partition": labels["partition"],
        "expected": expected,
        "hit": expected in fams,
        "column_hit": bool(cols & want) if want and expected in fams else None,
        "bugged_families": sorted(fams),
        "twin_false_alarm": bool(twin),
        "twin_families": sorted({f.family for f in twin}),
        "twin_findings": [f"{f.type.value}:{','.join(f.columns)}" for f in twin],
    }


def summarize(rows: list[dict[str, Any]], seed: int = 0) -> dict[str, Any]:
    by_type: dict[str, Any] = {}
    for bt in sorted({r["bug_type"] for r in rows}):
        sub = [r for r in rows if r["bug_type"] == bt]
        k = sum(r["hit"] for r in sub)
        lo, hi = wilson(k, len(sub))
        mean, blo, bhi = bootstrap_ci([float(r["hit"]) for r in sub], seed=seed)
        colh = [r["column_hit"] for r in sub if r["column_hit"] is not None]
        by_type[bt] = {
            "n": len(sub),
            "hits": k,
            "recall": k / len(sub),
            "wilson95": [round(lo, 4), round(hi, 4)],
            "bootstrap95": [round(blo, 4), round(bhi, 4)],
            "column_hit_rate": (sum(colh) / len(colh)) if colh else None,
        }
    fa = sum(r["twin_false_alarm"] for r in rows)
    flo, fhi = wilson(fa, len(rows))
    fmean, fblo, fbhi = bootstrap_ci([float(r["twin_false_alarm"]) for r in rows], seed=seed)
    return {
        "by_bug_type": by_type,
        "overall_recall": sum(r["hit"] for r in rows) / len(rows),
        "overall_recall_bootstrap95": list(
            bootstrap_ci([float(r["hit"]) for r in rows], seed=seed)[1:]
        ),
        "twin_fpr": fa / len(rows),
        "twin_fpr_wilson95": [round(flo, 4), round(fhi, 4)],
        "twin_fpr_bootstrap95": [round(fblo, 4), round(fbhi, 4)],
        "twin_false_alarm_n": fa,
        "n_variants": len(rows),
        "twin_false_alarm_examples": [
            {"variant_id": r["variant_id"], "findings": r["twin_findings"]}
            for r in rows
            if r["twin_false_alarm"]
        ],
    }


def run_partition(partition: str, seed: int = 0, root: Path = PLANTED_ROOT) -> dict[str, Any]:
    rows = [evaluate_variant(d, seed) for d in list_variants(partition, root)]
    return {"rows": rows, "summary": summarize(rows, seed)}
