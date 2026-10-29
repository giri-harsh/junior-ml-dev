"""arq worker policy (retries, timeout, settings) against fakeredis: no Redis server needed."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("arq")
fakeredis = pytest.importorskip("fakeredis")

from arq.connections import ArqRedis  # noqa: E402
from arq.jobs import Job, JobStatus  # noqa: E402
from arq.worker import Worker  # noqa: E402

from harness import queue_arq  # noqa: E402


@pytest.fixture(autouse=True)
def _no_redis_info(monkeypatch: pytest.MonkeyPatch) -> None:
    async def skip(*_: Any, **__: Any) -> None:  # fakeredis has no INFO; arq only logs it
        return None

    monkeypatch.setattr("arq.worker.log_redis_info", skip)


def _redis() -> ArqRedis:
    server = fakeredis.FakeServer()
    return ArqRedis(connection_pool=fakeredis.FakeAsyncRedis(server=server).connection_pool)


def _worker(redis: ArqRedis, **kw: Any) -> Worker:
    return Worker(
        functions=[queue_arq.run_agent], redis_pool=redis, burst=True, poll_delay=0.05,
        max_tries=kw.pop("max_tries", queue_arq.WorkerSettings.max_tries),
        job_timeout=kw.pop("job_timeout", 30), retry_jobs=True, **kw,
    )  # fmt: skip


def test_worker_settings_are_explicit_and_sane() -> None:
    s = queue_arq.WorkerSettings
    assert s.max_tries == 3 and s.job_timeout == 3600 and s.retry_jobs is True
    assert s.max_jobs >= 1 and s.health_check_interval > 0 and s.functions == [queue_arq.run_agent]


def test_successful_job_runs_once_and_returns_the_result(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "apps.api.routes.runs.execute_job", lambda payload: calls.append(payload) or {"ok": 1}
    )

    async def go() -> Any:
        redis = _redis()
        job = await redis.enqueue_job("run_agent", {"config": "x"}, _job_id="j1")
        assert job is not None
        await _worker(redis).main()
        return await job.result(timeout=5)

    assert asyncio.run(go()) == {"ok": 1} and calls == [{"config": "x"}]


def test_transient_failure_is_retried_until_it_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue_arq, "RETRY_DELAY_S", 0)
    attempts: list[int] = []

    def flaky(payload: dict[str, Any]) -> dict[str, Any]:
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("db restarting")
        return {"done": True}

    monkeypatch.setattr("apps.api.routes.runs.execute_job", flaky)

    async def go() -> Any:
        redis = _redis()
        job = await redis.enqueue_job("run_agent", {}, _job_id="j2")
        assert job is not None
        for _ in range(3):  # burst mode drains the queue once; deferred retries need another pass
            await _worker(redis).main()
        return await job.result(timeout=5)

    assert asyncio.run(go()) == {"done": True} and len(attempts) == 3


def test_failure_after_max_tries_is_surfaced_not_retried_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(queue_arq, "RETRY_DELAY_S", 0)
    n: list[int] = []

    def always(payload: dict[str, Any]) -> dict[str, Any]:
        n.append(1)
        raise ConnectionError("down")

    monkeypatch.setattr("apps.api.routes.runs.execute_job", always)

    async def go() -> JobStatus:
        redis = _redis()
        job = await redis.enqueue_job("run_agent", {}, _job_id="j3")
        assert job is not None
        for _ in range(5):
            await _worker(redis).main()
        return await Job("j3", redis).status()

    status = asyncio.run(go())
    assert len(n) == queue_arq.WorkerSettings.max_tries and status == JobStatus.complete


def test_producer_enqueues_a_named_job_with_a_unique_id() -> None:
    async def go() -> list[str]:
        redis = _redis()
        a = await redis.enqueue_job("run_agent", {"x": 1}, _job_id="run1-aaa")
        b = await redis.enqueue_job("run_agent", {"x": 1}, _job_id="run1-bbb")
        assert a is not None and b is not None
        return [j.job_id for j in await redis.queued_jobs()]

    assert sorted(asyncio.run(go())) == ["run1-aaa", "run1-bbb"]
