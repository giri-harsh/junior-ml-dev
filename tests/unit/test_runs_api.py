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


def test_ui_page_is_served(api: TestClient) -> None:
    r = api.get("/ui")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "Scripted planner (no LLM)" in r.text and "<script>" in r.text


def test_deploy_approval_flow_through_the_api(
    api: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEPLOY_DIR", str(tmp_path / "deploy"))
    _login(api)
    did = api.post("/v1/datasets", files={"file": ("d.csv", make_csv(tmp_path).read_bytes())})
    did = did.json()["dataset_id"]
    body = {
        "dataset_id": did, "target": "y", "task_type": "binary", "metric": "roc_auc",
        "deploy": True, "budget": {"flaml_budget_s": 0, "tune_trials": 0},
    }  # fmt: skip
    rid = api.post("/v1/runs", json=body).json()["run_id"]
    assert runs.work_once()
    got = api.get(f"/v1/runs/{rid}").json()
    assert got["status"] == "awaiting_approval"
    aid = got["result"]["pending_approval"]["approval_id"]
    assert api.post(f"/v1/runs/{rid}/resume", json={"approval_token": "x" * 20}).status_code == 202
    assert runs.work_once()  # a wrong token: deploy step fails safely, run still completes
    assert api.get(f"/v1/runs/{rid}").json()["status"] in {"done", "budget_exhausted"}
    assert api.post(f"/v1/runs/{rid}/resume", json={"approval_token": "y" * 20}).status_code == 409
    assert api.post(f"/v1/approvals/{aid}/approve").status_code == 200  # token exists, but unused


def test_run_submission_is_rate_limited(
    api: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harness.security.ratelimit import RateLimiter

    monkeypatch.setattr(runs, "limiter", RateLimiter(2, 60.0))
    _login(api)
    did = api.post("/v1/datasets", files={"file": ("d.csv", make_csv(tmp_path).read_bytes())})
    did = did.json()["dataset_id"]
    body = {"dataset_id": did, "target": "y", "task_type": "binary", "metric": "roc_auc",
            "budget": {"flaml_budget_s": 0, "tune_trials": 0}}  # fmt: skip
    codes = [api.post("/v1/runs", json=body).status_code for _ in range(3)]
    assert codes == [202, 202, 429]
    r = api.post("/v1/runs", json=body)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1


def test_audit_log_covers_every_tool_call_and_the_whole_approval_lifecycle(
    api: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEPLOY_DIR", str(tmp_path / "deploy"))
    _login(api)
    did = api.post("/v1/datasets", files={"file": ("d.csv", make_csv(tmp_path).read_bytes())})
    did = did.json()["dataset_id"]
    body = {"dataset_id": did, "target": "y", "task_type": "binary", "metric": "roc_auc",
            "deploy": True, "budget": {"flaml_budget_s": 0, "tune_trials": 0}}  # fmt: skip
    rid = api.post("/v1/runs", json=body).json()["run_id"]
    assert runs.work_once()
    aid = api.get(f"/v1/runs/{rid}").json()["result"]["pending_approval"]["approval_id"]
    token = api.post(f"/v1/approvals/{aid}/approve").json()["token"]
    assert api.post(f"/v1/runs/{rid}/resume", json={"approval_token": token}).status_code == 202
    assert runs.work_once()
    res = api.get(f"/v1/runs/{rid}").json()
    assert res["status"] in {"done", "budget_exhausted"}
    entries = api.get("/v1/audit").json()
    actions = [e["action"] for e in entries]
    for needed in ("login", "run_submitted", "approval_requested", "approval_granted",
                   "approval_consumed", "run_resumed"):  # fmt: skip
        assert needed in actions, needed
    n_steps = len(runs.run_store().checkpoints(rid))
    assert actions.count("tool_call") == n_steps  # one audit row per executed step
    assert api.get("/v1/audit/verify").json()["ok"] is True
    # a replay of the spent token is refused and the refusal is recorded too
    assert api.post(f"/v1/runs/{rid}/resume", json={"approval_token": token}).status_code == 409
