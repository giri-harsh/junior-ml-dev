from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from benchmarks import agent_benchmark as ab
from benchmarks.tasks.registry import TaskSpec, load_registry
from leakage import ledger

REAL_LEDGER = Path("benchmarks/eval_ledger.json")


@pytest.fixture(autouse=True)
def real_ledger_untouched() -> Iterator[None]:
    """Guard: no test in this module may modify the real eval ledger or real result files."""
    before = REAL_LEDGER.stat().st_mtime_ns
    results = Path("benchmarks/results/agent_v1.json")
    existed = results.exists()
    yield
    assert REAL_LEDGER.stat().st_mtime_ns == before, "test touched the REAL eval ledger"
    assert results.exists() == existed, "test wrote a REAL benchmark result"


def specs() -> list[TaskSpec]:
    return load_registry()[:3]


def refs(sp: list[TaskSpec]) -> dict[str, dict[str, Any]]:
    out = {}
    for s in sp:
        hi = s.metric not in {"rmse", "mae"}
        out[s.name] = {
            "dummy": 0.5 if hi else 10.0, "linear": 0.8 if hi else 4.0,
            "flaml": 0.9 if hi else 2.0, "linear_normalized": 0.75,
        }  # fmt: skip
    return out


def fake(sp: TaskSpec) -> dict[str, Any]:
    hi = sp.metric not in {"rmse", "mae"}
    return {"agent": 0.88 if hi else 2.5, "scale": None if hi else 5.0, "status": "done"}


def go(tmp_path: Path, run_one: Any, **kw: Any) -> Path:
    sp = specs()
    return ab.run_benchmark(
        sp, run_one, refs(sp), digest=kw.pop("digest", "h" * 64),
        ledger_path=tmp_path / "ledger.json", out_dir=tmp_path / "out", **kw,
    )  # fmt: skip


def test_runs_once_per_freeze_hash_and_claims_before_running(tmp_path: Path) -> None:
    seen_claimed: list[bool] = []

    def run_one(sp: TaskSpec) -> dict[str, Any]:
        seen_claimed.append(ledger.is_spent("agent:" + "h" * 64, tmp_path / "ledger.json"))
        return fake(sp)

    path = go(tmp_path, run_one)
    assert all(seen_claimed) and len(seen_claimed) == 3  # entry existed BEFORE each task ran
    res = json.loads(path.read_text(encoding="utf-8"))
    assert res["conditions"]["llm"] == "none" and "SCRIPTED" in res["conditions"]["notes"]
    assert res["results"]["planner"] == "scripted"
    with pytest.raises(ledger.EvalAlreadySpent):
        go(tmp_path, fake)  # second evaluation of the same hash is refused
    assert go(tmp_path, fake, digest="g" * 64).exists()  # a different freeze is a new eval


def test_crash_then_resume_reruns_only_unfinished_tasks(tmp_path: Path) -> None:
    calls: list[str] = []

    def flaky(sp: TaskSpec) -> dict[str, Any]:
        calls.append(sp.name)
        if sp.name == specs()[1].name and calls.count(sp.name) == 1:
            raise RuntimeError("infra crash")
        return fake(sp)

    with pytest.raises(RuntimeError):
        go(tmp_path, flaky)
    with pytest.raises(ledger.EvalAlreadySpent):
        go(tmp_path, flaky)  # without --resume the spent hash stays spent
    path = go(tmp_path, flaky, resume=True)
    names = [s.name for s in specs()]
    assert calls == [names[0], names[1], names[1], names[2]]  # task 0 not rerun
    entry = json.loads((tmp_path / "ledger.json").read_text())["agent:" + "h" * 64]
    assert entry["status"] == "evaluated" and len(entry["infra_retries"]) == 1
    assert path.exists()


def test_aggregate_numbers_and_paired_ci(tmp_path: Path) -> None:
    res = json.loads(go(tmp_path, fake).read_text(encoding="utf-8"))["results"]["aggregate"]
    assert res["n_defined"] == 3 and res["excluded"] == []
    mean, lo, hi = res["agent_minus_linear_paired_ci95"]
    assert lo <= mean <= hi
    assert res["pass_vs_linear"]["n"] == 3


def test_freeze_hash_changes_with_code_budget_and_planner(tmp_path: Path) -> None:
    root = tmp_path
    for rel in ab.FREEZE_FILES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"x\r\n")
    b: dict[str, Any] = {"flaml_budget_s": 30}
    base = ab.freeze_hash(b, {"v": 1}, root)
    assert base == ab.freeze_hash(b, {"v": 1}, root)
    assert base != ab.freeze_hash({"flaml_budget_s": 31}, {"v": 1}, root)
    assert base != ab.freeze_hash(b, {"v": 2}, root)
    (root / ab.FREEZE_FILES[0]).write_bytes(b"y\n")
    assert base != ab.freeze_hash(b, {"v": 1}, root)
    (root / ab.FREEZE_FILES[0]).write_bytes(b"x\n")
    assert base == ab.freeze_hash(b, {"v": 1}, root)  # CRLF vs LF does not matter


def test_frozen_checkout_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ab, "_git", lambda *a: "M file.py" if a[0] == "status" else "abc")
    with pytest.raises(SystemExit, match="not clean"):
        ab.assert_frozen_checkout()
    monkeypatch.setattr(ab, "_git", lambda *a: "" if a[0] == "status" else str(a))
    with pytest.raises(SystemExit, match="not tagged"):
        ab.assert_frozen_checkout()
