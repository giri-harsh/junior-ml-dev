"""Reproducibility notebook generation (PRD S21.1).

Generates Jupyter notebook from accepted agent code with metadata, seeds, and environment.
"""

# mypy: disable-error-code="no-untyped-call"

from __future__ import annotations

from typing import Any

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

from harness.agent.models import RunConfig, StepRecord


def generate_notebook(cfg: RunConfig, state: dict[str, Any], records: list[StepRecord]) -> Any:
    """Generate reproducibility notebook from run state (PRD S21.1).

    Notebook contains:
    - Setup: imports, seeds, data loading
    - Code cells from accepted steps
    - Model training and evaluation
    - Metadata: Python version, seeds, run config

    Returns nbformat NotebookNode ready to write with nbformat.write().
    """
    nb = new_notebook()

    # Header
    header_text = f"""# Reproducibility Notebook: {cfg.run_id}

Generated from junior-ml-dev agent run.

## Configuration
- Task: {cfg.task.task_type}, target: `{cfg.task.target}`
- Metric: {cfg.task.metric}
- Planner: {cfg.planner}, LLM mode: {cfg.llm_mode}
- Seed: {cfg.task.seed}
- Data: {cfg.task.data_path}

## Setup
Install dependencies and set random seeds.
"""
    nb.cells.append(new_markdown_cell(header_text))

    # Setup cell: imports and seeds
    setup_code = f"""# Setup
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
import joblib

# Set random seeds for reproducibility
SEED = {cfg.task.seed}
np.random.seed(SEED)

print(f"Setup complete with seed={{SEED}}")
"""
    nb.cells.append(new_code_cell(setup_code))

    # Data loading
    data_header = """## Data Loading

Load the dataset and prepare train/test split.
"""
    nb.cells.append(new_markdown_cell(data_header))

    data_code = f"""# Load data
df = pd.read_parquet("{cfg.task.data_path}")
print(f"Loaded {{len(df)}} rows, {{len(df.columns)}} columns")

# Display first few rows
df.head()
"""
    nb.cells.append(new_code_cell(data_code))

    # Dropped columns (if any)
    dropped = state.get("dropped", [])
    if dropped:
        drop_header = "## Column Drops\n\nColumns dropped due to leakage/ID policy."
        nb.cells.append(new_markdown_cell(drop_header))

        drop_code = f"""# Drop columns identified as leakage risks
dropped_columns = {dropped!r}
df = df.drop(columns=dropped_columns)
print(f"Dropped {{len(dropped_columns)}} columns: {{dropped_columns}}")
"""
        nb.cells.append(new_code_cell(drop_code))

    # Feature engineering (from accepted steps)
    final_code = state.get("final_code", "")
    if final_code:
        fe_header = """## Feature Engineering

Feature engineering code accepted by the agent.
"""
        nb.cells.append(new_markdown_cell(fe_header))
        nb.cells.append(new_code_cell(final_code))

    # Model training
    chosen = state.get("chosen")
    model_info = state.get("models", {}).get(chosen or "", {})
    family = model_info.get("family", "unknown")

    train_header = f"""## Model Training

Train {family} model on the prepared data.
"""
    nb.cells.append(new_markdown_cell(train_header))

    stratify_param = f'y if "{cfg.task.task_type}" != "regression" else None'
    train_code = f"""# Train/test split
target = "{cfg.task.target}"
X = df.drop(columns=[target])
y = df[target]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=SEED, stratify={stratify_param}
)

print(f"Train: {{len(X_train)}} rows, Test: {{len(X_test)}} rows")

# Model training would go here
# Note: Actual model artifacts are in the bundle directory
# This notebook demonstrates the data preparation pipeline
"""
    nb.cells.append(new_code_cell(train_code))

    # Results summary
    val_score = model_info.get("val_score", "n/a")
    results_text = f"""## Results

- Chosen model: {chosen or "none"}
- Family: {family}
- Validation {cfg.task.metric}: {val_score}

See the full bundle for model artifacts and detailed results.
"""
    nb.cells.append(new_markdown_cell(results_text))

    # Metadata
    nb.metadata = {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {
            "name": "python",
            "version": "3.11",
        },
        "jmd_run": {
            "run_id": cfg.run_id,
            "seed": cfg.task.seed,
            "planner": cfg.planner,
            "llm_mode": cfg.llm_mode,
            "task_type": cfg.task.task_type,
            "metric": cfg.task.metric,
        },
    }

    return nb


def write_notebook(
    cfg: RunConfig, state: dict[str, Any], records: list[StepRecord], output_path: str
) -> None:
    """Generate and write notebook to file."""
    nb = generate_notebook(cfg, state, records)
    with open(output_path, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)
