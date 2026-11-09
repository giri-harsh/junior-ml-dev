"""Chart template branches the main chart tests do not reach: sampling, rate-by-category with
Wilson intervals, the heatmap and missingness fallbacks, and candidate selection by target type."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from datastory.charts.templates import (
    MAX_POINTS,
    _sample,
    clustered_heatmap,
    generate_chart_candidates,
    histogram_with_density,
    missingness_matrix,
    rate_by_category,
)
from leakage.evaluate import wilson


def _rows(spec: dict) -> list[dict]:
    return next(iter(spec["datasets"].values()))  # type: ignore[no-any-return]


def test_sample_caps_large_frames_deterministically_and_keeps_small_ones() -> None:
    small = pd.DataFrame({"x": range(10)})
    assert _sample(small) is small
    big = pd.DataFrame({"x": range(MAX_POINTS + 700)})
    a, b = _sample(big), _sample(big)
    assert len(a) == MAX_POINTS
    assert a.equals(b)  # fixed random_state
    assert list(a.index) == list(range(MAX_POINTS))  # index reset


def test_histogram_of_a_big_column_is_built_from_at_most_5k_points() -> None:
    df = pd.DataFrame({"v": np.arange(MAX_POINTS * 2, dtype=float)})
    chart = histogram_with_density(df, "v")
    assert len(_rows(chart.spec)) == MAX_POINTS
    assert chart.columns == ["v"]


def test_rate_by_category_reports_rates_with_wilson_error_bars() -> None:
    df = pd.DataFrame(
        {
            "grp": ["a"] * 20 + ["b"] * 10,
            "y": [1] * 5 + [0] * 15 + [1] * 9 + [0] * 1,
        }
    )
    chart = rate_by_category(df, "grp", "y", insight_id="ins-7")
    assert chart.template == "rate_by_category"
    assert chart.chart_id == "rate_grp_y"
    assert chart.insight_id == "ins-7"
    assert chart.columns == ["grp", "y"]
    assert "Wilson" in chart.alt_text
    rows = {r["category"]: r for r in _rows(chart.spec)}
    assert rows["a"]["rate"] == pytest.approx(0.25)
    assert rows["b"]["rate"] == pytest.approx(0.9)
    lo, hi = wilson(5, 20)
    assert rows["a"]["ci_low"] == pytest.approx(lo)
    assert rows["a"]["ci_high"] == pytest.approx(hi)
    assert rows["b"]["ci_low"] < rows["b"]["rate"] < rows["b"]["ci_high"]
    assert chart.size_kb() < 500


def test_heatmap_with_one_numeric_column_falls_back_to_a_plain_matrix() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0, 4.0], "label": list("abcd")})
    chart = clustered_heatmap(df, ["n", "label"])
    assert chart.chart_id == "heatmap_corr"  # not the clustered id
    assert chart.columns == ["n"]  # non-numeric columns are dropped
    assert _rows(chart.spec) == [{"var1": "n", "var2": "n", "correlation": 1.0}]


def test_heatmap_with_several_columns_is_clustered_and_symmetric() -> None:
    rng = np.random.default_rng(0)
    a = rng.normal(size=60)
    df = pd.DataFrame({"a": a, "b": a + rng.normal(scale=0.1, size=60), "c": rng.normal(size=60)})
    chart = clustered_heatmap(df, ["a", "b", "c"])
    assert chart.chart_id == "heatmap_clustered"
    rows = _rows(chart.spec)
    corr = {(r["var1"], r["var2"]): r["correlation"] for r in rows}
    assert len(rows) == 9
    assert corr[("a", "b")] == pytest.approx(corr[("b", "a")])
    assert corr[("a", "b")] > 0.9 > abs(corr[("a", "c")])


def test_missingness_matrix_without_gaps_says_so() -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    chart = missingness_matrix(df, insight_id="m1")
    assert chart.chart_id == "missing_matrix"
    assert "no missing data" in chart.alt_text
    assert chart.columns == ["a", "b"]
    assert chart.insight_id == "m1"


def test_missingness_matrix_marks_only_the_missing_cells() -> None:
    df = pd.DataFrame({"a": [1.0, None, 3.0], "b": [None, None, "z"]})
    chart = missingness_matrix(df)
    cells = _rows(chart.spec)
    assert sorted((c["column"], c["row"]) for c in cells) == [("a", 1), ("b", 0), ("b", 1)]
    assert "first 3 rows" in chart.alt_text


@pytest.fixture
def mixed_frame() -> pd.DataFrame:
    n = 90
    rng = np.random.default_rng(3)
    df = pd.DataFrame(
        {
            "x1": rng.normal(size=n),
            "x2": rng.normal(size=n),
            "x3": rng.normal(size=n),
            "when": pd.date_range("2021-01-01", periods=n),
            "cls": np.where(rng.normal(size=n) > 0, "yes", "no"),
        }
    )
    df.loc[df.index % 7 == 0, "x1"] = np.nan
    return df


PROFILE = {
    "columns": [
        {"name": "x1", "semantic_type": "numeric"},
        {"name": "x2", "semantic_type": "numeric"},
        {"name": "x3", "semantic_type": "numeric"},
        {"name": "when", "semantic_type": "datetime"},
        {"name": "cls", "semantic_type": "categorical"},
    ]
}


def test_candidates_for_a_class_target_cover_box_missingness_time_and_heatmap(
    mixed_frame: pd.DataFrame,
) -> None:
    charts = generate_chart_candidates(mixed_frame, "cls", [], PROFILE)
    templates = [c.template for c in charts]
    assert templates[0] == "target_balance"
    assert templates.count("box_by_class") == 3
    assert "missingness_matrix" in templates  # x1 has gaps
    assert "time_trend" in templates
    assert "clustered_heatmap" in templates
    assert "mi_bar" not in templates  # no MI insight supplied
    assert all(c.alt_text and c.size_kb() < 500 for c in charts)


def test_candidates_skip_box_plots_for_a_numeric_target() -> None:
    n = 40
    df = pd.DataFrame({"x1": np.arange(n, dtype=float), "price": np.arange(n, dtype=float) * 2})
    profile = {
        "columns": [
            {"name": "x1", "semantic_type": "numeric"},
            {"name": "price", "semantic_type": "numeric"},
        ]
    }
    templates = [c.template for c in generate_chart_candidates(df, "price", [], profile)]
    assert "box_by_class" not in templates
    assert "missingness_matrix" not in templates  # nothing missing
    assert templates.count("histogram_density") == 1  # the target itself is excluded


def test_candidates_use_mutual_information_insight_when_present(
    mixed_frame: pd.DataFrame,
) -> None:
    insights = [
        {"type": "other", "facts": {}},
        {"type": "mutual_information", "facts": {"mi_scores": {"x1": 0.4, "x2": 0.1}}},
    ]
    charts = generate_chart_candidates(mixed_frame, "cls", insights, PROFILE)
    mi = [c for c in charts if c.template == "mi_bar"]
    assert len(mi) == 1 and mi[0].columns == ["x1", "x2"]
