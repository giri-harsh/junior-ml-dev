"""RunStore contract run against both implementations (SQLite-native and SQLAlchemy).

The SQLAlchemy store runs the same portable SQL Postgres runs; the Postgres variant itself is in
tests/infra (marker `infra`, auto-skipped without services).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from harness.agent.models import RunBudget, RunConfig, RunTask, Step, StepRecord
from harness.agent.planners import ScriptedPlanner
from harness.agent.runner import AgentRunner
from harness.agent.sql_store import SqlRunStore, open_run_store
from harness.agent.store import RunStore
from tests.unit.test_agent_runner import cfg_for, make_csv
from tests.unit.test_agent_runner import env as env  # noqa: F401

Factory = Callable[[Path], Any]
FACTORIES: dict[str, Factory] = {
    "sqlite-native": lambda p: RunStore(p / "a.db"),
    "sqlalchemy": lambda p: SqlRunStore(f"sqlite:///{(p / 'b.db').as_posix()}"),
}


def _cfg(rid: str = "r1") -> RunConfig:
    return RunConfig(
        run_id=rid,
        task=RunTask(name="t", data_path="x.csv", target="y", task_type="binary", metric="roc_auc"),
    )


def _rec(i: int, ok: bool = True) -> StepRecord:
    return StepRecord(idx=i, step=Step(tool="profile_dataset"), ok=ok, result={}, latency_s=0.5)


@pytest.fixture(params=sorted(FACTORIES))
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Any:
    return FACTORIES[request.param](tmp_path)


def test_create_is_idempotent_and_status_roundtrips(store: Any) -> None:
    assert store.create(_cfg()) is True and store.create(_cfg()) is False
    assert store.status("r1") == "running" and store.status("nope") is None
    assert store.config("r1").run_id == "r1"
    store.set_status("r1", "done", {"v": 1})
    store.set_status("r1", "done")  # no result: keeps the previous one
    assert store.status("r1") == "done" and store.result("r1") == {"v": 1}
    with pytest.raises(KeyError):
        store.config("nope")


def test_checkpoints_are_ordered_and_replace_on_conflict(store: Any) -> None:
    store.create(_cfg())
    for i in (2, 0, 1):
        store.checkpoint("r1", _rec(i), {"n": i})
    store.checkpoint("r1", _rec(1, ok=False), {"n": 99})  # same idx: replaced, not duplicated
    cps = store.checkpoints("r1")
    assert [r.idx for r, _ in cps] == [0, 1, 2] and cps[1][0].ok is False and cps[1][1] == {"n": 99}


def test_listing_and_step_stats(store: Any) -> None:
    store.create(_cfg("a"))
    store.create(_cfg("b"))
    store.checkpoint("a", _rec(0), {})
    store.checkpoint("a", _rec(1, ok=False), {})
    assert [r["run_id"] for r in store.list_runs()] == ["a", "b"]
    (stat,) = store.step_stats()
    assert stat["tool"] == "profile_dataset" and stat["n"] == 2 and stat["failed"] == 1


def test_agent_runs_and_resumes_on_the_sql_store(env: Path, tmp_path: Path) -> None:  # noqa: F811
    db = f"sqlite:///{(tmp_path / 'sql.db').as_posix()}"
    cfg = cfg_for(make_csv(env), budget=RunBudget(flaml_budget_s=0, tune_trials=0))
    first = AgentRunner(SqlRunStore(db), ScriptedPlanner(), run_root=tmp_path / "r").run(cfg)
    assert first["status"] == "done"
    again = AgentRunner(SqlRunStore(db), ScriptedPlanner(), run_root=tmp_path / "r").run(cfg)
    assert again == first  # terminal runs are returned, not redone


def test_factory_picks_the_store_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RUNS_DATABASE_URL", raising=False)
    assert isinstance(open_run_store(str(tmp_path / "x.db")), RunStore)
    monkeypatch.setenv("RUNS_DATABASE_URL", f"sqlite:///{(tmp_path / 'y.db').as_posix()}")
    assert isinstance(open_run_store(str(tmp_path / "x.db")), SqlRunStore)
