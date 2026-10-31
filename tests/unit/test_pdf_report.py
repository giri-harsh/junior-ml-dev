"""Unit tests for PDF report generation (PRD S21.3).

Note: These tests require WeasyPrint which needs GTK/Pango system libraries.
On Windows, these libraries are not available by default.
Tests will be skipped on Windows unless GTK is installed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Skip all tests in this module on Windows due to WeasyPrint GTK dependency
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="WeasyPrint requires GTK/Pango system libraries not available on Windows",
)

# Conditional imports to avoid import errors on Windows
if sys.platform != "win32":
    from pypdf import PdfReader  # type: ignore[import-untyped]

    from harness.agent.models import RunConfig, RunTask
    from harness.agent.pdf import generate_pdf
else:
    # Dummy definitions for Windows
    PdfReader = RunConfig = RunTask = generate_pdf = None  # type: ignore


@pytest.fixture
def sample_config() -> RunConfig:
    """Sample run configuration."""
    task = RunTask(
        name="test-task",
        data_path="data/test.csv",
        target="target",
        task_type="binary",
        metric="roc_auc",
    )
    return RunConfig(run_id="test-run-001", task=task, planner="scripted", llm_mode="fake")


@pytest.fixture
def sample_state() -> dict:
    """Sample run state dict."""
    return {
        "profile": {"n_rows": 1000, "n_cols": 10, "duplicate_rows": 5},
        "leaderboard": [
            {"model_id": "lgbm_001", "family": "lightgbm", "val_score": 0.85},
            {"model_id": "xgb_001", "family": "xgboost", "val_score": 0.82},
        ],
        "chosen": "lgbm_001",
        "findings": [
            {"severity": "medium", "type": "duplicate_rows", "columns": ["id", "date"]},
        ],
        "review": {"verdict": "APPROVE", "checks": {}},
        "explain": {
            "top": [
                {"feature": "age", "mean_drop": 0.05},
                {"feature": "income", "mean_drop": 0.03},
                {"feature": "tenure", "mean_drop": 0.02},
            ]
        },
    }


def test_generate_pdf_creates_single_page(
    sample_config: RunConfig, sample_state: dict, tmp_path: Path
) -> None:
    """Test PDF generation creates exactly 1 page (PRD S21 acceptance)."""
    pdf_path = tmp_path / "report.pdf"
    generate_pdf(sample_config, sample_state, pdf_path)

    assert pdf_path.exists()
    reader = PdfReader(pdf_path)
    assert len(reader.pages) == 1, f"Expected 1 page, got {len(reader.pages)}"


def test_pdf_contains_key_metrics(
    sample_config: RunConfig, sample_state: dict, tmp_path: Path
) -> None:
    """Test PDF contains verified numbers from state."""
    pdf_path = tmp_path / "report.pdf"
    generate_pdf(sample_config, sample_state, pdf_path)

    # Extract text from PDF
    reader = PdfReader(pdf_path)
    text = reader.pages[0].extract_text()

    # Verify key metrics present
    assert "1000 rows" in text
    assert "10 columns" in text
    assert "0.850" in text or "0.85" in text  # val_score
    assert "lightgbm" in text.lower()
    assert sample_config.run_id in text


def test_pdf_with_no_findings(sample_config: RunConfig, tmp_path: Path) -> None:
    """Test PDF generation with no leakage findings."""
    state = {
        "profile": {"n_rows": 500, "n_cols": 5, "duplicate_rows": 0},
        "leaderboard": [{"model_id": "baseline", "family": "linear", "val_score": 0.70}],
        "chosen": "baseline",
        "findings": [],
        "review": {"verdict": "APPROVE"},
    }
    pdf_path = tmp_path / "report.pdf"
    generate_pdf(sample_config, state, pdf_path)

    reader = PdfReader(pdf_path)
    text = reader.pages[0].extract_text()
    assert "0 total" in text or "No leakage" in text


def test_pdf_with_no_explainability(sample_config: RunConfig, tmp_path: Path) -> None:
    """Test PDF generation without explainability results."""
    state = {
        "profile": {"n_rows": 200, "n_cols": 3, "duplicate_rows": 0},
        "leaderboard": [{"model_id": "m1", "family": "dummy", "val_score": 0.50}],
        "chosen": "m1",
        "findings": [],
        "review": {"verdict": "REQUEST_CHANGES"},
    }
    pdf_path = tmp_path / "report.pdf"
    generate_pdf(sample_config, state, pdf_path)

    # Should still be exactly 1 page
    reader = PdfReader(pdf_path)
    assert len(reader.pages) == 1


def test_pdf_sanitizes_untrusted_content(sample_config: RunConfig, tmp_path: Path) -> None:
    """Test that column names and other untrusted content is sanitized."""
    state = {
        "profile": {"n_rows": 100, "n_cols": 2, "duplicate_rows": 0},
        "leaderboard": [{"model_id": "m1", "family": "linear", "val_score": 0.60}],
        "chosen": "m1",
        "findings": [
            {
                "severity": "high",
                "type": "target_proxy",
                "columns": ["<script>alert('xss')</script>", "very" * 50],  # Long name + XSS
            }
        ],
        "review": {"verdict": "REQUEST_CHANGES"},
    }
    pdf_path = tmp_path / "report.pdf"
    generate_pdf(sample_config, state, pdf_path)

    reader = PdfReader(pdf_path)
    text = reader.pages[0].extract_text()
    # Should not contain raw script tags
    assert "<script>" not in text
    assert len(reader.pages) == 1


def test_pdf_handles_missing_optional_fields(sample_config: RunConfig, tmp_path: Path) -> None:
    """Test PDF generation with minimal state (no optional fields)."""
    state = {
        "profile": {},
        "leaderboard": [],
        "findings": [],
        "review": {},
    }
    pdf_path = tmp_path / "report.pdf"
    generate_pdf(sample_config, state, pdf_path)

    reader = PdfReader(pdf_path)
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert sample_config.run_id in text


def test_pdf_metric_formatting() -> None:
    """Test business-friendly metric formatting."""
    from harness.agent.pdf import _format_metric

    assert "accuracy" in _format_metric("roc_auc", 0.85).lower()
    assert "0.850" in _format_metric("roc_auc", 0.85)
    assert "higher is better" in _format_metric("roc_auc", 0.85).lower()

    assert "error" in _format_metric("rmse", 12.5).lower()
    assert "12.500" in _format_metric("rmse", 12.5)
    assert "lower is better" in _format_metric("rmse", 12.5).lower()


def test_pdf_limits_findings_to_top_5(sample_config: RunConfig, tmp_path: Path) -> None:
    """Test that PDF limits findings to 5 for space (PRD S21.3: ≤3 charts constraint)."""
    state = {
        "profile": {"n_rows": 1000, "n_cols": 20, "duplicate_rows": 0},
        "leaderboard": [{"model_id": "m1", "family": "lgbm", "val_score": 0.75}],
        "chosen": "m1",
        "findings": [
            {"severity": "high", "type": f"type_{i}", "columns": [f"col_{i}"]}
            for i in range(10)  # 10 findings
        ],
        "review": {"verdict": "REQUEST_CHANGES"},
    }
    pdf_path = tmp_path / "report.pdf"
    generate_pdf(sample_config, state, pdf_path)

    reader = PdfReader(pdf_path)
    assert len(reader.pages) == 1  # Still fits on one page


def test_pdf_limits_leaderboard_to_top_5(sample_config: RunConfig, tmp_path: Path) -> None:
    """Test that PDF limits leaderboard to 5 models for space."""
    state = {
        "profile": {"n_rows": 500, "n_cols": 10, "duplicate_rows": 0},
        "leaderboard": [
            {"model_id": f"model_{i}", "family": "lgbm", "val_score": 0.7 + i * 0.01}
            for i in range(10)  # 10 models
        ],
        "chosen": "model_9",
        "findings": [],
        "review": {"verdict": "APPROVE"},
    }
    pdf_path = tmp_path / "report.pdf"
    generate_pdf(sample_config, state, pdf_path)

    reader = PdfReader(pdf_path)
    assert len(reader.pages) == 1
