"""E2B backend, for real. Mirrors tests/infra/test_sandbox_docker.py. The backend is called
directly (bypassing the code policy on purpose) to prove the sandbox limits hold even if the policy
were fooled. Each test costs one sandbox creation from the shared budget."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from harness.sandbox.backends import E2BBackend

pytestmark = pytest.mark.e2b


def test_normal_code_runs_and_returns_output_files(sandbox: E2BBackend) -> None:
    code = (
        "import pandas as pd\n"
        "pd.DataFrame({'a': [1, 2]}).to_parquet('out_x.parquet')\n"
        "print('ok')\n"
    )
    r = sandbox.run_python(code, 60, {})
    assert r.exit_code == 0 and r.stdout.strip() == "ok" and "out_x.parquet" in r.files
    assert not r.timed_out


def test_uploaded_files_are_visible_in_the_workdir(sandbox: E2BBackend) -> None:
    code = "print(open('in.txt').read().strip())\nopen('out_y.txt', 'w').write('done')\n"
    r = sandbox.run_python(code, 60, {"in.txt": b"hello e2b\n"})
    assert r.stdout.strip() == "hello e2b" and r.files == {"out_y.txt": b"done"}


def test_nonzero_exit_and_stderr_are_reported(sandbox: E2BBackend) -> None:
    r = sandbox.run_python("import sys\nprint('x', file=sys.stderr)\nsys.exit(3)\n", 60, {})
    assert r.exit_code == 3 and "x" in r.stderr and not r.timed_out


def test_network_is_blocked(sandbox: E2BBackend) -> None:
    # allow_internet_access=False is enforced by E2B at the sandbox network layer. If a live run
    # ever shows CONNECTED, this must become a documented xfail (see docs/ws/A.md), not be hidden.
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=5)\n"
        "    print('CONNECTED')\n"
        "except OSError:\n"
        "    print('blocked')\n"
    )
    r = sandbox.run_python(code, 60, {})
    assert "blocked" in r.stdout and "CONNECTED" not in r.stdout


def test_writes_outside_the_workdir_fail(sandbox: E2BBackend) -> None:
    code = (
        "for p in ('/etc/pwned', '/usr/pwned', '/root/pwned'):\n"
        "    try:\n"
        "        open(p, 'w').write('x')\n"
        "        print('WROTE', p)\n"
        "    except OSError:\n"
        "        print('denied', p)\n"
    )
    r = sandbox.run_python(code, 60, {})
    assert "WROTE" not in r.stdout and r.stdout.count("denied") == 3


def test_fork_bomb_is_contained_and_the_sandbox_is_discarded(sandbox: E2BBackend) -> None:
    code = (
        "import os, time\n"
        "n = 0\n"
        "try:\n"
        "    while n < 20000:\n"
        "        if os.fork() == 0:\n"
        "            time.sleep(30)\n"
        "            os._exit(0)\n"
        "        n += 1\n"
        "except OSError:\n"
        "    pass\n"
        "print('forks', n)\n"
    )
    t0 = time.time()
    r = sandbox.run_python(code, 30, {})
    # contained = the call returns within the wall clock (finished or timed out) and the
    # sandbox is killed in `finally`; the next sandbox is fresh and healthy
    assert time.time() - t0 < 30 + 40
    assert r.timed_out or "forks" in r.stdout
    assert sandbox.kill_failures == 0


def test_timeout_kills_the_sandbox(sandbox: E2BBackend) -> None:
    t0 = time.time()
    r = sandbox.run_python("import time\nwhile True:\n    time.sleep(1)\n", 4, {})
    assert r.timed_out and r.exit_code == -9
    assert time.time() - t0 < 60
    assert sandbox.kill_failures == 0


def test_agent_feature_step_end_to_end_through_e2b(
    sandbox: E2BBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harness.agent.models import RunBudget
    from harness.agent.planners import ScriptedPlanner
    from harness.agent.runner import AgentRunner
    from harness.agent.store import RunStore
    from harness.sandbox import backends
    from tests.unit.test_agent_runner import cfg_for
    from tests.unit.test_feature_step import _skewed

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATA_TOOLS_ROOTS", str(data))
    monkeypatch.setenv("EXPERIMENTS_DIR", str(tmp_path / "exp"))
    monkeypatch.setattr(backends, "backend_from_env", lambda: sandbox)  # budget-gated E2B
    budget = RunBudget(flaml_budget_s=0, tune_trials=0)
    cfg = cfg_for(_skewed(data), sandbox_features=True, budget=budget)
    runner = AgentRunner(RunStore(tmp_path / "r.db"), ScriptedPlanner(), run_root=tmp_path / "r")
    res = runner.run(cfg)
    assert res["status"] == "done" and not res["failures"]
    eng = RunStore(tmp_path / "r.db").checkpoints(cfg.run_id)[-1][1]["engineered"]
    assert eng["sandbox"] == type(sandbox).__name__
    assert eng["n_columns_after"] > eng["n_columns_before"]
