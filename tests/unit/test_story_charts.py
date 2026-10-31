"""Tests for chart integration in data story (PRD S6)."""

from __future__ import annotations

import pandas as pd
import pytest

from datastory.models import ColumnProfile, DatasetProfile, TargetProfile
from datastory.story import build_charts


def test_build_charts_no_dataframe() -> None:
    """build_charts returns empty dict when df is not a DataFrame."""
    profile = DatasetProfile(
        n_rows=100,
        n_cols=3,
        duplicate_rows=0,
        target=None,
        columns=[],
        constant_columns=[],
        near_constant_columns=[],
        high_missing_columns=[],
        high_cardinality_columns=[],
        suspected_id=[],
        suspected_time=[],
        suspected_group=[],
    )
    result = build_charts("not a dataframe", profile, [], top_n=12)
    assert result == {"gallery": [], "more_charts": []}


def test_build_charts_no_target() -> None:
    """build_charts returns empty dict when profile has no target."""
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    profile = DatasetProfile(
        n_rows=3,
        n_cols=2,
        duplicate_rows=0,
        target=None,
        columns=[
            ColumnProfile(
                name="a",
                semantic_type="numeric",
                dtype="int64",
                n_unique=3,
                missing_frac=0.0,
                near_constant=False,
                target_association=None,
                association_method=None,
            ),
        ],
        constant_columns=[],
        near_constant_columns=[],
        high_missing_columns=[],
        high_cardinality_columns=[],
        suspected_id=[],
        suspected_time=[],
        suspected_group=[],
    )
    result = build_charts(df, profile, [], top_n=12)
    assert result == {"gallery": [], "more_charts": []}


def test_build_charts_target_not_in_df() -> None:
    """build_charts returns empty when target column doesn't exist in df."""
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    profile = DatasetProfile(
        n_rows=3,
        n_cols=2,
        duplicate_rows=0,
        target=TargetProfile(
            name="target",
            task_type="classification",
            n_classes=2,
            majority_fraction=0.6,
            missing_frac=0.0,
            skew=None,
        ),
        columns=[],
        constant_columns=[],
        near_constant_columns=[],
        high_missing_columns=[],
        high_cardinality_columns=[],
        suspected_id=[],
        suspected_time=[],
        suspected_group=[],
    )
    result = build_charts(df, profile, [], top_n=12)
    assert result == {"gallery": [], "more_charts": []}


def test_build_charts_with_valid_data() -> None:
    """build_charts generates charts when valid df+profile+target."""
    df = pd.DataFrame(
        {
            "feature1": [1.0, 2.0, 3.0, 4.0, 5.0] * 20,
            "feature2": [10.0, 20.0, 30.0, 40.0, 50.0] * 20,
            "target": [0, 1, 0, 1, 0] * 20,
        }
    )
    profile = DatasetProfile(
        n_rows=100,
        n_cols=3,
        duplicate_rows=0,
        target=TargetProfile(
            name="target",
            task_type="classification",
            n_classes=2,
            majority_fraction=0.5,
            missing_frac=0.0,
            skew=None,
        ),
        columns=[
            ColumnProfile(
                name="feature1",
                semantic_type="numeric",
                dtype="float64",
                n_unique=5,
                missing_frac=0.0,
                near_constant=False,
                target_association=0.8,
                association_method="mutual_info",
            ),
            ColumnProfile(
                name="feature2",
                semantic_type="numeric",
                dtype="float64",
                n_unique=5,
                missing_frac=0.0,
                near_constant=False,
                target_association=0.6,
                association_method="mutual_info",
            ),
            ColumnProfile(
                name="target",
                semantic_type="categorical",
                dtype="int64",
                n_unique=2,
                missing_frac=0.0,
                near_constant=False,
                target_association=None,
                association_method=None,
            ),
        ],
        constant_columns=[],
        near_constant_columns=[],
        high_missing_columns=[],
        high_cardinality_columns=[],
        suspected_id=[],
        suspected_time=[],
        suspected_group=[],
    )
    insights = [{"id": "insight1", "type": "high_correlation", "importance": 1.0}]
    result = build_charts(df, profile, insights, top_n=12)
    
    assert "gallery" in result
    assert "more_charts" in result
    assert isinstance(result["gallery"], list)
    assert isinstance(result["more_charts"], list)
    # Should have at least target balance + some numeric charts
    total_charts = len(result["gallery"]) + len(result["more_charts"])
    assert total_charts > 0


def test_build_charts_respects_top_n() -> None:
    """build_charts respects top_n parameter for gallery size."""
    df = pd.DataFrame(
        {
            "f1": list(range(100)),
            "f2": list(range(100)),
            "f3": list(range(100)),
            "f4": list(range(100)),
            "f5": list(range(100)),
            "target": [0, 1] * 50,
        }
    )
    profile = DatasetProfile(
        n_rows=100,
        n_cols=6,
        duplicate_rows=0,
        target=TargetProfile(
            name="target",
            task_type="classification",
            n_classes=2,
            majority_fraction=0.5,
            missing_frac=0.0,
            skew=None,
        ),
        columns=[
            ColumnProfile(
                name=f"f{i}",
                semantic_type="numeric",
                dtype="int64",
                n_unique=100,
                missing_frac=0.0,
                near_constant=False,
                target_association=0.5,
                association_method="mutual_info",
            )
            for i in range(1, 6)
        ]
        + [
            ColumnProfile(
                name="target",
                semantic_type="categorical",
                dtype="int64",
                n_unique=2,
                missing_frac=0.0,
                near_constant=False,
                target_association=None,
                association_method=None,
            ),
        ],
        constant_columns=[],
        near_constant_columns=[],
        high_missing_columns=[],
        high_cardinality_columns=[],
        suspected_id=[],
        suspected_time=[],
        suspected_group=[],
    )
    result = build_charts(df, profile, [], top_n=3)
    
    # Gallery should have at most 3 charts
    assert len(result["gallery"]) <= 3


def test_build_charts_includes_chart_metadata() -> None:
    """build_charts includes proper metadata in chart specs."""
    df = pd.DataFrame({"a": [1, 2, 3, 4, 5], "target": [0, 1, 0, 1, 0]})
    profile = DatasetProfile(
        n_rows=5,
        n_cols=2,
        duplicate_rows=0,
        target=TargetProfile(
            name="target",
            task_type="classification",
            n_classes=2,
            majority_fraction=0.6,
            missing_frac=0.0,
            skew=None,
        ),
        columns=[
            ColumnProfile(
                name="a",
                semantic_type="numeric",
                dtype="int64",
                n_unique=5,
                missing_frac=0.0,
                near_constant=False,
                target_association=0.7,
                association_method="mutual_info",
            ),
            ColumnProfile(
                name="target",
                semantic_type="categorical",
                dtype="int64",
                n_unique=2,
                missing_frac=0.0,
                near_constant=False,
                target_association=None,
                association_method=None,
            ),
        ],
        constant_columns=[],
        near_constant_columns=[],
        high_missing_columns=[],
        high_cardinality_columns=[],
        suspected_id=[],
        suspected_time=[],
        suspected_group=[],
    )
    result = build_charts(df, profile, [], top_n=12)
    
    # Check that charts have required fields
    all_charts = result["gallery"] + result["more_charts"]
    for chart in all_charts:
        assert "chart_id" in chart
        assert "spec" in chart
        assert "alt_text" in chart
        assert "template" in chart
        assert "columns" in chart
        assert isinstance(chart["spec"], dict)
        assert isinstance(chart["alt_text"], str)
        assert len(chart["alt_text"]) > 0
