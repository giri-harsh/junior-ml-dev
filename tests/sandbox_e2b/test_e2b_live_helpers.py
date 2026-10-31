"""Budget gate, latency maths and the SDK-shape contract, all without network or a key."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from harness.sandbox import e2b_live
from harness.sandbox.backends import E2B_WORKDIR, E2BBackend
from tests.sandbox_e2b.test_e2b_backend_mocked import FakeSDK


def test_percentile_is_nearest_rank() -> None:
    xs = [float(i) for i in range(1, 21)]
    assert e2b_live.percentile(xs, 50) == 10.0
    assert e2b_live.percentile(xs, 95) == 19.0
    assert e2b_live.percentile([7.0], 95) == 7.0


def test_budgeted_backend_reserves_one_creation_per_exec(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[int] = []
    monkeypatch.setattr(e2b_live, "reserve", lambda n: asked.append(n) or True)
    be = e2b_live.BudgetedE2B(api_key="k", sdk=FakeSDK())
    be.run_python("pass", 5, {})
    be.run_python("pass", 5, {})
    assert asked == [1, 1] and be.creations == 2


def test_denied_budget_creates_no_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(e2b_live, "reserve", lambda n: False)
    sdk = FakeSDK()
    with pytest.raises(e2b_live.BudgetDenied):
        e2b_live.BudgetedE2B(api_key="k", sdk=sdk).run_python("pass", 5, {})
    assert sdk.boxes == []


def test_missing_budget_helper_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(e2b_live, "_budget_script", lambda: None)
    assert e2b_live.reserve(1) is False


def test_measure_latency_summarises_total_and_stages() -> None:
    sdk = FakeSDK(fs={f"{E2B_WORKDIR}/out_latency.txt": b"ok"})
    res = e2b_live.measure_latency(E2BBackend(api_key="k", sdk=sdk), 5)
    assert (res["n_requested"], res["n_ok"], res["n_failed"]) == (5, 5, 0)
    assert {"p50", "p95", "max"} <= set(res["total_s"])
    assert {"create_s", "exec_s", "kill_s"} <= set(res["stages_s"])
    assert len(sdk.boxes) == 5 and all(b.killed.is_set() for b in sdk.boxes)


def test_measure_latency_with_all_failures_raises_instead_of_inventing_numbers() -> None:
    be = E2BBackend(api_key="k", sdk=FakeSDK())
    with pytest.raises(RuntimeError, match="no latency"):
        e2b_live.measure_latency(be, 3)


def test_main_without_a_key_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    assert e2b_live.main() == 0
    assert "NOT RUN" in capsys.readouterr().out


def test_budget_script_resolves_in_a_worktree() -> None:
    script = e2b_live._budget_script()
    assert script is None or script.name == "budget.py"


def test_backend_matches_the_real_sdk_shape(tmp_path: Path) -> None:
    """Pin the parts of the e2b 2.x API the backend relies on (skipped if e2b is not installed)."""
    import inspect

    e2b = pytest.importorskip("e2b")
    create = set(inspect.signature(e2b.Sandbox.create).parameters)
    assert {"timeout", "allow_internet_access", "metadata", "template"} <= create
    from e2b.connection_config import ApiParams

    assert {"api_key", "request_timeout"} <= set(ApiParams.__annotations__)
    from e2b.sandbox_sync.commands.command import Commands
    from e2b.sandbox_sync.filesystem.filesystem import Filesystem

    assert {"cwd", "user", "timeout", "request_timeout"} <= set(
        inspect.signature(Commands.run).parameters
    )
    assert {"format"} <= set(inspect.signature(Filesystem.read).parameters)
    assert {"request_timeout"} <= set(inspect.signature(Filesystem.write).parameters)
    assert callable(e2b.Sandbox.kill) and callable(Filesystem.list)


def test_real_sdk_exceptions_are_classified_like_the_fakes() -> None:
    e2b = pytest.importorskip("e2b")

    class Box:
        def __init__(self, exc: Exception) -> None:
            self.exc = exc

        def run(self, *a: Any, **kw: Any) -> None:
            raise self.exc

    be = E2BBackend(api_key="k", sdk=FakeSDK())
    box = Box(e2b.TimeoutException("deadline"))
    box.commands = box  # type: ignore[attr-defined]
    assert be._exec(box, 1) == ("", "timeout", -9)
    box = Box(e2b.CommandExitException(stdout="o", stderr="e", exit_code=2, error=""))
    box.commands = box  # type: ignore[attr-defined]
    assert be._exec(box, 1) == ("o", "e", 2)
