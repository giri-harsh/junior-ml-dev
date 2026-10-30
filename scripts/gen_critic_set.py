"""Author the FRESH planted critic evaluation set (run 7). Deterministic (seed 7001).

Each item is a symbolic run summary in the exact shape `run_summary_v3` produces, plus a hidden
label (`planted`: issue type or null). The labels are NOT part of the summary the critic sees.
The output file and its sha256 are committed BEFORE any critic call reads them.

    uv run python scripts/gen_critic_set.py
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "benchmarks" / "critic_set_v6.json"
GAPS = json.loads((ROOT / "harness" / "agent" / "family_gaps.json").read_text(encoding="utf-8"))
FAMS = ["hgb", "rf", "flaml"]
CHECKS = ["metric_matches_task", "train_val_gap", "baseline_margin", "leakage_checked",
          "leakage_resolved"]  # fmt: skip


def top(fam: str) -> float:
    return float(GAPS.get(fam, GAPS["hgb"])["range"][1])


def item(rng: random.Random, i: int, planted: str | None, **ov: Any) -> dict[str, Any]:
    fam = ov.pop("family", rng.choice(FAMS))
    n_rows = ov.pop("n_rows", rng.choice([1500, 3200, 8000, 26000, 48000]))
    dummy = 0.5
    cv = ov.pop("cv", round(rng.uniform(0.72, 0.93), 4))
    lin = round(cv - rng.uniform(0.012, 0.05), 4)
    se = ov.pop("se", round(rng.uniform(0.002, 0.008), 4))
    lo, hi = GAPS.get(fam, GAPS["hgb"])["range"]
    ratio = ov.pop("gap_ratio", round(rng.uniform(lo, hi * 0.8), 3))
    train = round(min(1.0, cv + ratio * abs(cv - dummy)), 4)
    ratio = round(abs(train - cv) / (abs(cv - dummy) + 1e-9), 3)
    checks = {k: True for k in CHECKS}
    checks["train_val_gap"] = abs(train - cv) <= 0.15
    checks.update(ov.pop("checks", {}))
    partial = ov.pop("partial", [])
    unresolved = ov.pop("unresolved", [])
    ran = ov.pop("ran", True)
    tried = [
        {"family": "dummy", "cv": dummy, "se": 0.0, "train": dummy},
        {"family": "linear", "cv": lin, "se": se, "train": round(lin + 0.03, 4)},
        {"family": fam, "cv": cv, "se": se, "train": train},
    ]
    summary: dict[str, Any] = {
        "task_type": "binary", "metric": "roc_auc", "direction": "higher_is_better",
        "tried": tried, "chosen_family": fam,
        "leakage_detection_ran": ran, "unresolved_leakage": unresolved,
        "leakage_partial": partial,
        "dropped_columns": ov.pop("dropped", 0), "failed_steps": 0,
        "budget_exhausted": ov.pop("budget_exhausted", False),
        "chosen": {
            "family": fam, "cv": cv, "se": se, "train": train, "gap_ratio": ratio,
            "expected_gap_ratio": GAPS.get(fam, GAPS["hgb"])["range"],
            "lift_over_dummy_se": round(abs(cv - dummy) / max(se, 1e-9), 2),
        },
        "n_rows": n_rows, "rule_checks": checks,
    }  # fmt: skip
    return {"id": f"c{i:02d}", "planted": planted, "summary": summary}


def build() -> list[dict[str, Any]]:
    rng = random.Random(7001)
    out: list[dict[str, Any]] = []
    i = 0

    def add(planted: str | None, **ov: Any) -> None:
        nonlocal i
        out.append(item(rng, i, planted, **ov))
        i += 1

    for u in (
        ["TARGET_LEAKAGE:feat_a"],
        ["ID_LEAK:row_id", "TARGET_LEAKAGE:x3"],
        ["LEAKY_FEATURE:f7"],
    ):
        add("unresolved_leakage", unresolved=u, checks={"leakage_resolved": False})
    for fam in ("hgb", "rf", "flaml"):
        add("gap_beyond_family_range", family=fam, cv=rng.choice([0.58, 0.6, 0.62]), gap_ratio=9.0)
    for n in (60, 140):
        add("tiny_test", n_rows=n)
    for se in (0.09, 0.14):
        add("cv_instability", se=se)
    for r in (
        ["detector skipped: time bound", "linear_combination not run"],
        ["holdout too small for separator check"],
    ):
        add("partial_leakage_check", partial=r)
    for _ in range(3):
        add("rule_fail_baseline_margin", checks={"baseline_margin": False})
    # clean runs: all rule checks pass, nothing material; includes benign edge cases
    for _ in range(14):
        add(None)
    for fam in (
        "hgb",
        "rf",
        "flaml",
    ):  # high-but-in-range gaps (tree ensembles overfit legitimately)
        add(None, family=fam, gap_ratio=round(top(fam) * 0.92, 3))
    for _ in range(3):
        add(None, partial=["rows sampled to 20000"])
    add(None, n_rows=320)
    add(None, budget_exhausted=True)
    add(None, se=0.012)
    return out


def main() -> int:
    items = build()
    body = json.dumps({"seed": 7001, "items": items}, indent=1, sort_keys=True) + "\n"
    OUT.write_text(body, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    OUT.with_suffix(".sha256").write_text(digest + "\n", encoding="utf-8", newline="\n")
    planted = sum(1 for x in items if x["planted"])
    print(f"wrote {OUT.name}: {len(items)} items, {planted} planted, sha256 {digest[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
