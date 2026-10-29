"""Job queue interface with a SQLite implementation (in-process worker) and an arq STUB.

Jobs are leased: a worker that dies mid-run leaves a `running` row whose lease expires, and the
next `claim` re-delivers it (the agent resumes from its checkpoints). Attempts are bounded.
"""

from __future__ import annotations

import json
import sqlite3
import threading
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
                    "UPDATE jobs SET status='dead', error='max attempts' WHERE id=?",
                    (row[0],),
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
                ("queued" if again else "dead", error[:300], job_id),
            )

    def dead_letters(self) -> list[dict[str, Any]]:
        """Jobs that exhausted their attempts (state `dead`): inspect, fix, then `requeue_dead`."""
        with closing(self._conn()) as c:
            rows = c.execute(
                "SELECT id, run_id, attempts, error FROM jobs WHERE status='dead' ORDER BY created"
            ).fetchall()
        return [{"id": a, "run_id": b, "attempts": n, "error": e} for a, b, n, e in rows]

    def requeue_dead(self, job_id: str) -> bool:
        """Give a dead job a fresh set of attempts. Its run resumes from its checkpoints."""
        with closing(self._conn()) as c:
            cur = c.execute(
                "UPDATE jobs SET status='queued', attempts=0, error=NULL, lease_until=NULL"
                " WHERE id=? AND status='dead'",
                (job_id,),
            )
            return cur.rowcount == 1

    def status(self, job_id: str) -> dict[str, Any]:
        with closing(self._conn()) as c:
            row = c.execute(
                "SELECT status, attempts, error FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
        return {"status": row[0], "attempts": row[1], "error": row[2]} if row else {}


class Worker:
    """Pulls jobs one at a time. `request_stop()` (or SIGTERM via `install_signal_handlers`)
    stops it claiming new jobs; the job in hand is allowed to finish (up to `grace_s` in
    `run_forever`); if it does not, its lease expires and another worker resumes the run from the
    last checkpoint."""

    def __init__(
        self, queue: SQLiteJobQueue, handler: Callable[[dict[str, Any]], dict[str, Any]],
        worker_id: str = "w1", lease_s: float = 300.0,
    ) -> None:  # fmt: skip
        self.queue, self.handler, self.worker_id, self.lease_s = queue, handler, worker_id, lease_s
        self._stop = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def run_once(self) -> bool:
        if self._stop.is_set():
            return False
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

    def _step(self, box: list[bool]) -> None:
        box.append(self.run_once())

    def run_forever(self, poll_s: float = 1.0, grace_s: float = 30.0) -> int:
        """Loop until `request_stop()`. Returns the number of jobs finished. The in-flight job
        runs in a daemon thread so a stuck job cannot block shutdown past `grace_s`."""
        done = 0
        while not self._stop.is_set():
            box: list[bool] = []
            t = threading.Thread(target=self._step, args=(box,), daemon=True)
            t.start()
            while t.is_alive():
                t.join(0.1)
                if self._stop.is_set():
                    t.join(grace_s)  # drain the job in hand, then give up on it
                    break
            if t.is_alive():
                return done  # lease will expire; the run resumes elsewhere from its checkpoints
            if box and box[0]:
                done += 1
            elif not self._stop.wait(poll_s):
                continue
        return done

    def install_signal_handlers(self) -> None:
        import signal

        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: self.request_stop())

    def run_until_empty(self, limit: int = 1000) -> int:
        n = 0
        while n < limit and self.run_once():
            n += 1
        return n
