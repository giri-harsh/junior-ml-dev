"""SQL run store (Postgres in compose, SQLite via SQLAlchemy in unit tests): same API as RunStore.

Portable SQL only (`ON CONFLICT`, named parameters), so the unit tests exercise the exact
statements Postgres runs. Postgres itself is covered by tests/infra (NOT RUN without services).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from sqlalchemy import Engine, create_engine, text

from harness.agent.models import RunConfig, StepRecord
from harness.agent.store import RunStore

DDL = [
    "CREATE TABLE IF NOT EXISTS runs (run_id VARCHAR(64) PRIMARY KEY, status VARCHAR(32) NOT NULL,"
    " config TEXT NOT NULL, created DOUBLE PRECISION NOT NULL, updated DOUBLE PRECISION NOT NULL,"
    " result TEXT)",
    "CREATE TABLE IF NOT EXISTS checkpoints (run_id VARCHAR(64) NOT NULL, idx INTEGER NOT NULL,"
    " record TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY (run_id, idx))",
]


class SqlRunStore:
    def __init__(self, url: str, engine: Engine | None = None) -> None:
        self.url = url
        self.engine = engine or create_engine(url, pool_pre_ping=True)
        with self.engine.begin() as c:
            for stmt in DDL:
                c.execute(text(stmt))

    def create(self, cfg: RunConfig) -> bool:
        now = time.time()
        with self.engine.begin() as c:
            cur = c.execute(
                text(
                    "INSERT INTO runs (run_id, status, config, created, updated)"
                    " VALUES (:r, 'running', :cfg, :t, :t) ON CONFLICT (run_id) DO NOTHING"
                ),
                {"r": cfg.run_id, "cfg": cfg.model_dump_json(), "t": now},
            )
            return cur.rowcount == 1

    def _one(self, sql: str, **p: Any) -> Any:
        with self.engine.connect() as c:
            row = c.execute(text(sql), p).fetchone()
        return None if row is None else row[0]

    def config(self, run_id: str) -> RunConfig:
        raw = self._one("SELECT config FROM runs WHERE run_id=:r", r=run_id)
        if raw is None:
            raise KeyError(run_id)
        return RunConfig.model_validate_json(raw)

    def status(self, run_id: str) -> str | None:
        v = self._one("SELECT status FROM runs WHERE run_id=:r", r=run_id)
        return None if v is None else str(v)

    def set_status(self, run_id: str, status: str, result: dict[str, Any] | None = None) -> None:
        with self.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE runs SET status=:s, updated=:t, result=COALESCE(:res, result)"
                    " WHERE run_id=:r"
                ),
                {
                    "s": status, "t": time.time(), "r": run_id,
                    "res": None if result is None else json.dumps(result),
                },
            )  # fmt: skip

    def result(self, run_id: str) -> dict[str, Any] | None:
        raw = self._one("SELECT result FROM runs WHERE run_id=:r", r=run_id)
        return None if raw is None else dict(json.loads(raw))

    def checkpoint(self, run_id: str, rec: StepRecord, state: dict[str, Any]) -> None:
        with self.engine.begin() as c:
            c.execute(
                text(
                    "INSERT INTO checkpoints (run_id, idx, record, state)"
                    " VALUES (:r, :i, :rec, :st)"
                    " ON CONFLICT (run_id, idx) DO UPDATE SET record=:rec, state=:st"
                ),
                {
                    "r": run_id, "i": rec.idx, "rec": rec.model_dump_json(),
                    "st": json.dumps(state, default=str),
                },
            )  # fmt: skip

    def checkpoints(self, run_id: str) -> list[tuple[StepRecord, dict[str, Any]]]:
        with self.engine.connect() as c:
            rows = c.execute(
                text("SELECT record, state FROM checkpoints WHERE run_id=:r ORDER BY idx"),
                {"r": run_id},
            ).fetchall()
        return [(StepRecord.model_validate_json(r), dict(json.loads(s))) for r, s in rows]

    def list_runs(self) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            rows = c.execute(
                text("SELECT run_id, status, created, updated FROM runs ORDER BY created")
            ).fetchall()
        return [{"run_id": a, "status": b, "created": cr, "updated": u} for a, b, cr, u in rows]

    def step_stats(self) -> list[dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        with self.engine.connect() as c:
            rows = c.execute(text("SELECT record FROM checkpoints")).fetchall()
        for (raw,) in rows:
            rec = StepRecord.model_validate_json(raw)
            s = out.setdefault(
                rec.step.tool, {"tool": rec.step.tool, "n": 0, "failed": 0, "latency_s": 0.0}
            )
            s["n"] += 1
            s["failed"] += 0 if rec.ok else 1
            s["latency_s"] += rec.latency_s
        return list(out.values())


def open_run_store(default_path: str) -> RunStore | SqlRunStore:
    """RUNS_DATABASE_URL (postgresql+psycopg://... or sqlite:///...) selects the SQL store."""
    url = os.environ.get("RUNS_DATABASE_URL", "")
    return SqlRunStore(url) if url else RunStore(default_path)
