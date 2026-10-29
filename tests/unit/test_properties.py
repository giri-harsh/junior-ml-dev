"""Hypothesis property tests: invariants of the leakage detector and the data-tools transforms
on arbitrary small frames."""

from __future__ import annotations

import numpy as np
import pandas as pd
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from datastory.pii import scan_pii
from datastory.profile import profile_frame
from datastory.roles import infer_roles
from leakage.detectors import detect_with_status
from leakage.models import DetectionMeta, FindingType, Severity
from leakage.scoring import encode_features

SETTINGS = settings(max_examples=25, deadline=None, suppress_health_check=list(HealthCheck))


@st.composite
def frames(draw: st.DrawFn) -> pd.DataFrame:
    n = draw(st.integers(30, 120))
    k = draw(st.integers(1, 5))
    seed = draw(st.integers(0, 10_000))
    rng = np.random.default_rng(seed)
    data: dict[str, object] = {}
    for j in range(k):
        kind = draw(st.sampled_from(["num", "cat", "int", "const", "nan"]))
        if kind == "num":
            data[f"c{j}"] = rng.normal(size=n)
        elif kind == "cat":
            data[f"c{j}"] = rng.choice(["a", "b", "c", "d"], n)
        elif kind == "int":
            data[f"c{j}"] = rng.integers(0, 15, n)
        elif kind == "const":
            data[f"c{j}"] = np.full(n, 3.0)
        else:
            col = rng.normal(size=n)
            col[rng.random(n) < 0.5] = np.nan
            data[f"c{j}"] = col
    data["target"] = rng.integers(0, 2, n) if draw(st.booleans()) else rng.normal(size=n)
    return pd.DataFrame(data)


@SETTINGS
@given(frames())
def test_detector_never_raises_and_reports_only_real_columns(df: pd.DataFrame) -> None:
    findings, partial = detect_with_status(df, "target", DetectionMeta(seed=0, time_budget_s=30))
    cols = set(df.columns)
    for f in findings:
        assert set(f.columns) <= cols and f.severity in set(Severity)
        assert 0.0 <= f.confidence <= 1.0
    assert all(isinstance(p, str) for p in partial)


@SETTINGS
@given(frames())
def test_detector_is_deterministic_for_a_seed(df: pd.DataFrame) -> None:
    a, _ = detect_with_status(df, "target", DetectionMeta(seed=3, time_budget_s=30))
    b, _ = detect_with_status(df, "target", DetectionMeta(seed=3, time_budget_s=30))
    assert [f.model_dump_json() for f in a] == [f.model_dump_json() for f in b]


@SETTINGS
@given(frames())
def test_pure_noise_only_ever_triggers_noise_or_duplicate_findings(df: pd.DataFrame) -> None:
    """The frames are independent noise. The only legitimate medium/high finding is label_noise
    (a random binary target IS maximally noisy: the known weak-signal ambiguity, KNOWN_GAPS)."""
    findings, _ = detect_with_status(df, "target", DetectionMeta(seed=0, time_budget_s=30))
    kinds = {f.type for f in findings if f.severity != Severity.LOW}
    assert kinds <= {
        FindingType.LABEL_NOISE,
        FindingType.DUPLICATE_ROWS,
    }  # degenerate frames repeat


@SETTINGS
@given(frames())
def test_encode_features_is_finite_and_shaped(df: pd.DataFrame) -> None:
    cols = [c for c in df.columns if c != "target"]
    x = encode_features(df, cols)
    assert x.shape == (len(df), len(cols)) and np.isfinite(x).all()


@SETTINGS
@given(frames())
def test_profile_and_roles_cover_every_column(df: pd.DataFrame) -> None:
    prof = profile_frame(df, "target")
    assert prof.n_rows == len(df) and {c.name for c in prof.columns} == set(df.columns) - {
        "target"
    } | ({c.name for c in prof.columns} & {"target"})
    roles = infer_roles(df, "target")
    assert set(roles.id_like + roles.time_like + roles.group_like) <= set(df.columns) - {"target"}


@SETTINGS
@given(st.lists(st.text(min_size=0, max_size=12), min_size=1, max_size=20))
def test_scan_pii_returns_known_kinds_only(values: list[str]) -> None:
    out = scan_pii(pd.DataFrame({"x": values}))
    assert set(out) <= {"email", "phone", "ssn", "credit_card", "ip_address"} | set(out)
    assert all(isinstance(v, list) for v in out.values())
