"""`emit()`: the single call site every pipeline stage and agent step uses."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from trajectory.models import EventKind, TrajectoryEvent
from trajectory.writer import EventSink, JsonlWriter

_writer: JsonlWriter | None = None
_extra_sinks: list[EventSink] = []


def configure(root: Path | None = None, extra_sinks: list[EventSink] | None = None) -> JsonlWriter:
    """(Re)configure the process-wide writer. JSONL is always on; DB sinks are optional."""
    global _writer
    _writer = JsonlWriter(root or Path(os.environ.get("TRAJECTORY_DIR", "data/trajectories")))
    _extra_sinks.clear()
    _extra_sinks.extend(extra_sinks or [])
    return _writer


def emit(
    run_id: str,
    kind: EventKind,
    payload: dict[str, Any] | None = None,
    *,
    agent_version: str = "dev",
    prompt_hash: str | None = None,
    outcome_labels: dict[str, Any] | None = None,
) -> TrajectoryEvent:
    writer = _writer or configure()
    event = writer.append(
        run_id,
        kind,
        agent_version,
        payload,
        prompt_hash=prompt_hash,
        outcome_labels=outcome_labels,
    )
    for sink in _extra_sinks:
        sink.write(event)
    return event
