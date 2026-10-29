"""Idempotency keys, graceful worker shutdown, dead letters."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.routes import runs
from harness.queue import SQLiteJobQueue, Worker
from harness.security.idempotency import IdempotencyStore, body_hash
from tests.unit.test_agent_runner import make_csv
from tests.unit.test_runs_api import _login, api  # noqa: F401


def test_idempotency_store_lifecycle(tmp_path: Path) -> None:
    s = IdempotencyStore(tmp_path / "i.db")
    h = body_hash({"a": 1})
    assert s.begin("k", h) == ("new", None)
    assert s.begin("k", h) == ("in_progress", None)  # reserved, not finished
    s.finish("k", {"run_id": "r1"})
    assert s.begin("k", h) == ("replay", {"run_id": "r1"})
    assert s.begin("k", body_hash({"a": 2}))[0] == "conflict"
    s.begin("k2", h)
    s.abandon("k2")  # failed work frees the key
    assert s.begin("k2", h)[0] == "new"
    assert body_hash({"b": 1, "a": 2}) == body_hash({"a": 2, "b": 1})  # key order is irrelevant


def test_api_retry_with_same_key_returns_the_same_run(
    api: TestClient,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    monkeypatch.setenv("IDEMPOTENCY_DB", str(tmp_path / "idem.db"))
    _login(api)
    did = api.post("/v1/datasets", files={"file": ("d.csv", make_csv(tmp_path).read_bytes())})
    did = did.json()["dataset_id"]
    body = {"dataset_id": did, "target": "y", "task_type": "binary", "metric": "roc_auc",
            "budget": {"flaml_budget_s": 0, "tune_trials": 0}}  # fmt: skip
    h = {"Idempotency-Key": "retry-1"}
    first = api.post("/v1/runs", json=body, headers=h)
    again = api.post("/v1/runs", json=body, headers=h)
    assert first.status_code == again.status_code == 202
    assert (
        again.json()["run_id"] == first.json()["run_id"]
        and again.json()["idempotent_replay"] == "true"
    )
    assert len(runs.run_store().list_runs()) == 0  # nothing executed yet; exactly one job queued
    other = api.post("/v1/runs", json={**body, "metric": "pr_auc"}, headers=h)
    assert other.status_code == 422  # same key, different body
    fresh = api.post("/v1/runs", json=body, headers={"Idempotency-Key": "retry-2"})
    assert fresh.json()["run_id"] != first.json()["run_id"]
    assert api.post("/v1/runs", json=body, headers={"Idempotency-Key": "x" * 80}).status_code == 422


def test_worker_stops_claiming_after_sigterm_but_finishes_the_job_in_hand(tmp_path: Path) -> None:
    q = SQLiteJobQueue(tmp_path / "q.db")
    for i in range(3):
        q.enqueue(f"r{i}", {"i": i})
    started, release = threading.Event(), threading.Event()
    done: list[int] = []

    def handler(p: dict[str, Any]) -> dict[str, Any]:
        started.set()
        release.wait(5)
        done.append(p["i"])
        return {}

    w = Worker(q, handler)
    result: list[int] = []
    t = threading.Thread(target=lambda: result.append(w.run_forever(poll_s=0.05, grace_s=5)))
    t.start()
    assert started.wait(5)
    w.request_stop()  # SIGTERM arrives while job 0 is running
    release.set()
    t.join(10)
    assert not t.is_alive() and done == [0] and result == [1]  # drained job 0, claimed no other
    assert sum(1 for _ in q.dead_letters()) == 0


def test_stuck_job_does_not_block_shutdown_and_is_redelivered(tmp_path: Path) -> None:
    class Clock:
        t = 1000.0

        def __call__(self) -> float:
            return self.t

    clock = Clock()
    q = SQLiteJobQueue(tmp_path / "q.db", clock=clock)
    jid = q.enqueue("r", {})
    block = threading.Event()
    w = Worker(q, lambda p: block.wait(30) or {}, lease_s=60)
    out: list[int] = []
    t = threading.Thread(target=lambda: out.append(w.run_forever(poll_s=0.05, grace_s=0.3)))
    t.start()
    time.sleep(0.3)
    w.request_stop()
    t.join(5)
    assert not t.is_alive()  # gave up on the stuck job after the grace period
    clock.t += 61  # lease expires; another worker takes the same job (checkpoints make it a resume)
    again = q.claim("w2", lease_s=60)
    assert again is not None and again.id == jid and again.attempts == 2
    block.set()


def test_dead_letters_can_be_listed_and_requeued(tmp_path: Path) -> None:
    q = SQLiteJobQueue(tmp_path / "q.db", max_attempts=1)
    jid = q.enqueue("r", {})
    Worker(q, lambda p: (_ for _ in ()).throw(RuntimeError("boom"))).run_until_empty()
    (dead,) = q.dead_letters()
    assert dead["id"] == jid and "boom" in dead["error"]
    assert q.requeue_dead(jid) and not q.requeue_dead(jid)
    assert q.dead_letters() == [] and q.status(jid)["status"] == "queued"


def test_dead_letter_api_requires_admin_and_lists_jobs(
    api: TestClient,  # noqa: F811
    tmp_path: Path,  # noqa: F811
) -> None:
    assert api.get("/v1/jobs/dead").status_code == 401
    _login(api)
    q = runs.job_queue()
    assert isinstance(q, SQLiteJobQueue)
    jid = q.enqueue("r", {})
    for _ in range(q.max_attempts):
        job = q.claim("w")
        assert job is not None
        q.fail(job.id, "boom")
    listed = api.get("/v1/jobs/dead").json()
    assert [j["id"] for j in listed] == [jid]
    assert api.post(f"/v1/jobs/{jid}/requeue").status_code == 200
    assert api.post(f"/v1/jobs/{jid}/requeue").status_code == 404
