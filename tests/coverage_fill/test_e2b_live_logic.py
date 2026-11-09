"""Budget plumbing, failure accounting and the measurement entry point of harness.sandbox.e2b_live,
driven by a fake backend and a stand-in budget script. No E2B call is possible: the real SDK is
never imported, the real budget ledger is never touched, and no result file is written to the repo."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from harness.sandbox import e2b_live
from harness.sandbox.backends import ExecResult


def _write_budget_script(path: Path, exit_code: int, log: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "import sys\n"
        f"open({str(log)!r}, 'a', encoding='utf-8').write(' '.join(sys.argv[1:]) + '\\n')\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    return path


def test_budget_script_is_found_relative_to_the_repo_and_then_the_main_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_here = tmp_path / "wt" / "harness" / "sandbox" / "e2b_live.py"
    fake_here.parent.mkdir(parents=True)
    main_checkout = tmp_path / "main"
    monkeypatch.setattr(e2b_live, "_HERE", fake_here)
    monkeypatch.setattr(e2b_live, "_main_checkout", lambda: [main_checkout])
    assert e2b_live._budget_script() is None  # nowhere to be found

    (main_checkout / "scripts").mkdir(parents=True)
    (main_checkout / "scripts" / "budget.py").write_text("", encoding="utf-8")
    assert e2b_live._budget_script() == main_checkout / "scripts" / "budget.py"

    (tmp_path / "wt" / "scripts").mkdir()
    (tmp_path / "wt" / "scripts" / "budget.py").write_text("", encoding="utf-8")
    assert e2b_live._budget_script() == tmp_path / "wt" / "scripts" / "budget.py"  # own repo first


def test_main_checkout_is_the_parent_of_the_git_common_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="/repos/proj/.git\n", stderr="")

    monkeypatch.setattr(e2b_live.subprocess, "run", fake_run)
    assert e2b_live._main_checkout() == [Path("/repos/proj")]
    assert seen["cmd"][:2] == ["git", "rev-parse"] and "--git-common-dir" in seen["cmd"]


@pytest.mark.parametrize(
    "exc", [FileNotFoundError("no git"), subprocess.CalledProcessError(128, ["git"])]
)
def test_main_checkout_is_empty_when_git_is_unavailable_or_fails(
    monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    def boom(*a: Any, **kw: Any) -> None:
        raise exc

    monkeypatch.setattr(e2b_live.subprocess, "run", boom)
    assert e2b_live._main_checkout() == []


def test_reserve_and_commit_call_the_budget_script_with_the_ledger_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "calls.log"
    script = _write_budget_script(tmp_path / "scripts" / "budget.py", 0, log)
    monkeypatch.setattr(e2b_live, "_budget_script", lambda: script)
    assert e2b_live.reserve(20) is True
    e2b_live.commit(3, 20)
    assert log.read_text(encoding="utf-8").splitlines() == ["reserve e2b 20", "commit e2b 3 20"]


def test_a_refusing_budget_script_makes_reserve_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "calls.log"
    script = _write_budget_script(tmp_path / "budget.py", 2, log)
    monkeypatch.setattr(e2b_live, "_budget_script", lambda: script)
    assert e2b_live.reserve(1) is False
    assert log.read_text(encoding="utf-8").strip() == "reserve e2b 1"


def test_budget_without_a_script_returns_failure_and_runs_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(e2b_live, "_budget_script", lambda: None)

    def never(*a: Any, **kw: Any) -> None:
        raise AssertionError("no subprocess may start without a budget script")

    monkeypatch.setattr(e2b_live.subprocess, "run", never)
    assert e2b_live._budget("reserve", "e2b", "1") == 1
    e2b_live.commit(1, 1)  # a missing helper on commit is silent, never an exception


def test_budget_invokes_the_current_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []

    def fake_run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(e2b_live, "_budget_script", lambda: tmp_path / "budget.py")
    monkeypatch.setattr(e2b_live.subprocess, "run", fake_run)
    assert e2b_live._budget("reserve", "e2b", "5") == 0
    assert seen == [[sys.executable, str(tmp_path / "budget.py"), "reserve", "e2b", "5"]]


# --- measurement ---------------------------------------------------------------------------------
class ScriptedBackend:
    """Plays a fixed sequence of outcomes: an ExecResult, or an exception to raise."""

    name = "scripted"

    def __init__(self, outcomes: list[ExecResult | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0
        self.last_timings: dict[str, float] = {}

    def run_python(self, code: str, timeout_s: float, files: dict[str, bytes]) -> ExecResult:
        self.calls += 1
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        self.last_timings = {"create_s": o.duration_s / 2, "exec_s": o.duration_s / 4}
        return o


def ok(duration: float) -> ExecResult:
    return ExecResult(
        stdout="", stderr="", exit_code=0, timed_out=False, duration_s=duration,
        files={"out_latency.txt": b"ok"},
    )  # fmt: skip


def test_percentile_edges() -> None:
    xs = [5.0, 1.0, 3.0]
    assert e2b_live.percentile(xs, 0) == 1.0  # clamped to the first rank
    assert e2b_live.percentile(xs, 100) == 5.0
    assert e2b_live.percentile(xs, 50) == 3.0
    assert xs == [5.0, 1.0, 3.0]  # input not reordered


def test_failed_execs_are_counted_and_excluded_from_the_summary() -> None:
    bad_exit = ExecResult(stdout="", stderr="x", exit_code=1, timed_out=False, duration_s=99.0)
    no_file = ExecResult(stdout="", stderr="", exit_code=0, timed_out=False, duration_s=98.0)
    be = ScriptedBackend([ok(1.0), RuntimeError("sdk down"), bad_exit, ok(3.0), no_file, ok(2.0)])
    res = e2b_live.measure_latency(be, 6)  # type: ignore[arg-type]
    assert (res["n_requested"], res["n_ok"], res["n_failed"]) == (6, 3, 3)
    assert res["total_s"] == {"p50": 2.0, "p95": 3.0, "max": 3.0}
    assert res["stages_s"]["create_s"] == {"p50": 1.0, "p95": 1.5, "max": 1.5}
    assert be.calls == 6


def test_a_denied_budget_stops_the_measurement_instead_of_counting_a_failure() -> None:
    be = ScriptedBackend([ok(1.0), e2b_live.BudgetDenied("cap reached"), ok(1.0)])
    with pytest.raises(e2b_live.BudgetDenied):
        e2b_live.measure_latency(be, 3)  # type: ignore[arg-type]
    assert be.calls == 2


# --- main ----------------------------------------------------------------------------------------
@pytest.fixture
def fake_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dummy value so main() takes its keyed path; the backend is faked, nothing authenticates."""
    monkeypatch.setenv("E2B_API_KEY", "dummy-not-a-real-key")


def test_main_denied_budget_defers_without_creating_a_backend_or_a_result(
    fake_key: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(e2b_live, "reserve", lambda n: False)

    def no_backend(*a: Any, **kw: Any) -> None:
        raise AssertionError("must not construct a backend when the budget is denied")

    monkeypatch.setattr(e2b_live, "E2BBackend", no_backend)
    assert e2b_live.main() == 1
    assert "budget denied" in capsys.readouterr().out


def test_main_reserves_measures_commits_and_writes_the_result(
    fake_key: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import benchmarks.results_writer as rw

    events: list[Any] = []
    monkeypatch.setattr(e2b_live, "reserve", lambda n: events.append(("reserve", n)) or True)
    monkeypatch.setattr(e2b_live, "commit", lambda a, r: events.append(("commit", a, r)))
    backend = ScriptedBackend([ok(1.0), ok(2.0), RuntimeError("flaky")])
    monkeypatch.setattr(e2b_live, "E2BBackend", lambda: backend)
    monkeypatch.setattr(e2b_live, "LATENCY_N", 3)  # main() passes the module constant explicitly
    written: dict[str, Any] = {}

    def fake_write(name: str, results: dict, cond: Any, *, command: str | None = None) -> Path:
        written.update(name=name, results=results, cond=cond, command=command)
        return tmp_path / f"{name}.json"

    monkeypatch.setattr(rw, "write_result", fake_write)
    assert e2b_live.main() == 0
    # the full request is reserved up front and committed conservatively, even for failed execs
    assert events == [("reserve", 3), ("commit", 3, 3)]
    assert written["name"] == "e2b_v1"
    assert written["results"]["n_ok"] == 2 and written["results"]["n_failed"] == 1
    assert written["cond"].sandbox == "e2b" and written["cond"].llm == "none"
    assert written["cond"].n == 2
    assert written["command"] == "python -m harness.sandbox.e2b_live"
    assert f"wrote {tmp_path / 'e2b_v1.json'}" in capsys.readouterr().out


def test_main_commits_the_reservation_even_when_every_exec_fails(
    fake_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[Any] = []
    monkeypatch.setattr(e2b_live, "reserve", lambda n: events.append(("reserve", n)) or True)
    monkeypatch.setattr(e2b_live, "commit", lambda a, r: events.append(("commit", a, r)))
    monkeypatch.setattr(e2b_live, "E2BBackend", lambda: ScriptedBackend([RuntimeError("x")] * 20))
    with pytest.raises(RuntimeError, match="all 20 live execs failed"):
        e2b_live.main()
    assert events == [("reserve", 20), ("commit", 20, 20)]
