"""Author the FRESH critic evaluation set v2 (run 9). Deterministic (seed 9301, not 7001).

Same item shape as the run-7 set (`benchmarks/critic_set_v6.json`): a symbolic run summary in the
exact shape `run_summary_v3` produces plus a hidden label (`planted`: issue type or null). The
label is NOT part of the summary the critic sees. The set and its sha256 are committed BEFORE any
critic call reads them; the set is evaluated exactly once.

Differences from the run-7 generator (set-design flaws fixed, none of them tuned on results):
  * `baseline_margin`, `train_val_gap` and `metric_matches_task` rule outcomes are computed with
    the REAL functions of `harness/review/checks.py`, so no clean item carries a failing rule.
  * Every `rule_fail_baseline_margin` item is UNAMBIGUOUSLY failing: the chosen model is not
    better than the linear baseline at all (cv <= linear). See docs/ws/D.md for the rule.
  * Item order is shuffled and ids are opaque, so neither order nor id leaks the label.

    python -m benchmarks.critic_v2.gen
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from harness.review.checks import (
    check_baseline_margin,
    check_metric_matches_task,
    check_train_val_gap,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "benchmarks" / "critic_v2" / "set_v2.json"
SHA = OUT.with_suffix(".sha256")
SEED = 9301
GAPS: dict[str, Any] = json.loads(
    (ROOT / "harness" / "agent" / "family_gaps.json").read_text(encoding="utf-8")
)
FAMS = ["hgb", "rf", "flaml"]
DUMMY = 0.5
METRIC = "roc_auc"
CHECKS = ["metric_matches_task", "train_val_gap", "baseline_margin", "leakage_checked",
          "leakage_resolved"]  # fmt: skip
MAX_CLEAN_GAP = 0.12  # absolute train-CV gap for clean items; the rule limit is 0.15
RULE_FAIL_RULE = (
    "rule_fail_baseline_margin: linear.cv = round(cv + m, 4) with m = 3 to 6 x se (at least 0.01) "
    "for 'worse' items, or m = 0 for 'tie' items, i.e. cv <= linear.cv; the real "
    "check_baseline_margin (needs cv >= linear.cv x 1.02) is asserted False for every item."
)

PLANTED_TYPES = [
    "unresolved_leakage", "leakage_not_run", "gap_beyond_family_range", "tiny_test",
    "cv_instability", "partial_leakage_check", "rule_fail_baseline_margin",
    "metric_task_mismatch", "lift_below_one",
]  # fmt: skip


def top(fam: str) -> float:
    return float(GAPS.get(fam, GAPS["hgb"])["range"][1])


def lo(fam: str) -> float:
    return float(GAPS.get(fam, GAPS["hgb"])["range"][0])


def item(rng: random.Random, planted: str | None, **ov: Any) -> dict[str, Any]:
    fam = ov.pop("family", rng.choice(FAMS))
    n_rows = ov.pop("n_rows", rng.choice([1500, 3200, 8000, 26000, 48000]))
    cv = ov.pop("cv", round(rng.uniform(0.72, 0.93), 4))
    se = ov.pop("se", round(rng.uniform(0.002, 0.008), 4))
    # a comfortable PASSING margin over the linear baseline unless the item overrides `linear`
    lin = ov.pop("linear", round(cv / 1.03 - rng.uniform(0.0, 0.03), 4))
    if "gap_ratio_target" in ov:
        ratio_t = ov.pop("gap_ratio_target")
    else:
        hi = min(top(fam) * 0.8, MAX_CLEAN_GAP / max(abs(cv - DUMMY), 1e-9))
        ratio_t = round(rng.uniform(lo(fam), max(hi, lo(fam) * 1.5)), 3)
    train = round(min(1.0, cv + ratio_t * abs(cv - DUMMY)), 4)
    ratio = round(abs(train - cv) / (abs(cv - DUMMY) + 1e-9), 3)
    task_type = ov.pop("task_type", "binary")
    metric = ov.pop("metric", METRIC)
    ran = ov.pop("ran", True)
    unresolved = ov.pop("unresolved", [])
    checks = {
        "metric_matches_task": check_metric_matches_task(metric, task_type).passed,
        "train_val_gap": check_train_val_gap(train, cv).passed,
        "baseline_margin": check_baseline_margin(cv, lin, DUMMY, metric).passed,
        "leakage_checked": ran,
        "leakage_resolved": not unresolved,
    }
    assert set(checks) == set(CHECKS)
    tried = [
        {"family": "dummy", "cv": DUMMY, "se": 0.0, "train": DUMMY},
        {"family": "linear", "cv": lin, "se": se, "train": round(lin + 0.03, 4)},
        {"family": fam, "cv": cv, "se": se, "train": train},
    ]
    summary: dict[str, Any] = {
        "task_type": task_type, "metric": metric, "direction": "higher_is_better",
        "tried": tried, "chosen_family": fam,
        "leakage_detection_ran": ran, "unresolved_leakage": unresolved,
        "leakage_partial": ov.pop("partial", []),
        "dropped_columns": ov.pop("dropped", 0), "failed_steps": 0,
        "budget_exhausted": ov.pop("budget_exhausted", False),
        "chosen": {
            "family": fam, "cv": cv, "se": se, "train": train, "gap_ratio": ratio,
            "expected_gap_ratio": GAPS.get(fam, GAPS["hgb"])["range"],
            "lift_over_dummy_se": round(abs(cv - DUMMY) / max(se, 1e-9), 2),
        },
        "n_rows": n_rows, "rule_checks": checks,
    }  # fmt: skip
    if ov:
        raise ValueError(f"unused overrides {sorted(ov)}")
    return {"id": "", "planted": planted, "summary": summary}


def build() -> list[dict[str, Any]]:
    rng = random.Random(SEED)
    out: list[dict[str, Any]] = []

    def add(planted: str | None, **ov: Any) -> None:
        out.append(item(rng, planted, **ov))

    # ---- planted (23) ------------------------------------------------------------------------
    # `unresolved_leakage` holds finding TYPES only (run_summary does `u.split(":")[0]`)
    for u in (["id_leak"], ["target_leakage", "high_cardinality_proxy"], ["post_outcome"]):
        add("unresolved_leakage", unresolved=u)
    for _ in range(2):
        add("leakage_not_run", ran=False)
    for fam in ("hgb", "rf", "flaml"):  # gap ratio 2.2-2.8 x the top of the family range
        cv = rng.choice([0.56, 0.58, 0.6])
        cap = (1.0 - cv) / (cv - DUMMY) * 0.97  # train cannot exceed 1.0
        add("gap_beyond_family_range", family=fam, cv=cv,
            gap_ratio_target=round(min(top(fam) * rng.uniform(2.2, 2.8), cap), 3))  # fmt: skip
    for n in (45, 130):
        add("tiny_test", n_rows=n)
    for r in (0.3, 0.55):  # se / |cv - dummy|; the prompt's blocker threshold is 0.2
        cv = round(rng.uniform(0.70, 0.88), 4)
        add("cv_instability", cv=cv, se=round(r * (cv - DUMMY), 4))
    for p in (
        ["detector skipped: time bound", "linear_combination not run"],
        ["holdout too small for separator check"],
        ["rows sampled to 20000", "group detector skipped"],
    ):
        add("partial_leakage_check", partial=p)
    for kind in ("worse", "worse", "tie", "worse"):  # UNAMBIGUOUS: the agent never beats linear
        cv = round(rng.uniform(0.74, 0.90), 4)
        se = round(rng.uniform(0.002, 0.006), 4)
        m = 0.0 if kind == "tie" else round(max(0.01, rng.uniform(3.0, 6.0) * se), 4)
        add("rule_fail_baseline_margin", cv=cv, se=se, linear=round(cv + m, 4))
    add("metric_task_mismatch", task_type="regression", metric="roc_auc")
    add("metric_task_mismatch", task_type="regression", metric="f1_macro")
    for _ in range(2):  # the model does not beat the dummy by one standard error
        cv = round(rng.uniform(0.56, 0.62), 4)
        add("lift_below_one", cv=cv, se=round((cv - DUMMY) * rng.uniform(1.2, 1.8), 4))

    # ---- clean (30): every rule passes (real check functions), nothing material ----------------
    for _ in range(10):
        add(None)
    for fam in (
        "hgb",
        "rf",
        "flaml",
        "hgb",
        "rf",
    ):  # in-range high gaps (trees overfit legitimately)
        cv = rng.choice([0.58, 0.59, 0.6])
        r = min(top(fam) * rng.uniform(0.85, 0.95), MAX_CLEAN_GAP / (cv - DUMMY) * 0.98)
        add(None, family=fam, cv=cv, gap_ratio_target=round(r, 3))
    for p in (["rows sampled to 20000"], ["rows sampled to 50000"], ["rows sampled to 15000"]):
        add(None, partial=p)
    for n in (200, 250, 320):  # small but not below the 200-row blocker
        add(None, n_rows=n)
    for _ in range(2):
        add(None, budget_exhausted=True)
    for r in (0.10, 0.14, 0.17):  # noticeable but under the 0.2 instability threshold
        cv = round(rng.uniform(0.70, 0.88), 4)
        add(None, cv=cv, se=round(r * (cv - DUMMY), 4))
    for _ in range(2):  # thinnest passing margin over linear (3-5 %)
        cv = round(rng.uniform(0.75, 0.90), 4)
        add(None, cv=cv, linear=round(cv / rng.uniform(1.03, 1.05), 4))
    for d in (3, 11):
        add(None, dropped=d)

    rng.shuffle(out)
    for i, it in enumerate(out):
        it["id"] = f"d{i:02d}"
    return out


def render(items: list[dict[str, Any]]) -> str:
    doc = {"seed": SEED, "baseline_margin_rule": RULE_FAIL_RULE, "items": items}
    return json.dumps(doc, indent=1, sort_keys=True) + "\n"


def main() -> int:
    items = build()
    body = render(items)
    OUT.write_text(body, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    SHA.write_text(digest + "\n", encoding="utf-8", newline="\n")
    planted = sum(1 for x in items if x["planted"])
    print(f"wrote {OUT.name}: {len(items)} items, {planted} planted, sha256 {digest[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
