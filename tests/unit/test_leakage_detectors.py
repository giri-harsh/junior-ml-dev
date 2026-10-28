from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from benchmarks.planted_bugs import generate as g
from datastory.roles import infer_roles
from leakage.detectors import detect
from leakage.models import DetectionMeta, Finding, FindingType, Severity

BY_NAME = {b.name: b for b in g.BUG_TYPES}
DEV_VARIANT = 1  # unit tests only touch dev-partition variants (0-2)


def _types(findings: list[Finding], min_sev: Severity = Severity.MEDIUM) -> set[FindingType]:
    order = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2}
    return {f.type for f in findings if order[f.severity] >= order[min_sev]}


def _pair(name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    v = g.build_variant(BY_NAME[name], DEV_VARIANT)
    return v["bugged"], v["twin"]


@pytest.mark.parametrize(
    ("bug", "expected"),
    [
        ("target_proxy", {FindingType.POST_OUTCOME, FindingType.TARGET_LEAKAGE}),
        ("duplicate_leak", {FindingType.DUPLICATE_ROWS}),
        ("temporal_leak", {FindingType.TEMPORAL_LEAKAGE}),
        ("group_leak", {FindingType.GROUP_LEAKAGE}),
        ("id_correlated", {FindingType.ID_LEAK}),
        ("unit_mismatch", {FindingType.UNIT_MISMATCH}),
        ("poisoned_name", {FindingType.SUSPICIOUS_COLUMN_NAME}),
    ],
)
def test_detector_positive_and_negative(bug: str, expected: set[FindingType]) -> None:
    bugged, twin = _pair(bug)
    assert expected & _types(detect(bugged, "target"))
    assert not _types(detect(twin, "target"))


def test_post_outcome_uses_name_hint_and_localises_column() -> None:
    bugged, _ = _pair("target_proxy")
    f = next(x for x in detect(bugged, "target") if x.columns == ["refund_issued"])
    assert f.type is FindingType.POST_OUTCOME and f.evidence["name_hint"] == "refund"
    renamed = bugged.rename(columns={"refund_issued": "zz9"})
    f2 = next(x for x in detect(renamed, "target") if x.columns == ["zz9"])
    assert f2.type is FindingType.TARGET_LEAKAGE  # no hint -> generic target leakage


def test_group_finding_lists_group_constant_columns() -> None:
    bugged, _ = _pair("group_leak")
    f = next(x for x in detect(bugged, "target") if x.type is FindingType.GROUP_LEAKAGE)
    assert f.columns[0] == "customer_id" and "account_age" in f.columns


def test_id_like_without_signal_is_advisory_only() -> None:
    _, twin = _pair("id_correlated")
    fs = detect(twin, "target")
    assert any(f.type is FindingType.ID_LIKE and f.severity is Severity.LOW for f in fs)
    assert not _types(fs)


def test_train_test_contamination_positive_and_negative() -> None:
    _, twin = _pair("target_proxy")
    train, hold = twin.iloc[:800], twin.iloc[800:]
    clean = detect(train, "target", DetectionMeta(holdout=hold), only=["contamination"])
    assert clean == []
    leaked = pd.concat([hold, train.iloc[:50]], ignore_index=True)
    fs = detect(train, "target", DetectionMeta(holdout=leaked), only=["contamination"])
    assert [f.type for f in fs] == [FindingType.TRAIN_TEST_CONTAMINATION]


def test_high_cardinality_proxy_on_categorical() -> None:
    rng = np.random.default_rng(0)
    n = 600
    y = rng.integers(0, 2, n)
    # each category appears ~3 times and always carries one label -> OOF encoding can still learn
    # it only if categories repeat across folds: make 150 categories, label fixed per category
    cat = rng.integers(0, 150, n)
    label_by_cat = rng.integers(0, 2, 150)
    df = pd.DataFrame(
        {"x": rng.normal(size=n), "city": cat.astype(str), "target": label_by_cat[cat]}
    )
    fs = detect(df, "target", only=["target_leakage"])
    assert any(f.type is FindingType.HIGH_CARDINALITY_PROXY and f.columns == ["city"] for f in fs)
    del y


def test_regression_target_leak_detected() -> None:
    rng = np.random.default_rng(1)
    n = 500
    x = rng.normal(size=n)
    y = 3 * x + rng.normal(size=n)
    df = pd.DataFrame(
        {"x": x, "noise": rng.normal(size=n), "leak": y + rng.normal(size=n) * 0.01, "y": y}
    )
    fs = detect(df, "y", only=["target_leakage"])
    assert [f.columns for f in fs if f.severity is Severity.HIGH] == [["leak"]] or any(
        f.columns == ["leak"] for f in fs
    )


def test_roles_inference() -> None:
    n = 400
    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {
            "row": np.arange(n),
            "event_date": np.arange(n)[::-1],
            "customer": rng.integers(0, 40, n),
            "x": rng.normal(size=n),
            "label": rng.integers(0, 2, n),
        }
    )
    r = infer_roles(df, "label")
    assert r.id_like == ["row"] and r.time_like == ["event_date"] and r.group_like == ["customer"]


@given(seed=st.integers(0, 5), n=st.integers(120, 220))
@settings(max_examples=6, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_property_detection_is_deterministic(seed: int, n: int) -> None:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(
        {
            "a": rng.normal(size=n),
            "b": rng.integers(0, 5, n).astype(str),
            "event_time": np.arange(n),
            "target": rng.integers(0, 2, n),
        }
    )
    first = [f.model_dump_json() for f in detect(df, "target", DetectionMeta(seed=seed))]
    second = [f.model_dump_json() for f in detect(df.copy(), "target", DetectionMeta(seed=seed))]
    assert first == second


def test_detectors_do_not_read_label_files() -> None:
    import inspect

    import leakage.detectors as d
    import leakage.scoring as s

    src = inspect.getsource(d) + inspect.getsource(s)
    for banned in ("labels.json", "planted_bugs", "bug_type", "expected_detector"):
        assert banned not in src


def test_missing_target_raises() -> None:
    with pytest.raises(KeyError):
        detect(pd.DataFrame({"a": [1, 2, 3]}), "nope")
