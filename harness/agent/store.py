"""Run state in SQLite: one row per run, one checkpoint per completed step.

A killed process resumes at the first step without a checkpoint. SQLite stands in for Postgres
behind the same two-table shape (STUB for Postgres, see KNOWN_GAPS).
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from harness.agent.models import RunConfig, StepRecord


class RunStore:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conn()) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, status TEXT NOT NULL,"
                " config TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,"
                " result TEXT)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS checkpoints (run_id TEXT NOT NULL,"
                " idx INTEGER NOT NULL,"
                " record TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY (run_id, idx))"
            )

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def create(self, cfg: RunConfig) -> bool:
        """Insert the run; False when it already exists (resume)."""
        now = time.time()
        with closing(self._conn()) as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO runs VALUES (?,?,?,?,?,NULL)",
                (cfg.run_id, "running", cfg.model_dump_json(), now, now),
            )
            return cur.rowcount == 1

    def config(self, run_id: str) -> RunConfig:
        with closing(self._conn()) as c:
            row = c.execute("SELECT config FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return RunConfig.model_validate_json(row[0])

    def status(self, run_id: str) -> str | None:
        with closing(self._conn()) as c:
            row = c.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return None if row is None else str(row[0])

    def set_status(self, run_id: str, status: str, result: dict[str, Any] | None = None) -> None:
        with closing(self._conn()) as c:
            c.execute(
                "UPDATE runs SET status=?, updated=?, result=COALESCE(?, result) WHERE run_id=?",
                (status, time.time(), None if result is None else json.dumps(result), run_id),
            )

    def result(self, run_id: str) -> dict[str, Any] | None:
        with closing(self._conn()) as c:
            row = c.execute("SELECT result FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return None if row is None or row[0] is None else dict(json.loads(row[0]))

    def checkpoint(self, run_id: str, rec: StepRecord, state: dict[str, Any]) -> None:
        with closing(self._conn()) as c:
            c.execute(
                "INSERT OR REPLACE INTO checkpoints VALUES (?,?,?,?)",
                (run_id, rec.idx, rec.model_dump_json(), json.dumps(state, default=str)),
            )

    def checkpoints(self, run_id: str) -> list[tuple[StepRecord, dict[str, Any]]]:
        with closing(self._conn()) as c:
            rows = c.execute(
                "SELECT record, state FROM checkpoints WHERE run_id=? ORDER BY idx", (run_id,)
            ).fetchall()
        return [(StepRecord.model_validate_json(r), dict(json.loads(s))) for r, s in rows]

    def list_runs(self) -> list[dict[str, Any]]:
        with closing(self._conn()) as c:
            rows = c.execute("SELECT run_id, status, created, updated FROM runs ORDER BY created")
            return [
                {"run_id": a, "status": b, "created": cr, "updated": u}
                for a, b, cr, u in rows.fetchall()
            ]

    def step_stats(self) -> list[dict[str, Any]]:
        """Per-tool aggregates for the metrics endpoint."""
        out: dict[str, dict[str, Any]] = {}
        with closing(self._conn()) as c:
            rows = c.execute("SELECT record FROM checkpoints").fetchall()
        for (raw,) in rows:
            rec = StepRecord.model_validate_json(raw)
            s = out.setdefault(
                rec.step.tool, {"tool": rec.step.tool, "n": 0, "failed": 0, "latency_s": 0.0}
            )
            s["n"] += 1
            s["failed"] += 0 if rec.ok else 1
            s["latency_s"] += rec.latency_s
        return list(out.values())
