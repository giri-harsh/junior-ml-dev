"""Postgres `events` table (SQLAlchemy Core) and a DB sink. Unit tests may use SQLite only."""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Engine,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    select,
)

from trajectory.models import EventKind, TrajectoryEvent

metadata = MetaData()

events = Table(
    "events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String(128), nullable=False),
    Column("seq", Integer, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("agent_version", String(128), nullable=False),
    Column("prompt_hash", String(128), nullable=True),
    Column("payload", JSON, nullable=False),
    Column("outcome_labels", JSON, nullable=True),
    UniqueConstraint("run_id", "seq", name="uq_events_run_seq"),
    Index("ix_events_run_id", "run_id"),
)


def default_database_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql+psycopg://jmd:jmd@localhost:5432/jmd")


def make_engine(url: str | None = None, connect_args: dict[str, Any] | None = None) -> Engine:
    return create_engine(
        url or default_database_url(), future=True, connect_args=connect_args or {}
    )


class DbSink:
    """Idempotent on (run_id, seq): replaying an event is a no-op, not an error."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create_all(self) -> None:
        metadata.create_all(self.engine)

    def write(self, event: TrajectoryEvent) -> None:
        with self.engine.begin() as conn:
            exists = conn.execute(
                select(events.c.id).where(
                    events.c.run_id == event.run_id, events.c.seq == event.seq
                )
            ).first()
            if exists:
                return
            conn.execute(events.insert().values(**event.model_dump(mode="python")))

    def read(self, run_id: str) -> list[TrajectoryEvent]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(events).where(events.c.run_id == run_id).order_by(events.c.seq)
            ).mappings()
            return [
                TrajectoryEvent(
                    run_id=r["run_id"],
                    seq=r["seq"],
                    ts=r["ts"],
                    kind=EventKind(r["kind"]),
                    agent_version=r["agent_version"],
                    prompt_hash=r["prompt_hash"],
                    payload=r["payload"],
                    outcome_labels=r["outcome_labels"],
                )
                for r in rows
            ]
