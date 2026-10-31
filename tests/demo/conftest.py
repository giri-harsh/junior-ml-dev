from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.demo import install
from apps.api.demo.service import DemoService
from tests.demo.helpers import FakeExecutor, fresh_app, make_samples, make_settings

ADMIN_PW = "demo-admin-pw-for-tests"


@pytest.fixture
def demo_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """DEMO_MODE=1 plus every variable install() may touch, restored after the test."""
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("JWT_SECRET", "jwt-secret-for-demo-tests-0123456789")
    monkeypatch.setenv("APPROVAL_SECRET", "approval-secret-for-demo-tests")
    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", ADMIN_PW)
    for name in ("ADMIN_PASSWORD_HASH", "ADMIN_USER", "COOKIE_SECURE"):
        monkeypatch.setenv(name, "")  # recorded so teardown restores the original state
        monkeypatch.delenv(name)
    monkeypatch.setenv("JMD_SANDBOX", "docker")  # must be removed by install()
    monkeypatch.setenv("AUDIT_DB", str(tmp_path / "audit.db"))
    monkeypatch.setenv("APPROVAL_DB", str(tmp_path / "appr.db"))
    monkeypatch.setenv("DATA_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("RUNS_DB", str(tmp_path / "runs.db"))
    monkeypatch.setenv("JOBS_DB", str(tmp_path / "jobs.db"))
    return make_samples(tmp_path)


@pytest.fixture
def executor() -> FakeExecutor:
    return FakeExecutor()


@pytest.fixture
def app_service(
    demo_env: Path, tmp_path: Path, executor: FakeExecutor
) -> tuple[FastAPI, DemoService]:
    app = fresh_app()
    service = install(app, make_settings(tmp_path), executor)
    assert service is not None
    return app, service


@pytest.fixture
def client(app_service: tuple[FastAPI, DemoService]) -> Iterator[TestClient]:
    # https so the Secure admin cookie is sent back; no lifespan, tests drive the worker
    yield TestClient(app_service[0], base_url="https://testserver")
