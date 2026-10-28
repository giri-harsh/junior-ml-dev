from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import create_engine

from trajectory import emit as emit_mod
from trajectory.db import DbSink
from trajectory.models import EventKind, TrajectoryEvent
from trajectory.writer import JsonlWriter


def test_event_round_trips_through_jsonl() -> None:
    ev = TrajectoryEvent(
        run_id="r1",
        seq=0,
        kind=EventKind.TOOL_CALL,
        agent_version="v0",
        payload={"tool": "run_python", "n": [1, 2]},
        outcome_labels={"success": True},
    )
    assert TrajectoryEvent.from_jsonl(ev.to_jsonl()) == ev


def test_unknown_field_and_kind_rejected() -> None:
    with pytest.raises(ValueError):
        TrajectoryEvent.model_validate(
            {"run_id": "r", "seq": 0, "kind": "nope", "agent_version": "v"}
        )
    with pytest.raises(ValueError):
        TrajectoryEvent.model_validate(
            {"run_id": "r", "seq": 0, "kind": "state", "agent_version": "v", "extra": 1}
        )


def test_seq_monotonic_and_ordered(tmp_path: Path) -> None:
    w = JsonlWriter(tmp_path)
    for _ in range(5):
        w.append("r1", EventKind.STATE, "v0")
    w.append("r2", EventKind.STATE, "v0")
    assert [e.seq for e in w.read("r1")] == [0, 1, 2, 3, 4]
    assert [e.seq for e in w.read("r2")] == [0]


def test_seq_resumes_from_disk(tmp_path: Path) -> None:
    JsonlWriter(tmp_path).append("r1", EventKind.STATE, "v0")
    again = JsonlWriter(tmp_path)
    assert again.append("r1", EventKind.STATE, "v0").seq == 1


def test_writer_is_append_only(tmp_path: Path) -> None:
    w = JsonlWriter(tmp_path)
    w.append("r1", EventKind.STATE, "v0", {"a": 1})
    before = w.path_for("r1").read_text(encoding="utf-8")
    w.append("r1", EventKind.DECISION, "v0", {"b": 2})
    assert w.path_for("r1").read_text(encoding="utf-8").startswith(before)


@pytest.mark.parametrize("bad", ["../x", "a/b", "a\\b", ".hidden"])
def test_unsafe_run_id_rejected(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        JsonlWriter(tmp_path).append(bad, EventKind.STATE, "v0")


@given(st.lists(st.sampled_from(list(EventKind)), min_size=1, max_size=20))
def test_property_seq_always_contiguous(kinds: list[EventKind]) -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        w = JsonlWriter(Path(d))
        for k in kinds:
            w.append("r", k, "v0")
        assert [e.seq for e in w.read("r")] == list(range(len(kinds)))


def test_db_sink_round_trip_and_idempotent() -> None:
    engine = create_engine("sqlite://")  # SQLite is allowed for unit tests only
    sink = DbSink(engine)
    sink.create_all()
    ev = TrajectoryEvent(
        run_id="r1", seq=0, kind=EventKind.BUDGET, agent_version="v0", payload={"t": 1}
    )
    sink.write(ev)
    sink.write(ev)  # replay is a no-op
    rows = sink.read("r1")
    assert len(rows) == 1
    assert rows[0].payload == {"t": 1} and rows[0].kind is EventKind.BUDGET


def test_emit_writes_jsonl_and_db(tmp_path: Path) -> None:
    engine = create_engine("sqlite://")
    sink = DbSink(engine)
    sink.create_all()
    emit_mod.configure(tmp_path, [sink])
    emit_mod.emit("demo", EventKind.PIPELINE_STEP, {"step": "profile"})
    emit_mod.emit("demo", EventKind.DECISION, {"pick": "x"})
    assert len(sink.read("demo")) == 2
    assert len(list(emit_mod.configure(tmp_path).read("demo"))) == 2


def test_emits_trajectory(tmp_path: Path) -> None:
    """Convention test required by the PRD for every new code path (S1 baseline)."""
    emit_mod.configure(tmp_path)
    ev = emit_mod.emit("conv", EventKind.PIPELINE_STEP, {"stage": "s1"})
    assert ev.seq == 0 and (tmp_path / "conv.jsonl").exists()
