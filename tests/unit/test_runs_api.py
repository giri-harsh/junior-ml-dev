from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import datasets, runs
from apps.api.store import LocalObjectStore
from harness.security import auth
from tests.unit.test_agent_runner import make_csv


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    data = tmp_path / "data"
    data.mkdir()
    for k, v in {
        "ADMIN_USER": "root", "ADMIN_PASSWORD_HASH": auth.hash_password("pw-for-tests"),
        "JWT_SECRET": "jwt-test", "APPROVAL_SECRET": "appr-test",
        "AUDIT_DB": str(tmp_path / "audit.db"), "APPROVAL_DB": str(tmp_path / "appr.db"),
        "RUNS_DB": str(tmp_path / "runs.db"), "JOBS_DB": str(tmp_path / "jobs.db"),
        "RUN_ROOT": str(tmp_path / "runs"), "RUN_INPUT_DIR": str(data / "run_inputs"),
        "DATA_TOOLS_ROOTS": str(data), "EXPERIMENTS_DIR": str(tmp_path / "exp"),
        "TRAJECTORY_DIR": str(tmp_path / "traj"),
    }.items():  # fmt: skip
        monkeypatch.setenv(k, v)
    datasets.set_store(LocalObjectStore(tmp_path / "store"))
    assert runs.run_store().path == str(tmp_path / "runs.db")  # env binding took effect
    yield TestClient(app)
    datasets.set_store(None)


def _login(c: TestClient) -> None:
    r = c.post("/v1/auth/login", json={"user": "root", "password": "pw-for-tests"})
    assert r.status_code == 200


def test_endpoints_require_admin(api: TestClient) -> None:
    body = {"dataset_id": "0" * 16, "target": "y", "task_type": "binary", "metric": "roc_auc"}
    assert api.post("/v1/runs", json=body).status_code == 401
    assert api.get("/v1/runs/x").status_code == 401
    assert api.get("/v1/runs/x/report").status_code == 401


def test_submit_work_status_report_metrics(api: TestClient, tmp_path: Path) -> None:
    _login(api)
    csv = make_csv(tmp_path)
    up = api.post("/v1/datasets", files={"file": ("d.csv", csv.read_bytes())})
    did = up.json()["dataset_id"]
    body = {
        "dataset_id": did, "target": "y", "task_type": "binary", "metric": "roc_auc",
        "budget": {"flaml_budget_s": 0, "tune_trials": 0},
    }  # fmt: skip
    sub = api.post("/v1/runs", json=body)
    assert sub.status_code == 202
    rid = sub.json()["run_id"]
    assert api.get(f"/v1/runs/{rid}").status_code == 404  # queued, not started
    assert runs.work_once() is True and runs.work_once() is False
    got = api.get(f"/v1/runs/{rid}").json()
    assert got["status"] == "done" and got["result"]["val_score"] > 0.75
    rep = api.get(f"/v1/runs/{rid}/report")
    assert rep.status_code == 200 and "planner=scripted" in rep.text
    m = api.get("/metrics").text
    assert 'jmd_runs{status="done"} 1' in m and 'jmd_steps_total{tool="train_model"}' in m
    assert rid not in m  # aggregates only
    assert api.get("/v1/audit").json()[-1]["action"] in {"run_submitted", "tool_call"}
    assert api.get("/v1/audit/verify").json()["ok"] is True


def test_submit_rejects_bad_input(api: TestClient) -> None:
    _login(api)
    bad = {"dataset_id": "../../etc", "target": "y", "task_type": "binary", "metric": "roc_auc"}
    assert api.post("/v1/runs", json=bad).status_code == 422
    extra = {"dataset_id": "0" * 16, "target": "y", "task_type": "binary", "metric": "roc_auc"}
    assert api.post("/v1/runs", json={**extra, "path": "/etc/passwd"}).status_code == 422
    assert api.post("/v1/runs", json=extra).status_code in {404, 409}  # unknown dataset
