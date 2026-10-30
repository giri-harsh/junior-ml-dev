"""Run budgets, one-at-a-time execution, per-IP limits, history cap and cleanup."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.demo.config import MAX_FLAML_S, MAX_WALL_S, DemoSettings
from apps.api.demo.service import DemoJob, DemoService, ExecOutcome, subprocess_executor
from tests.demo.helpers import FakeExecutor, make_settings, wait_until


def xff(ip: str) -> dict[str, str]:
    return {"x-forwarded-for": ip}


def post_run(c: TestClient, ip: str, sample: str = "diabetes") -> int:
    return c.post("/demo/api/runs", json={"sample": sample}, headers=xff(ip)).status_code


# --- budgets -------------------------------------------------------------------------------------
def test_budgets_are_fixed_server_side_and_clamped(
    app_service: tuple[FastAPI, DemoService], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, service = app_service
    from apps.api.demo.samples import BY_KEY, sample_path

    cfg = service.build_config(
        "demo-abc", BY_KEY["diabetes"], sample_path(service.s.data_dir, "diabetes")
    )
    assert cfg.budget.max_wall_s <= 90 and cfg.budget.flaml_budget_s <= 20
    assert cfg.planner == "scripted" and cfg.llm_mode == "none"
    assert not cfg.deploy and not cfg.sandbox_features and cfg.budget.max_tokens == 0
    # env overrides may lower the ceilings, never raise them
    monkeypatch.setenv("DEMO_MAX_WALL_S", "5000")
    monkeypatch.setenv("DEMO_FLAML_S", "500")
    monkeypatch.setenv("DEMO_SOFT_WALL_S", "4000")
    s = DemoSettings.from_env()
    assert s.max_wall_s == MAX_WALL_S == 90.0 and s.flaml_s == MAX_FLAML_S == 20.0
    assert s.soft_wall_s <= s.max_wall_s
    monkeypatch.setenv("DEMO_MAX_WALL_S", "30")
    assert DemoSettings.from_env().max_wall_s == 30.0
    # nothing in the request can change a budget
    assert service.s.max_wall_s <= 90


def test_the_hard_wall_clock_kills_a_run_that_does_not_finish(
    app_service: tuple[FastAPI, DemoService], tmp_path: Path
) -> None:
    _, service = app_service
    from apps.api.demo.samples import BY_KEY, sample_path

    cfg = service.build_config(
        "demo-timeout1", BY_KEY["credit-g"], sample_path(service.s.data_dir, "credit-g")
    )
    cfg = cfg.model_copy(update={"budget": cfg.budget.model_copy(update={"max_wall_s": 2.0})})
    job = DemoJob("demo-timeout1", tmp_path / "run", cfg, 3.0, 15.0, service.s.data_dir)
    t0 = time.time()
    out = subprocess_executor(job)  # the real child process; 3 s is far too short for a full run
    assert out.status == "timeout" and "wall limit" in out.error, out.error
    assert time.time() - t0 < 25


def test_a_real_run_end_to_end_with_the_scripted_planner(
    app_service: tuple[FastAPI, DemoService], tmp_path: Path
) -> None:
    _, service = app_service
    service.executor = subprocess_executor
    service.s = make_settings(tmp_path, flaml_s=0.0, data_dir=service.s.data_dir)
    run_id = service.submit("diabetes", "1.1.1.1")
    assert service.work_once()
    st = service.public_status(run_id)
    assert st is not None and st["status"] == "done", st
    assert st["summary"]["review"] in {"APPROVE", "REQUEST_CHANGES"}
    assert st["summary"]["val_score"] and st["summary"]["has_report"]
    report = service.report_path(run_id)
    assert report is not None and "planner=scripted" in report.read_text(encoding="utf-8")


# --- one at a time -------------------------------------------------------------------------------
def test_only_one_run_executes_at_a_time_and_the_rest_wait_in_a_queue(
    client: TestClient, app_service: tuple[FastAPI, DemoService], executor: FakeExecutor
) -> None:
    _, service = app_service
    executor.delay = 0.25
    ids = []
    for i in range(4):  # 1 running + 3 waiting is the maximum
        r = client.post("/demo/api/runs", json={"sample": "diabetes"}, headers=xff(f"10.0.0.{i}"))
        assert r.status_code == 202, r.text
        ids.append(r.json()["run_id"])
    assert post_run(client, "10.0.0.99") == 429  # queue full
    service.start()
    try:
        assert wait_until(lambda: executor.calls, 5)
        mid = [client.get(f"/demo/api/runs/{i}").json() for i in ids]
        assert sum(m["status"] == "running" for m in mid) <= 1
        assert any(m["status"] == "queued" and m["queue_position"] >= 2 for m in mid)
        assert wait_until(
            lambda: all(client.get(f"/demo/api/runs/{i}").json()["status"] == "done" for i in ids),
            20,
        )
    finally:
        service.stop()
    assert executor.peak == 1 and len(executor.calls) == 4
    assert executor.calls == ids  # FIFO


def test_one_active_run_per_address(client: TestClient) -> None:
    assert post_run(client, "9.9.9.9") == 202
    r = client.post("/demo/api/runs", json={"sample": "diabetes"}, headers=xff("9.9.9.9"))
    assert r.status_code == 409 and "Retry-After" in r.headers
    assert post_run(client, "8.8.8.8") == 202  # someone else is fine


def test_unknown_sample_and_unknown_run(client: TestClient) -> None:
    assert post_run(client, "1.2.3.4", "no-such-sample") == 404
    assert client.get("/demo/api/runs/demo-0123456789").status_code == 404
    assert client.get("/demo/api/runs/../../etc/passwd").status_code == 404
    assert client.get("/demo/api/runs/demo-0123456789/report").status_code == 404


def test_a_tampered_sample_file_is_refused(
    client: TestClient, app_service: tuple[FastAPI, DemoService]
) -> None:
    _, service = app_service
    (service.s.data_dir / "diabetes.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    assert post_run(client, "5.5.5.5", "diabetes") == 404


# --- rate limits ---------------------------------------------------------------------------------
def test_per_ip_rate_limit_and_the_forwarded_header_is_not_trusted_blindly(
    demo_env: Path, tmp_path: Path, executor: FakeExecutor
) -> None:
    from apps.api.demo import install
    from tests.demo.helpers import fresh_app

    now = [0.0]
    app = fresh_app()
    s = make_settings(tmp_path, ip_runs_per_window=2, ip_window_s=600.0, queue_max=50, proxy_hops=1)
    service = install(app, s, executor)
    assert service is not None
    service.ip_limiter.clock = lambda: now[0]
    c = TestClient(app)
    codes = []
    for _ in range(3):
        codes.append(post_run(c, "7.7.7.7"))
        service.work_once()  # finish it so only the window limit applies
    assert codes == [202, 202, 429]
    r = c.post("/demo/api/runs", json={"sample": "diabetes"}, headers=xff("7.7.7.7"))
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    # a client cannot dodge the limit by prepending addresses: the trusted entry is the last one
    spoof = {"x-forwarded-for": "1.1.1.1, 7.7.7.7"}
    assert c.post("/demo/api/runs", json={"sample": "diabetes"}, headers=spoof).status_code == 429
    assert post_run(c, "6.6.6.6") == 202
    now[0] += 601  # the window passes
    service.work_once()
    assert post_run(c, "7.7.7.7") == 202


def test_global_hourly_cap(demo_env: Path, tmp_path: Path, executor: FakeExecutor) -> None:
    from apps.api.demo import install
    from tests.demo.helpers import fresh_app

    app = fresh_app()
    service = install(app, make_settings(tmp_path, global_runs_per_hour=2, queue_max=50), executor)
    assert service is not None
    c = TestClient(app)
    assert [post_run(c, f"3.3.3.{i}") for i in range(3)] == [202, 202, 429]


# --- history cap and cleanup ---------------------------------------------------------------------
def test_history_is_capped_and_old_run_directories_are_deleted(
    demo_env: Path, tmp_path: Path, executor: FakeExecutor
) -> None:
    from apps.api.demo import install
    from tests.demo.helpers import fresh_app

    app = fresh_app()
    service = install(app, make_settings(tmp_path, history_cap=3, queue_max=50), executor)
    assert service is not None
    c = TestClient(app)
    ids = []
    for i in range(7):
        r = c.post("/demo/api/runs", json={"sample": "diabetes"}, headers=xff(f"4.4.4.{i}"))
        ids.append(r.json()["run_id"])
        assert service.work_once()
    rows = service.admin_list()
    assert len(rows) == 3 and [r["run_id"] for r in rows] == ids[:-4:-1]
    dirs = {d.name for d in service.runs_dir.iterdir()}
    assert dirs == set(ids[-3:])
    assert c.get(f"/demo/api/runs/{ids[0]}").status_code == 404  # evicted
    assert c.get(f"/demo/api/runs/{ids[-1]}/report").status_code == 200


def test_ttl_cleanup_orphans_and_active_runs(
    demo_env: Path, tmp_path: Path, executor: FakeExecutor
) -> None:
    from apps.api.demo import install
    from tests.demo.helpers import fresh_app

    app = fresh_app()
    service = install(app, make_settings(tmp_path, history_ttl_s=100.0, queue_max=50), executor)
    assert service is not None
    c = TestClient(app)
    clock = [1_000_000.0]
    service.clock = lambda: clock[0]
    old = c.post("/demo/api/runs", json={"sample": "diabetes"}, headers=xff("2.2.2.1")).json()[
        "run_id"
    ]
    service.work_once()
    clock[0] += 500
    queued = c.post("/demo/api/runs", json={"sample": "diabetes"}, headers=xff("2.2.2.2")).json()[
        "run_id"
    ]
    (service.runs_dir / "orphan-dir").mkdir()
    assert service.cleanup() == 1
    assert not (service.runs_dir / old).exists() and not (service.runs_dir / "orphan-dir").exists()
    assert service.public_status(queued)["status"] == "queued"  # type: ignore[index]


def test_runs_left_active_by_a_dead_process_are_marked_interrupted(
    demo_env: Path, tmp_path: Path, executor: FakeExecutor
) -> None:
    s = make_settings(tmp_path)
    first = DemoService(s, executor)
    run_id = first.submit("diabetes", "1.1.1.1")
    second = DemoService(s, executor)  # a restart
    st = second.public_status(run_id)
    assert st is not None and st["status"] == "interrupted" and "restarted" in st["message"]
    assert second.work_once() is False  # the old queue is not resumed


def test_a_failing_executor_does_not_wedge_the_queue(demo_env: Path, tmp_path: Path) -> None:
    def boom(job: DemoJob) -> ExecOutcome:
        raise RuntimeError("kaboom")

    s = make_settings(tmp_path)
    svc = DemoService(s, boom)
    a = svc.submit("diabetes", "1.1.1.1")
    b = svc.submit("diabetes", "2.2.2.2")
    assert svc.work_once() and svc.work_once()
    assert svc.public_status(a)["status"] == "failed"  # type: ignore[index]
    assert svc.public_status(b)["status"] == "failed"  # type: ignore[index]
    assert svc.submit("diabetes", "1.1.1.1")  # the address is free again
