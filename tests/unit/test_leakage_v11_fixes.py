"""Regression tests for two detector misfires, built from SYNTHETIC data only (no held-out sets)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from datastory.roles import infer_roles
from leakage.detectors import detect
from leakage.models import FindingType, Severity


def _count_frame(n: int = 2000, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    calls = rng.integers(0, 10, n)  # a predictive 10-level count, like "number of service calls"
    y = (calls + rng.normal(scale=2.0, size=n) > 5).astype(int)
    return pd.DataFrame({"calls": calls, "x": rng.normal(size=n), "target": y})


def test_low_cardinality_count_is_not_a_group_candidate() -> None:
    assert "calls" not in infer_roles(_count_frame(), "target").group_like
    fs = detect(_count_frame(), "target", only=["group"])
    assert not [f for f in fs if f.severity != Severity.LOW]


def test_identifier_named_numeric_column_is_still_a_group_candidate() -> None:
    df = _count_frame()
    df = df.rename(columns={"calls": "customer_id"})
    assert "customer_id" in infer_roles(df, "target").group_like


def test_string_categorical_with_many_levels_stays_a_candidate() -> None:
    rng = np.random.default_rng(1)
    n = 1500
    df = pd.DataFrame(
        {"region": rng.choice([f"r{i}" for i in range(12)], n), "x": rng.normal(size=n)}
    )
    df["target"] = (df.x > 0).astype(int)
    assert "region" in infer_roles(df, "target").group_like


def _ordinal_frame(n: int = 1500, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, 4))
    score = x @ np.array([1.0, 0.8, 0.5, 0.2]) + rng.normal(scale=1.0, size=n)
    q = np.clip(np.round(score * 1.2 + 6), 3, 9).astype(int)  # quality-like, 7 levels
    return pd.DataFrame({**{f"f{i}": x[:, i] for i in range(4)}, "quality": q})


def test_ordinal_target_is_not_flagged_for_label_noise() -> None:
    fs = detect(_ordinal_frame(), "quality", only=["label_noise"])
    assert fs and all(f.severity == Severity.LOW for f in fs)
    assert fs[0].type is FindingType.LABEL_NOISE and fs[0].evidence["applicable"] is False


def test_nominal_multiclass_label_noise_is_still_evaluated() -> None:
    rng = np.random.default_rng(2)
    n = 1500
    x = rng.normal(size=(n, 3))
    y = np.array(["a", "b", "c"])[np.digitize(x[:, 0], [-0.5, 0.5])]
    flip = rng.random(n) < 0.4
    y = np.where(flip, rng.choice(["a", "b", "c"], n), y)
    df = pd.DataFrame({**{f"f{i}": x[:, i] for i in range(3)}, "t": y})
    fs = detect(df, "t", only=["label_noise"])
    assert not any(f.evidence.get("applicable") is False for f in fs)


def test_measure_about_an_entity_is_not_an_entity_id() -> None:
    df = _count_frame().rename(columns={"calls": "number_customer_service_calls"})
    roles = infer_roles(df, "target")
    assert "number_customer_service_calls" not in roles.group_like
    for ok in ("customer", "account_number", "user_id", "household_key"):
        assert "x" not in roles.group_like  # sanity: continuous column never a candidate
        renamed = _count_frame().rename(columns={"calls": ok})
        assert ok in infer_roles(renamed, "target").group_like, ok
