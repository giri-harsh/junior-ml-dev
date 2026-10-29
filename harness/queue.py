"""Job queue interface with a SQLite implementation (in-process worker) and an arq STUB.

Jobs are leased: a worker that dies mid-run leaves a `running` row whose lease expires, and the
next `claim` re-delivers it (the agent resumes from its checkpoints). Attempts are bounded.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class Job:
    id: str
    run_id: str
    payload: dict[str, Any]
    attempts: int


class JobQueue(Protocol):
    def enqueue(self, run_id: str, payload: dict[str, Any]) -> str: ...
    def claim(self, worker_id: str, lease_s: float = 300.0) -> Job | None: ...
    def complete(self, job_id: str) -> None: ...
    def fail(self, job_id: str, error: str, retry: bool = True) -> None: ...


class SQLiteJobQueue:
    def __init__(
        self,
        path: Path | str,
        max_attempts: int = 3,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path, self.max_attempts, self.clock = str(path), max_attempts, clock
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, run_id TEXT NOT NULL,"
                " payload TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL,"
                " lease_until REAL, worker TEXT, error TEXT, created REAL NOT NULL)"
            )

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def enqueue(self, run_id: str, payload: dict[str, Any]) -> str:
        jid = uuid.uuid4().hex[:16]
        with closing(self._conn()) as c:
            c.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,0,NULL,NULL,NULL,?)",
                (jid, run_id, json.dumps(payload), "queued", self.clock()),
            )
        return jid

    def claim(self, worker_id: str, lease_s: float = 300.0) -> Job | None:
        now = self.clock()
        with closing(self._conn()) as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT id, run_id, payload, attempts FROM jobs WHERE status='queued' "
                "OR (status='running' AND lease_until < ?) ORDER BY created LIMIT 1",
                (now,),
            ).fetchone()
            if row is None:
                c.execute("COMMIT")
                return None
            if row[3] >= self.max_attempts:  # lease expired too many times: give up
                c.execute(
                    "UPDATE jobs SET status='failed', error='max attempts' WHERE id=?", (row[0],)
                )
                c.execute("COMMIT")
                return self.claim(worker_id, lease_s)
            c.execute(
                "UPDATE jobs SET status='running', attempts=attempts+1, lease_until=?, worker=? "
                "WHERE id=?",
                (now + lease_s, worker_id, row[0]),
            )
            c.execute("COMMIT")
        return Job(row[0], row[1], json.loads(row[2]), row[3] + 1)

    def complete(self, job_id: str) -> None:
        with closing(self._conn()) as c:
            c.execute("UPDATE jobs SET status='done', lease_until=NULL WHERE id=?", (job_id,))

    def fail(self, job_id: str, error: str, retry: bool = True) -> None:
        with closing(self._conn()) as c:
            row = c.execute("SELECT attempts FROM jobs WHERE id=?", (job_id,)).fetchone()
            again = retry and row is not None and row[0] < self.max_attempts
            c.execute(
                "UPDATE jobs SET status=?, error=?, lease_until=NULL WHERE id=?",
                ("queued" if again else "failed", error[:300], job_id),
            )

    def status(self, job_id: str) -> dict[str, Any]:
        with closing(self._conn()) as c:
            row = c.execute(
                "SELECT status, attempts, error FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
        return {"status": row[0], "attempts": row[1], "error": row[2]} if row else {}


class ArqJobQueue:
    """STUB: arq + Redis (+ Postgres) implementation. Not run: Redis/Postgres unavailable here.

    Verify later: start Redis, implement `enqueue` via `arq.create_pool(...).enqueue_job`, and run
    the shared contract tests in tests/unit/test_queue.py against it (marker `integration`).
    """

    def __init__(self, *_: object, **__: object) -> None:
        raise NotImplementedError("arq queue is a STUB; see KNOWN_GAPS.md")


class Worker:
    def __init__(
        self, queue: SQLiteJobQueue, handler: Callable[[dict[str, Any]], dict[str, Any]],
        worker_id: str = "w1", lease_s: float = 300.0,
    ) -> None:  # fmt: skip
        self.queue, self.handler, self.worker_id, self.lease_s = queue, handler, worker_id, lease_s

    def run_once(self) -> bool:
        job = self.queue.claim(self.worker_id, self.lease_s)
        if job is None:
            return False
        try:
            self.handler(job.payload)
        except Exception as exc:  # the handler is the agent: it should not raise, but never trust
            self.queue.fail(job.id, f"{type(exc).__name__}: {exc}")
        else:
            self.queue.complete(job.id)
        return True

    def run_until_empty(self, limit: int = 1000) -> int:
        n = 0
        while n < limit and self.run_once():
            n += 1
        return n
