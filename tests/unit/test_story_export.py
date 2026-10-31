"""Tests for data story HTML export (PRD S7.5)."""

from __future__ import annotations

from datastory.export import story_to_html
from datastory.models import DatasetProfile, StoryResult, TargetProfile
from leakage.models import Finding, FindingType, Severity


def test_story_to_html_basic() -> None:
    """story_to_html generates valid HTML with profile info."""
    profile = DatasetProfile(
        n_rows=100,
        n_cols=3,
        duplicate_rows=5,
        target=TargetProfile(
            name="target",
            task_type="binary",
            n_classes=2,
            majority_fraction=0.6,
            missing_frac=0.0,
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
    story = StoryResult(
        profile=profile,
        findings=[],
        markdown="# Test Story\n\nThis is a test.",
        charts={},
    )

    html = story_to_html(story)

    assert "<!DOCTYPE html>" in html
    assert '<html lang="en">' in html
    assert "Data Story" in html
    assert "100" in html  # Row count
    assert "3" in html  # Column count
    assert "target" in html
    assert "binary" in html
    assert "# Test Story" in html


def test_story_to_html_with_findings() -> None:
    """story_to_html includes leakage findings."""
    profile = DatasetProfile(
        n_rows=50,
        n_cols=2,
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
    findings = [
        Finding(
            type=FindingType.TARGET_LEAKAGE,
            severity=Severity.HIGH,
            columns=["leak_col"],
            confidence=0.95,
        ),
        Finding(
            type=FindingType.ID_LIKE,
            severity=Severity.LOW,
            columns=["id_col"],
            confidence=0.7,
        ),
    ]
    story = StoryResult(
        profile=profile,
        findings=findings,
        markdown="Story text",
        charts={},
    )

    html = story_to_html(story)

    assert "Leakage Findings" in html
    assert "HIGH" in html
    assert "target_leakage" in html
    assert "leak_col" in html
    assert "0.95" in html
    assert "id_like" in html


def test_story_to_html_with_charts() -> None:
    """story_to_html includes chart specs embedded as JSON."""
    profile = DatasetProfile(
        n_rows=100,
        n_cols=2,
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
    charts = {
        "gallery": [
            {
                "chart_id": "test_chart_1",
                "spec": {"mark": "bar", "encoding": {"x": {"field": "a"}}},
                "alt_text": "Test bar chart",
                "template": "histogram_density",
                "columns": ["a"],
            },
        ],
        "more_charts": [
            {
                "chart_id": "test_chart_2",
                "spec": {"mark": "line"},
                "alt_text": "Test line chart",
                "template": "time_trend",
                "columns": ["b"],
            },
        ],
    }
    story = StoryResult(
        profile=profile,
        findings=[],
        markdown="Story with charts",
        charts=charts,
    )

    html = story_to_html(story)

    assert "Chart Gallery" in html
    assert "Test bar chart" in html
    assert "test_chart_1" in html
    assert '"mark":"bar"' in html
    assert "More Charts" in html
    assert "Test line chart" in html


def test_story_to_html_escapes_dangerous_content() -> None:
    """story_to_html properly escapes HTML in user content."""
    profile = DatasetProfile(
        n_rows=10,
        n_cols=1,
        duplicate_rows=0,
        target=TargetProfile(
            name="<script>alert('xss')</script>",
            task_type="binary",
            n_classes=2,
            majority_fraction=0.5,
            missing_frac=0.0,
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
    story = StoryResult(
        profile=profile,
        findings=[],
        markdown="<b>Bold text</b>",
        charts={},
    )

    html = story_to_html(story)

    # Should be escaped
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
    assert "&lt;b&gt;" in html


def test_story_to_html_self_contained() -> None:
    """story_to_html creates self-contained HTML with no external dependencies."""
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
    story = StoryResult(
        profile=profile,
        findings=[],
        markdown="Test",
        charts={},
    )

    html = story_to_html(story)

    # No external CSS links
    assert "<link" not in html or "href=" not in html
    # No external script tags
    assert "<script src=" not in html
    # Has inline styles
    assert "<style>" in html
    assert "</style>" in html


def test_story_to_html_custom_title() -> None:
    """story_to_html accepts custom title."""
    profile = DatasetProfile(
        n_rows=10,
        n_cols=1,
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
    story = StoryResult(
        profile=profile,
        findings=[],
        markdown="Test",
        charts={},
    )

    html = story_to_html(story, title="Custom Title")

    assert "<title>Custom Title</title>" in html
    assert "<h1>Custom Title</h1>" in html
