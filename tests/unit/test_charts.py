"""Unit tests for declarative charts (PRD S6)."""

from __future__ import annotations

import pandas as pd
import pytest

from datastory.charts import ChartSpec, generate_chart_candidates, render_spec_to_svg
from datastory.charts.ranking import rank_charts
from datastory.charts.templates import (
    box_by_class,
    clustered_heatmap,
    histogram_with_density,
    mi_bar,
    missingness_matrix,
    target_balance,
    time_trend,
    top_k_bar,
)


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """Sample dataframe for testing."""
    return pd.DataFrame(
        {
            "feature1": [1.0, 2.0, 3.0, 4.0, 5.0] * 20,
            "feature2": [10, 20, 30, 40, 50] * 20,
            "category": (["A", "B", "C"] * 34)[:100],
            "target": ([0, 1] * 50),
        }
    )


@pytest.fixture
def profile() -> dict:
    """Sample profile dict."""
    return {
        "columns": [
            {"name": "feature1", "semantic_type": "numeric"},
            {"name": "feature2", "semantic_type": "numeric"},
            {"name": "category", "semantic_type": "categorical"},
            {"name": "target", "semantic_type": "categorical"},
        ]
    }


def test_histogram_template(sample_df: pd.DataFrame) -> None:
    """Test histogram+density template."""
    chart = histogram_with_density(sample_df, "feature1")
    assert chart.template == "histogram_density"
    assert "feature1" in chart.columns
    assert chart.alt_text
    # Chart is a layered spec with multiple marks (bar + line)
    assert "layer" in chart.spec or "mark" in chart.spec
    assert chart.size_kb() < 500


def test_top_k_bar_template(sample_df: pd.DataFrame) -> None:
    """Test top-k bar template."""
    chart = top_k_bar(sample_df, "category", k=3)
    assert chart.template == "top_k_bar"
    assert "category" in chart.columns
    assert chart.alt_text
    assert chart.size_kb() < 500


def test_target_balance_template(sample_df: pd.DataFrame) -> None:
    """Test target balance template."""
    chart = target_balance(sample_df, "target")
    assert chart.template == "target_balance"
    assert "target" in chart.columns
    assert "balance" in chart.alt_text.lower()
    assert chart.size_kb() < 500


def test_box_by_class_template(sample_df: pd.DataFrame) -> None:
    """Test box plot by class template."""
    chart = box_by_class(sample_df, "feature1", "target")
    assert chart.template == "box_by_class"
    assert "feature1" in chart.columns
    assert "target" in chart.columns
    assert chart.size_kb() < 500


def test_mi_bar_template() -> None:
    """Test MI bar template."""
    mi_scores = {"feat_a": 0.5, "feat_b": 0.3, "feat_c": 0.8}
    chart = mi_bar(mi_scores)
    assert chart.template == "mi_bar"
    assert len(chart.columns) == 3
    assert chart.alt_text
    assert chart.size_kb() < 500


def test_missingness_matrix() -> None:
    """Test missingness matrix."""
    df = pd.DataFrame({"a": [1, None, 3], "b": [None, 2, 3], "c": [1, 2, 3]})
    chart = missingness_matrix(df)
    assert chart.template == "missingness_matrix"
    assert chart.alt_text
    assert chart.size_kb() < 500


def test_clustered_heatmap(sample_df: pd.DataFrame) -> None:
    """Test clustered heatmap."""
    chart = clustered_heatmap(sample_df, ["feature1", "feature2"])
    assert chart.template == "clustered_heatmap"
    assert "feature1" in chart.columns or "feature2" in chart.columns
    assert chart.alt_text
    assert chart.size_kb() < 500


def test_time_trend() -> None:
    """Test time trend template."""
    df = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=100),
            "value": range(100),
        }
    )
    chart = time_trend(df, "date", "value")
    assert chart.template == "time_trend"
    assert "date" in chart.columns
    assert "value" in chart.columns
    assert chart.size_kb() < 500


def test_generate_chart_candidates(sample_df: pd.DataFrame, profile: dict) -> None:
    """Test chart candidate generation."""
    insights = [{"id": "ins1", "type": "mutual_information", "facts": {"mi_scores": {"feature1": 0.5, "feature2": 0.3}}}]  # fmt: skip
    charts = generate_chart_candidates(sample_df, "target", insights, profile)
    assert len(charts) > 0
    # Should have target balance
    assert any(c.template == "target_balance" for c in charts)
    # Should have at least one histogram
    assert any(c.template == "histogram_density" for c in charts)
    # All charts should have alt text
    assert all(c.alt_text for c in charts)
    # All charts under size limit
    assert all(c.size_kb() < 500 for c in charts)


def test_rank_charts(sample_df: pd.DataFrame) -> None:
    """Test chart ranking."""
    charts = [
        histogram_with_density(sample_df, "feature1"),
        histogram_with_density(sample_df, "feature2"),
        target_balance(sample_df, "target"),
        top_k_bar(sample_df, "category"),
    ]
    insights = []
    gallery, more = rank_charts(charts, insights, top_n=3)
    assert len(gallery) <= 3
    assert len(gallery) + len(more) <= len(charts)
    # Gallery charts should be ranked
    assert all(c.rank is not None for c in gallery)
    # Ranks should be 1-indexed and unique
    ranks = [c.rank for c in gallery if c.rank is not None]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks)


def test_rank_charts_no_duplicate_columns() -> None:
    """Test that no two gallery charts share identical column sets (PRD S6 acceptance)."""
    df = pd.DataFrame({"a": range(10), "b": range(10), "c": range(10), "target": [0, 1] * 5})
    charts = [
        histogram_with_density(df, "a"),
        histogram_with_density(df, "a"),  # Duplicate column set
        histogram_with_density(df, "b"),
        target_balance(df, "target"),
    ]
    gallery, _ = rank_charts(charts, [], top_n=10)
    col_sets = [frozenset(c.columns) for c in gallery]
    assert len(col_sets) == len(set(col_sets)), "Gallery has duplicate column sets"


def test_render_to_svg(sample_df: pd.DataFrame) -> None:
    """Test SVG rendering (PRD S6.4)."""
    chart = histogram_with_density(sample_df, "feature1")
    svg = render_spec_to_svg(chart)
    assert isinstance(svg, str)
    assert svg.startswith("<svg")
    assert "feature1" in svg or "Distribution" in svg


def test_all_templates_have_alt_text(sample_df: pd.DataFrame) -> None:
    """PRD S6 acceptance: 100% have alt text."""
    charts = [
        histogram_with_density(sample_df, "feature1"),
        top_k_bar(sample_df, "category"),
        target_balance(sample_df, "target"),
        box_by_class(sample_df, "feature1", "target"),
        mi_bar({"a": 0.5, "b": 0.3}),
    ]
    assert all(c.alt_text and len(c.alt_text) > 0 for c in charts)


def test_chart_spec_size_under_limit() -> None:
    """PRD S6 acceptance: each spec ≤500 KB."""
    # Create a large chart with many data points
    df = pd.DataFrame({"a": range(1000), "b": range(1000)})
    chart = histogram_with_density(df, "a")
    assert chart.size_kb() < 500


def test_novelty_penalty_reduces_duplicate_columns() -> None:
    """Test that novelty penalty works to reduce score for duplicate column usage."""
    from datastory.charts.ranking import _novelty_penalty

    df = pd.DataFrame({"a": range(10), "b": range(10)})
    chart1 = histogram_with_density(df, "a")
    chart2 = histogram_with_density(df, "a")  # Same columns
    chart3 = histogram_with_density(df, "b")  # Different columns

    penalty2 = _novelty_penalty(chart2, [chart1])
    penalty3 = _novelty_penalty(chart3, [chart1])

    assert penalty2 < penalty3, "Duplicate columns should have lower novelty"
