"""Demo-mode lockdown: uploads, deploy, admin auth, sandbox / code execution."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.demo import install
from apps.api.demo.config import BLOCKED_TOOLS
from apps.api.demo.runner import DemoAgentRunner, enforce_demo_config
from apps.api.demo.service import DemoService, child_env
from harness.agent.models import RunBudget, RunConfig, RunTask, Step
from harness.agent.planners import ScriptedPlanner
from harness.agent.runner import AgentRunner, new_state
from harness.agent.store import RunStore
from tests.demo.conftest import ADMIN_PW
from tests.demo.helpers import fresh_app

REPO = Path(__file__).resolve().parents[2]


def route_paths(app: FastAPI) -> list[str]:
    """Every (METHODS path) the app can route to, including lazily included routers."""
    out: list[str] = []

    def walk(routes: list[Any]) -> None:
        for r in routes:
            inner = getattr(r, "original_router", None)
            if inner is not None:
                walk(list(inner.routes))
            else:
                out.append(getattr(r, "path", ""))

    walk(list(app.router.routes))
    return out


def test_install_is_a_noop_without_demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_MODE", raising=False)
    app = fresh_app()
    before = route_paths(app)
    assert install(app) is None
    assert route_paths(app) == before and "/v1/datasets" in before
    monkeypatch.setenv("DEMO_MODE", "0")
    assert install(app) is None


def test_entrypoint_refuses_to_start_without_demo_mode() -> None:
    env = {**os.environ, "DEMO_MODE": "0", "PYTHONPATH": str(REPO), "PYTHONUTF8": "1"}
    res = subprocess.run(
        [sys.executable, "-c", "import apps.api.demo.app"],
        capture_output=True, text=True, env=env, cwd=REPO, timeout=120,
    )  # fmt: skip
    assert res.returncode != 0 and "requires DEMO_MODE=1" in res.stderr


def test_upload_is_rejected_and_nothing_is_stored(
    client: TestClient, app_service: tuple[FastAPI, DemoService], tmp_path: Path
) -> None:
    app, _ = app_service
    for url in ("/v1/datasets", "/demo/api/runs", "/v1/datasets/0123456789abcdef/status"):
        r = client.post(url, files={"file": ("d.csv", b"a,b\n1,2\n")})
        assert r.status_code == 403, url
    assert not (tmp_path / "store").exists()  # the object store was never touched
    assert not any(p.startswith("/v1/datasets") for p in route_paths(app))
    assert any("/v1/datasets" in x for x in app.state.demo_removed_routes)


def test_deploy_endpoint_is_absent_and_cannot_be_requested(
    client: TestClient, app_service: tuple[FastAPI, DemoService]
) -> None:
    app, _ = app_service
    assert not any("deploy" in p.lower() for p in route_paths(app))
    for method, url in (
        ("get", "/v1/deploy"),
        ("post", "/v1/deploy"),
        ("post", "/v1/runs/x/deploy"),
    ):
        assert getattr(client, method)(url).status_code == 404, url
    # the run request has no deploy field: it is a pydantic model with extra=forbid
    r = client.post("/demo/api/runs", json={"sample": "diabetes", "deploy": True})
    assert r.status_code == 422
    # the regular submission and resume routes are gone, even for a logged-in admin
    assert (
        client.post("/v1/auth/login", json={"user": "admin", "password": ADMIN_PW}).status_code
        == 200
    )
    body = {"dataset_id": "0" * 16, "target": "y", "task_type": "binary", "metric": "roc_auc"}
    assert client.post("/v1/runs", json=body).status_code == 403
    assert (
        client.post("/v1/runs/run-1/resume", json={"approval_token": "x" * 12}).status_code == 403
    )


def test_admin_endpoints_need_the_admin_login(client: TestClient) -> None:
    assert client.get("/demo/api/admin/runs").status_code == 401
    for method, url in (
        ("get", "/v1/audit"), ("get", "/v1/audit/verify"), ("get", "/v1/runs"),
        ("get", "/v1/jobs/dead"), ("post", "/v1/approvals/abc/approve"),
    ):  # fmt: skip
        assert getattr(client, method)(url).status_code == 401, url
    bad = client.post("/v1/auth/login", json={"user": "admin", "password": "wrong"})
    assert bad.status_code == 401
    ok = client.post("/v1/auth/login", json={"user": "admin", "password": ADMIN_PW})
    assert ok.status_code == 200
    assert "secure" in ok.headers["set-cookie"].lower()
    assert client.get("/demo/api/admin/runs").status_code == 200
    assert "DEMO_ADMIN_PASSWORD" not in os.environ  # consumed, not left lying around


def test_admin_login_attempts_are_rate_limited(client: TestClient) -> None:
    codes = [
        client.post("/v1/auth/login", json={"user": "admin", "password": "x"}).status_code
        for _ in range(14)
    ]
    assert codes[:10] == [401] * 10 and 429 in codes[10:]


def test_sandbox_and_code_tools_do_not_exist_in_the_demo_runner(tmp_path: Path) -> None:
    runner = DemoAgentRunner(RunStore(tmp_path / "a.db"), ScriptedPlanner(), run_root=tmp_path)
    assert {
        "engineer_features",
        "check_code_policy",
        "package_model",
        "deploy_local",
    } == BLOCKED_TOOLS
    assert not (BLOCKED_TOOLS & set(runner.tools))
    assert set(AgentRunner(RunStore(tmp_path / "b.db"), ScriptedPlanner()).tools) >= BLOCKED_TOOLS
    cfg = RunConfig(
        run_id="r1",
        task=RunTask(name="t", data_path=str(tmp_path / "d.csv"), target="y",
                     task_type="binary", metric="roc_auc"),
    )  # fmt: skip
    for tool in sorted(BLOCKED_TOOLS):
        rec = runner._execute(
            cfg, Step(tool=tool, args={"code": "import os; os.system('id')"}), 0, new_state(), []
        )
        assert not rec.ok and rec.result == {}, tool
        assert rec.error in {"unknown_tool", "blocked:approval_required"}, tool


def test_config_with_sandbox_deploy_or_an_llm_planner_is_refused(tmp_path: Path) -> None:
    task = RunTask(name="t", data_path="x.csv", target="y", task_type="binary", metric="roc_auc")
    budget = RunBudget(max_wall_s=55, max_tokens=0, flaml_budget_s=10)
    ok = RunConfig(run_id="r1", task=task, budget=budget)
    assert enforce_demo_config(ok, max_wall_s=90, flaml_s=20) is ok
    for bad in (
        RunConfig(run_id="r1", task=task, budget=budget, sandbox_features=True),
        RunConfig(run_id="r1", task=task, budget=budget, deploy=True),
        RunConfig(run_id="r1", task=task, budget=budget, planner="llm", llm_mode="mocked"),
    ):
        with pytest.raises(ValueError):
            enforce_demo_config(bad, max_wall_s=90, flaml_s=20)


def test_install_removes_sandbox_settings_and_child_env_has_no_secrets(
    app_service: tuple[FastAPI, DemoService], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, service = app_service
    assert "JMD_SANDBOX" not in os.environ
    monkeypatch.setenv("GROQ_API_KEY", "x-groq-not-a-real-key")
    monkeypatch.setenv("E2B_API_KEY", "x-e2b-not-a-real-key")
    from apps.api.demo.service import DemoJob

    job = DemoJob("demo-1", tmp_path / "r", None, 90, 15, service.s.data_dir)  # type: ignore[arg-type]
    env = child_env(job)
    assert env["DEMO_MODE"] == "1"
    for name in ("JWT_SECRET", "APPROVAL_SECRET", "GROQ_API_KEY", "E2B_API_KEY",
                 "ADMIN_PASSWORD_HASH", "HF_TOKEN", "JMD_SANDBOX"):  # fmt: skip
        assert name not in env, name


def test_oversized_bodies_and_unexpected_fields_are_refused(client: TestClient) -> None:
    assert client.post("/demo/api/runs", content=b"x" * 20_000,
                       headers={"content-type": "application/json"}).status_code == 413  # fmt: skip
    assert client.post("/demo/api/runs", json={"sample": "../../etc/passwd"}).status_code == 422
    assert client.post("/demo/api/runs", json={"sample": "diabetes", "budget": {"max_wall_s": 9999}}
                       ).status_code == 422  # fmt: skip
