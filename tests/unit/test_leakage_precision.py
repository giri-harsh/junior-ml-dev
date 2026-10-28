"""S5 precision layer: real-data false-positive patterns, label_noise, partitions."""

from __future__ import annotations

import numpy as np
import pandas as pd

from benchmarks.planted_bugs import generate as g
from benchmarks.real_dev import OPENML
from benchmarks.tasks.registry import load_registry
from datastory.roles import infer_roles
from leakage.detectors import detect
from leakage.models import DetectionMeta, Finding, FindingType, Severity

BY_NAME = {b.name: b for b in g.BUG_TYPES}


def _confirmed(findings: list[Finding], ftype: FindingType) -> list[Finding]:
    return [f for f in findings if f.type is ftype and f.severity != Severity.LOW]


def _honest_frame(n: int = 1500, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    duration = rng.integers(0, 60, n)  # discrete, predictive, many repeats: looks group-like
    x = rng.normal(size=n)
    y = (duration / 60 + 0.3 * x + rng.normal(scale=0.4, size=n) > 0.5).astype(int)
    return pd.DataFrame(
        {"duration": duration, "x": x, "total_day_minutes": rng.normal(size=n), "target": y}
    )


def test_honest_discrete_feature_is_not_group_leakage() -> None:
    fs = detect(_honest_frame(), "target", only=["group"])
    assert not _confirmed(fs, FindingType.GROUP_LEAKAGE)


def test_day_in_a_column_name_is_not_a_time_column() -> None:
    roles = infer_roles(_honest_frame(), "target")
    assert "total_day_minutes" not in roles.time_like


def test_time_name_without_shortcut_is_not_confirmed() -> None:
    df = _honest_frame()
    df["event_time"] = np.arange(len(df))  # ordered but unrelated to the label
    fs = detect(df, "target", only=["temporal"])
    assert not _confirmed(fs, FindingType.TEMPORAL_LEAKAGE)


def test_heavy_tailed_positive_column_is_not_unit_mismatch() -> None:
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"income": rng.lognormal(3, 1.5, 2000), "target": rng.integers(0, 2, 2000)})
    assert not detect(df, "target", only=["unit_mismatch"])


def test_natural_repeats_on_low_resolution_columns_are_low_only() -> None:
    rng = np.random.default_rng(2)
    df = pd.DataFrame(
        {
            "a": rng.integers(0, 4, 800),
            "b": rng.integers(0, 4, 800),
            "target": rng.integers(0, 2, 800),
        }
    )
    fs = detect(df, "target", only=["duplicates"])
    assert fs and all(f.severity is Severity.LOW for f in fs)


def test_copied_continuous_rows_are_confirmed_duplicates() -> None:
    v = g.build_variant(BY_NAME["duplicate_leak"], 1)
    assert _confirmed(
        detect(v["bugged"], "target", only=["duplicates"]), FindingType.DUPLICATE_ROWS
    )


def test_count_like_unique_integer_is_not_an_id() -> None:
    rng = np.random.default_rng(3)
    counts = rng.choice(np.arange(0, 10**7, 5), size=1000, replace=False)  # unique, gappy range
    df = pd.DataFrame({"bytes_read": counts, "target": rng.integers(0, 2, 1000)})
    assert infer_roles(df, "target").id_like == []


def test_post_outcome_name_hint_alone_is_low() -> None:
    rng = np.random.default_rng(4)
    df = pd.DataFrame(
        {
            "refund_amount": rng.normal(size=1000),
            "x": rng.normal(size=1000),
            "target": rng.integers(0, 2, 1000),
        }
    )
    fs = detect(df, "target")
    assert not [f for f in fs if f.columns == ["refund_amount"] and f.severity != Severity.LOW]


def test_label_noise_positive_and_negative() -> None:
    noisy = g.build_variant(BY_NAME["label_noise"], 1)
    fs = detect(noisy["bugged"], "target", only=["label_noise"])
    assert [f.type for f in fs] == [FindingType.LABEL_NOISE]
    ev = fs[0].evidence
    assert ev["estimated_noise_rate"] > 0.31 and len(ev["suspect_indices"]) <= 50
    assert not detect(noisy["twin"], "target", only=["label_noise"])


def test_label_noise_not_applicable_for_regression() -> None:
    rng = np.random.default_rng(5)
    df = pd.DataFrame({"x": rng.normal(size=300)})
    df["y"] = 2 * df["x"] + rng.normal(size=300)
    fs = detect(df, "y", DetectionMeta(task_type="regression"), only=["label_noise"])
    assert len(fs) == 1 and fs[0].severity is Severity.LOW and fs[0].evidence["applicable"] is False


def test_label_noise_is_deterministic() -> None:
    v = g.build_variant(BY_NAME["label_noise"], 0)
    a = [f.model_dump_json() for f in detect(v["bugged"], "target", only=["label_noise"])]
    b = [f.model_dump_json() for f in detect(v["bugged"].copy(), "target", only=["label_noise"])]
    assert a == b


def test_real_dev_is_disjoint_from_real_heldout() -> None:
    heldout = {t.name for t in load_registry()}
    assert heldout.isdisjoint(OPENML)
    assert len(OPENML) >= 12


def test_eval2_is_a_distinct_partition_with_new_seeds() -> None:
    parts = [g.partition_of(i) for i in range(g.VARIANTS_PER_TYPE)]
    assert parts.count("eval2") == 3
    a, b = g.build_variant(BY_NAME["target_proxy"], 2), g.build_variant(BY_NAME["target_proxy"], 6)
    assert g.variant_seed(a["id"]) != g.variant_seed(b["id"])
    assert b["labels"]["partition"] == "eval2"
