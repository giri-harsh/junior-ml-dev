from __future__ import annotations

import numpy as np
import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from benchmarks.metrics import bootstrap_ci, normalized_score, paired_bootstrap_ci, passes


def test_normalized_score_endpoints() -> None:
    assert normalized_score(0.5, 0.5, 0.9, "roc_auc") == 0.0
    assert normalized_score(0.9, 0.5, 0.9, "roc_auc") == 1.0
    assert normalized_score(0.7, 0.5, 0.9, "roc_auc") == pytest.approx(0.5)


def test_normalized_score_error_metric_direction() -> None:
    # dummy rmse 10, flaml rmse 2: agent 2 -> 1.0, agent 10 -> 0.0, agent 6 -> 0.5
    assert normalized_score(2.0, 10.0, 2.0, "rmse") == pytest.approx(1.0)
    assert normalized_score(10.0, 10.0, 2.0, "rmse") == pytest.approx(0.0)
    assert normalized_score(6.0, 10.0, 2.0, "rmse") == pytest.approx(0.5)


def test_normalized_score_undefined_cases() -> None:
    assert normalized_score(0.8, 0.5, 0.5, "roc_auc") is None  # flaml == dummy
    assert normalized_score(0.8, 0.5, 0.5004, "roc_auc") is None  # tiny denominator
    assert normalized_score(0.8, 0.9, 0.5, "roc_auc") is None  # flaml worse than dummy


@given(
    st.floats(0.0, 1.0),
    st.floats(0.0, 1.0),
    st.sampled_from(["roc_auc", "rmse"]),
)
def test_property_monotone_in_agent_score(a: float, b: float, metric: str) -> None:
    dummy, flaml = (0.5, 0.9) if metric == "roc_auc" else (10.0, 2.0)
    na, nb = normalized_score(a, dummy, flaml, metric), normalized_score(b, dummy, flaml, metric)
    assume(na is not None and nb is not None and abs(a - b) > 1e-6)
    assert na is not None and nb is not None
    better = a > b if metric == "roc_auc" else a < b
    assert (na > nb) == better


def test_pass_rule_relative_margin() -> None:
    assert passes(0.82, 0.80, "roc_auc")  # 0.80 * 1.02 = 0.816
    assert not passes(0.81, 0.80, "roc_auc")
    assert passes(9.7, 10.0, "rmse", scale=100.0)  # 10 * 0.98 = 9.8
    assert not passes(9.9, 10.0, "rmse", scale=100.0)


def test_pass_rule_ceiling_clause() -> None:
    assert passes(0.985, 0.985, "roc_auc")  # linear >= 0.98: not worse than linear
    assert not passes(0.98, 0.985, "roc_auc")
    assert passes(1.0, 1.0, "rmse", scale=100.0)  # linear error <= 2% of scale
    assert not passes(1.1, 1.0, "rmse", scale=100.0)


def test_error_metric_requires_scale() -> None:
    with pytest.raises(ValueError):
        passes(1.0, 1.0, "rmse")


def test_bootstrap_ci_known_samples() -> None:
    mean, lo, hi = bootstrap_ci([1.0] * 10, n_resamples=500)
    assert mean == lo == hi == 1.0
    vals = list(np.linspace(0, 1, 30))
    mean, lo, hi = bootstrap_ci(vals, n_resamples=2000, seed=1)
    assert lo < mean < hi and hi - lo < 0.5
    assert bootstrap_ci(vals, n_resamples=2000, seed=1) == (mean, lo, hi)  # seeded


def test_paired_bootstrap_detects_consistent_gain() -> None:
    base = [0.5, 0.6, 0.7, 0.8, 0.55, 0.65]
    mean, lo, hi = paired_bootstrap_ci([b + 0.05 for b in base], base, n_resamples=1000)
    assert lo > 0 and mean == pytest.approx(0.05)
    with pytest.raises(ValueError):
        paired_bootstrap_ci([1.0], [1.0, 2.0])
