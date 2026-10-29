from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from harness.queue import SQLiteJobQueue, Worker
from harness.queue_arq import ArqJobQueue, QueueUnavailable


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_fifo_claim_and_complete(tmp_path: Path) -> None:
    q = SQLiteJobQueue(tmp_path / "q.db")
    a, b = q.enqueue("r1", {"n": 1}), q.enqueue("r2", {"n": 2})
    j = q.claim("w")
    assert j and j.id == a and j.payload == {"n": 1} and j.attempts == 1
    q.complete(a)
    j2 = q.claim("w")
    assert j2 and j2.id == b
    assert q.claim("w") is None  # b is leased, nothing else queued
    assert q.status(a)["status"] == "done"


def test_dead_worker_lease_expires_and_job_is_redelivered(tmp_path: Path) -> None:
    clock = Clock()
    q = SQLiteJobQueue(tmp_path / "q.db", clock=clock)
    jid = q.enqueue("r1", {})
    assert q.claim("dead", lease_s=60) is not None  # worker takes it and is then killed
    assert q.claim("w2", lease_s=60) is None  # lease still valid
    clock.t += 61
    again = q.claim("w2", lease_s=60)
    assert again and again.id == jid and again.attempts == 2


def test_attempts_are_bounded(tmp_path: Path) -> None:
    clock = Clock()
    q = SQLiteJobQueue(tmp_path / "q.db", max_attempts=2, clock=clock)
    jid = q.enqueue("r1", {})
    for _ in range(2):
        assert q.claim("w", lease_s=10) is not None
        clock.t += 11  # worker dies each time
    assert q.claim("w", lease_s=10) is None
    assert q.status(jid)["status"] == "failed"


def test_worker_retries_failures_then_gives_up(tmp_path: Path) -> None:
    q = SQLiteJobQueue(tmp_path / "q.db", max_attempts=3)
    calls: list[dict[str, Any]] = []

    def boom(p: dict[str, Any]) -> dict[str, Any]:
        calls.append(p)
        raise RuntimeError("nope")

    jid = q.enqueue("r1", {"x": 1})
    assert Worker(q, boom).run_until_empty() == 3
    assert len(calls) == 3 and q.status(jid)["status"] == "failed"
    assert "nope" in q.status(jid)["error"]


def test_arq_queue_reports_unreachable_redis_cleanly() -> None:
    pytest.importorskip("arq")
    q = ArqJobQueue("redis://127.0.0.1:1/0")  # nothing listens on port 1
    with pytest.raises(QueueUnavailable):
        q.enqueue("r1", {})
    with pytest.raises(NotImplementedError):
        q.claim("w")
