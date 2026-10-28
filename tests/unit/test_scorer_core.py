from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from apps.scorer import metrics
from apps.scorer.service import create_app, run_token
from apps.scorer.splits import frame_sha256, make_split, write_split
from benchmarks.fetch import synthetic
from benchmarks.tasks.registry import TaskSpec, get_task, load_registry

ROOT = Path(__file__).resolve().parents[2]


def _spec(name: str) -> TaskSpec:
    return get_task(name)


def test_registry_has_ten_valid_tasks() -> None:
    tasks = load_registry()
    assert len(tasks) == 10
    assert sum(t.imbalanced for t in tasks) >= 2
    assert sum(t.role == "p3_heldout" for t in tasks) >= 2
    assert {t.task_type for t in tasks} == {"binary", "multiclass", "regression"}


def test_registry_rejects_bad_metric() -> None:
    with pytest.raises(ValueError):
        TaskSpec(
            name="x",
            source="openml",
            task_type="regression",
            target="y",
            metric="roc_auc",
            role="dev",
        )


@pytest.mark.parametrize("name", ["credit-g", "segment", "cpu_act"])
def test_split_is_reproducible(name: str) -> None:
    spec = _spec(name)
    df, _ = synthetic(spec)
    a = make_split(df, spec)
    b = make_split(df.copy(), spec)
    assert frame_sha256(a[0]) == frame_sha256(b[0])
    assert frame_sha256(a[1]) == frame_sha256(b[1])
    assert set(a[0]["row_id"]).isdisjoint(a[1]["row_id"])
    assert len(a[0]) + len(a[1]) == len(df)


def test_stratified_split_keeps_class_balance() -> None:
    spec = _spec("churn")
    df, _ = synthetic(spec)
    tr, te = make_split(df, spec)
    assert abs(tr[spec.target].eq("1").mean() - te[spec.target].eq("1").mean()) < 0.02


def test_group_and_time_splits() -> None:
    df = pd.DataFrame(
        {"g": np.repeat(np.arange(50), 4), "t": np.arange(200), "y": np.arange(200) % 2}
    )
    base = _spec("credit-g").model_dump()
    gspec = TaskSpec.model_validate({**base, "target": "y", "group_col": "g"})
    tr, te = make_split(df, gspec)
    assert set(tr["g"]).isdisjoint(te["g"])
    tspec = TaskSpec.model_validate({**base, "target": "y", "time_col": "t"})
    tr, te = make_split(df, tspec)
    assert tr["t"].max() < te["t"].min()


def test_write_split_isolates_labels(tmp_path: Path) -> None:
    spec = _spec("credit-g")
    df, _ = synthetic(spec)
    write_split(df, spec, tmp_path / "agent", tmp_path / "scorer")
    agent_files = {p.name for p in (tmp_path / "agent" / spec.name).iterdir()}
    assert agent_files == {"train.parquet", "manifest.json"}
    feats = pd.read_parquet(tmp_path / "scorer" / spec.name / "test_features.parquet")
    assert spec.target not in feats.columns
    assert (
        "test_labels_sha256" not in (tmp_path / "agent" / spec.name / "manifest.json").read_text()
    )


def test_metrics_match_hand_computed() -> None:
    y = [0, 0, 1, 1]
    assert metrics.roc_auc(y, [0.1, 0.4, 0.35, 0.8]) == 0.75
    assert metrics.rmse([1, 2, 3], [1, 2, 5]) == pytest.approx(np.sqrt(4 / 3))
    assert metrics.mae([1, 2, 3], [1, 2, 5]) == pytest.approx(2 / 3)
    assert metrics.f1_macro(["a", "a", "b", "b"], ["a", "b", "b", "b"]) == pytest.approx(
        (2 / 3 + 0.8) / 2
    )
    assert metrics.pr_auc([0, 1], [0.2, 0.9]) == 1.0
    assert metrics.HIGHER_IS_BETTER["rmse"] is False and metrics.HIGHER_IS_BETTER["roc_auc"]


def _client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> tuple[TestClient, TaskSpec, pd.DataFrame]:
    monkeypatch.setenv("SCORER_SECRET", "unit-test-secret")
    spec = _spec(name)
    df, _ = synthetic(spec)
    write_split(df, spec, tmp_path / "agent", tmp_path / "scorer")
    labels = pd.read_parquet(tmp_path / "scorer" / name / "test_labels.parquet")
    return TestClient(create_app(tmp_path / "scorer")), spec, labels


def _post(c: TestClient, name: str, preds: pd.DataFrame, token: str | None = None) -> object:
    buf = io.BytesIO(preds.to_csv(index=False).encode())
    headers = {"Authorization": f"Bearer {token or run_token('unit-test-secret', 'r1')}"}
    return c.post(
        "/v1/score-predictions",
        data={"task": name, "run_id": "r1"},
        files={"predictions": ("p.csv", buf)},
        headers=headers,
    )


def test_perfect_and_dummy_scores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c, spec, labels = _client(tmp_path, monkeypatch, "cpu_act")
    perfect = pd.DataFrame({"row_id": labels.row_id, "pred": labels[spec.target]})
    r = _post(c, spec.name, perfect)
    assert r.status_code == 200 and r.json()["score"] == 0.0  # type: ignore[attr-defined]
    dummy = pd.DataFrame({"row_id": labels.row_id, "pred": labels[spec.target].mean()})
    assert _post(c, spec.name, dummy).json()["score"] > 0  # type: ignore[attr-defined]


def test_binary_auc_perfect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c, spec, labels = _client(tmp_path, monkeypatch, "credit-g")
    pos = sorted(labels[spec.target].unique())[-1]
    perfect = pd.DataFrame(
        {"row_id": labels.row_id, "pred": (labels[spec.target] == pos).astype(float)}
    )
    assert _post(c, spec.name, perfect).json()["score"] == 1.0  # type: ignore[attr-defined]


def test_scorer_rejects_bad_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c, spec, labels = _client(tmp_path, monkeypatch, "cpu_act")
    good = pd.DataFrame({"row_id": labels.row_id, "pred": 1.0})
    assert _post(c, spec.name, good, token="wrong").status_code == 401  # type: ignore[attr-defined]
    assert _post(c, spec.name, good.iloc[:-1]).status_code == 422  # type: ignore[attr-defined]
    bad = good.copy()
    bad.loc[0, "pred"] = float("nan")
    assert _post(c, spec.name, bad).status_code == 422  # type: ignore[attr-defined]


def test_labels_not_in_worker_mount() -> None:
    """Security: only the scorer service may mount the scorer_data volume."""
    compose = yaml.safe_load((ROOT / "deploy/compose/docker-compose.yml").read_text())
    for name, svc in compose["services"].items():
        mounts = [v for v in svc.get("volumes", []) if "scorer_data" in str(v)]
        if name != "scorer":
            assert not mounts, f"{name} must not mount scorer_data"
    assert any("scorer_data" in str(v) for v in compose["services"]["scorer"]["volumes"])
