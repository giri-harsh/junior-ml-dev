"""Wiring test for the real benchmark path on a SYNTHETIC task in temp dirs (no real data, no
real ledger): split -> agent run -> predictions -> scorer service -> score."""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.scorer.splits import write_split
from benchmarks import agent_benchmark as ab
from benchmarks import baselines
from benchmarks.fetch import synthetic
from benchmarks.tasks.registry import get_task
from trajectory import emit


@pytest.mark.parametrize("name", ["credit-g", "segment", "cpu_act"])  # binary/multiclass/regression
def test_real_run_one_scores_through_the_scorer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    spec = get_task(name)  # registry spec (the scorer looks tasks up by name); data is synthetic
    target, metric = spec.target, spec.metric
    data_root, scorer_root = tmp_path / "data" / "tasks", tmp_path / "scorer"
    df, _ = synthetic(spec, n=400)
    write_split(df, spec, data_root, scorer_root)
    monkeypatch.setattr(baselines, "DATA_ROOT", data_root)
    monkeypatch.setattr(baselines, "SCORER_ROOT", scorer_root)
    monkeypatch.setenv("DATA_TOOLS_ROOTS", str(tmp_path / "data"))
    monkeypatch.setenv("EXPERIMENTS_DIR", str(tmp_path / "exp"))
    emit.configure(tmp_path / "traj")
    monkeypatch.setattr(ab, "FLAML_BUDGET_S", 0.0)
    out = ab.real_run_one(spec, tmp_path / "work")
    assert out["status"] == "done" and not out["failures"]
    good = (
        float(df[target].std()) if metric == "rmse" else {"roc_auc": 0.7, "f1_macro": 0.4}[metric]
    )
    assert (out["agent"] > good) if metric != "rmse" else (out["agent"] < good)
    assert out["scale"] is None or out["scale"] > 0
    assert (data_root / spec.name / "test_features.parquet").exists()
    labels = list((tmp_path / "data").rglob("*test_labels*"))
    assert labels == []  # labels never copied into the agent-visible tree
