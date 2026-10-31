"""Tests for reproducibility notebook generation (PRD S21.1)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import nbformat
import pytest

from harness.agent.models import RunBudget, RunConfig, RunTask, Step, StepRecord
from harness.agent.notebook import generate_notebook, write_notebook


@pytest.fixture
def sample_config() -> RunConfig:
    """Sample run configuration."""
    return RunConfig(
        run_id="test-run-123",
        task=RunTask(
            name="test-task",
            data_path="data/test.parquet",
            target="target",
            task_type="binary",
            metric="roc_auc",
            seed=42,
        ),
        planner="scripted",
        llm_mode="none",
        budget=RunBudget(),
    )


@pytest.fixture
def sample_state() -> dict:
    """Sample run state."""
    return {
        "chosen": "model_001",
        "models": {
            "model_001": {
                "family": "rf",
                "val_score": 0.85,
            },
        },
        "dropped": ["id_col", "leak_col"],
        "final_code": "# Feature engineering\ndf['new_feature'] = df['a'] + df['b']",
    }


def test_generate_notebook_basic(sample_config: RunConfig, sample_state: dict) -> None:
    """generate_notebook creates valid notebook structure."""
    nb = generate_notebook(sample_config, sample_state, [])
    
    assert isinstance(nb, nbformat.NotebookNode)
    assert len(nb.cells) > 0
    
    # Check metadata
    assert "jmd_run" in nb.metadata
    assert nb.metadata["jmd_run"]["run_id"] == "test-run-123"
    assert nb.metadata["jmd_run"]["seed"] == 42
    
    # Check cells exist
    cell_types = [cell.cell_type for cell in nb.cells]
    assert "markdown" in cell_types
    assert "code" in cell_types


def test_generate_notebook_includes_config(sample_config: RunConfig, sample_state: dict) -> None:
    """generate_notebook includes run configuration."""
    nb = generate_notebook(sample_config, sample_state, [])
    
    # Check first markdown cell contains config info
    first_cell = nb.cells[0]
    assert first_cell.cell_type == "markdown"
    assert "test-run-123" in first_cell.source
    assert "target" in first_cell.source
    assert "binary" in first_cell.source
    assert "roc_auc" in first_cell.source


def test_generate_notebook_includes_seed(sample_config: RunConfig, sample_state: dict) -> None:
    """generate_notebook includes seed in setup code."""
    nb = generate_notebook(sample_config, sample_state, [])
    
    # Find code cell with seed setup
    code_cells = [c.source for c in nb.cells if c.cell_type == "code"]
    setup_code = code_cells[0]
    
    assert "SEED = 42" in setup_code
    assert "np.random.seed(SEED)" in setup_code


def test_generate_notebook_includes_dropped_columns(
    sample_config: RunConfig, sample_state: dict
) -> None:
    """generate_notebook includes dropped columns section."""
    nb = generate_notebook(sample_config, sample_state, [])
    
    # Check for dropped columns
    all_source = " ".join(c.source for c in nb.cells)
    assert "id_col" in all_source
    assert "leak_col" in all_source
    assert "dropped_columns" in all_source


def test_generate_notebook_includes_final_code(
    sample_config: RunConfig, sample_state: dict
) -> None:
    """generate_notebook includes accepted feature engineering code."""
    nb = generate_notebook(sample_config, sample_state, [])
    
    # Check for final code
    all_source = " ".join(c.source for c in nb.cells)
    assert "new_feature" in all_source
    assert "df['a'] + df['b']" in all_source


def test_generate_notebook_includes_model_info(
    sample_config: RunConfig, sample_state: dict
) -> None:
    """generate_notebook includes model training and results."""
    nb = generate_notebook(sample_config, sample_state, [])
    
    all_source = " ".join(c.source for c in nb.cells)
    assert "model_001" in all_source
    assert "rf" in all_source
    assert "0.85" in all_source


def test_generate_notebook_without_dropped_columns(sample_config: RunConfig) -> None:
    """generate_notebook works without dropped columns."""
    state = {"chosen": "model_001", "models": {"model_001": {"family": "linear"}}}
    nb = generate_notebook(sample_config, state, [])
    
    assert len(nb.cells) > 0
    # Should not crash, notebook should still be valid


def test_generate_notebook_without_final_code(sample_config: RunConfig) -> None:
    """generate_notebook works without feature engineering code."""
    state = {
        "chosen": "model_001",
        "models": {"model_001": {"family": "hgb"}},
        "dropped": [],
    }
    nb = generate_notebook(sample_config, state, [])
    
    assert len(nb.cells) > 0
    # Should not have feature engineering section if no code


def test_write_notebook_creates_file(sample_config: RunConfig, sample_state: dict) -> None:
    """write_notebook creates a valid .ipynb file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test.ipynb"
        write_notebook(sample_config, sample_state, [], str(output_path))
        
        assert output_path.exists()
        
        # Verify it's valid JSON notebook format
        with open(output_path, "r", encoding="utf-8") as f:
            nb = nbformat.read(f, as_version=4)
        
        assert isinstance(nb, nbformat.NotebookNode)
        assert len(nb.cells) > 0


def test_notebook_metadata_structure(sample_config: RunConfig, sample_state: dict) -> None:
    """Notebook metadata includes all required fields."""
    nb = generate_notebook(sample_config, sample_state, [])
    
    assert "kernelspec" in nb.metadata
    assert nb.metadata["kernelspec"]["name"] == "python3"
    
    assert "language_info" in nb.metadata
    assert nb.metadata["language_info"]["name"] == "python"
    
    jmd = nb.metadata["jmd_run"]
    assert jmd["run_id"] == "test-run-123"
    assert jmd["seed"] == 42
    assert jmd["planner"] == "scripted"
    assert jmd["task_type"] == "binary"
    assert jmd["metric"] == "roc_auc"


def test_notebook_has_data_loading(sample_config: RunConfig, sample_state: dict) -> None:
    """Notebook includes data loading code."""
    nb = generate_notebook(sample_config, sample_state, [])
    
    code_sources = [c.source for c in nb.cells if c.cell_type == "code"]
    data_loading_present = any("read_parquet" in src for src in code_sources)
    
    assert data_loading_present


def test_notebook_has_train_test_split(sample_config: RunConfig, sample_state: dict) -> None:
    """Notebook includes train/test split code."""
    nb = generate_notebook(sample_config, sample_state, [])
    
    code_sources = [c.source for c in nb.cells if c.cell_type == "code"]
    split_present = any("train_test_split" in src for src in code_sources)
    
    assert split_present
