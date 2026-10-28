"""Append-only JSONL writer with per-run monotonic sequence numbers."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

from trajectory.models import EventKind, TrajectoryEvent


class EventSink(Protocol):
    def write(self, event: TrajectoryEvent) -> None: ...


class JsonlWriter:
    """One file per run: `<root>/<run_id>.jsonl`. Never rewrites; resumes `seq` from disk."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._next_seq: dict[str, int] = {}

    def path_for(self, run_id: str) -> Path:
        if "/" in run_id or "\\" in run_id or run_id.startswith("."):
            raise ValueError(f"unsafe run_id: {run_id!r}")
        return self.root / f"{run_id}.jsonl"

    def _seq_from_disk(self, run_id: str) -> int:
        path = self.path_for(run_id)
        if not path.exists():
            return 0
        last = -1
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = TrajectoryEvent.from_jsonl(line).seq
        return last + 1

    def append(
        self,
        run_id: str,
        kind: EventKind,
        agent_version: str,
        payload: dict[str, Any] | None = None,
        *,
        prompt_hash: str | None = None,
        outcome_labels: dict[str, Any] | None = None,
    ) -> TrajectoryEvent:
        with self._lock:
            seq = self._next_seq.get(run_id)
            if seq is None:
                seq = self._seq_from_disk(run_id)
            event = TrajectoryEvent(
                run_id=run_id,
                seq=seq,
                kind=kind,
                agent_version=agent_version,
                prompt_hash=prompt_hash,
                payload=payload or {},
                outcome_labels=outcome_labels,
            )
            with self.path_for(run_id).open("a", encoding="utf-8") as fh:
                fh.write(event.to_jsonl() + "\n")
            self._next_seq[run_id] = seq + 1
            return event

    def write(self, event: TrajectoryEvent) -> None:  # EventSink compatibility (replay/import)
        with self._lock:
            with self.path_for(event.run_id).open("a", encoding="utf-8") as fh:
                fh.write(event.to_jsonl() + "\n")
            self._next_seq[event.run_id] = event.seq + 1

    def read(self, run_id: str) -> Iterator[TrajectoryEvent]:
        path = self.path_for(run_id)
        if not path.exists():
            return
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield TrajectoryEvent.from_jsonl(line)
