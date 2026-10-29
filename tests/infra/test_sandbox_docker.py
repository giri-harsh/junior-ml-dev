"""Docker sandbox backend, for real. Runs only where Docker works (CI); image built from
deploy/sandbox/Dockerfile as `jmd-sandbox:latest`. The backend is called directly (bypassing the
code policy on purpose) to prove the container limits hold even if the policy were fooled."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from harness.sandbox.backends import LocalDockerBackend

pytestmark = pytest.mark.infra


@pytest.fixture
def sandbox(docker_bin: str) -> LocalDockerBackend:
    have = subprocess.run(
        [docker_bin, "image", "inspect", "jmd-sandbox:latest"], capture_output=True
    )
    if have.returncode != 0:
        subprocess.run(
            [docker_bin, "build", "-t", "jmd-sandbox:latest", "deploy/sandbox"], check=True
        )
    return LocalDockerBackend()


def test_normal_code_runs_and_returns_output_files(sandbox: LocalDockerBackend) -> None:
    code = (
        "import pandas as pd\n"
        "pd.DataFrame({'a': [1, 2]}).to_parquet('out_x.parquet')\n"
        "print('ok')\n"
    )
    r = sandbox.run_python(code, 60, {})
    assert r.exit_code == 0 and r.stdout.strip() == "ok" and "out_x.parquet" in r.files


def test_network_is_blocked(sandbox: LocalDockerBackend) -> None:
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        "    print('CONNECTED')\n"
        "except OSError:\n"
        "    print('blocked')\n"
    )
    r = sandbox.run_python(code, 60, {})
    assert "blocked" in r.stdout and "CONNECTED" not in r.stdout


def test_writes_outside_the_workdir_fail(sandbox: LocalDockerBackend) -> None:
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


def test_fork_bomb_is_contained_by_the_pids_limit(sandbox: LocalDockerBackend) -> None:
    code = (
        "import os, time\n"
        "n = 0\n"
        "try:\n"
        "    while n < 5000:\n"
        "        if os.fork() == 0:\n"
        "            time.sleep(5)\n"
        "            os._exit(0)\n"
        "        n += 1\n"
        "except OSError:\n"
        "    pass\n"
        "print('forks', n)\n"
    )
    t0 = time.time()
    r = sandbox.run_python(code, 60, {})
    forks = int(r.stdout.split("forks")[1]) if "forks" in r.stdout else 0
    assert 0 < forks <= 130 and time.time() - t0 < 60  # capped by --pids-limit, host unharmed


def test_timeout_kills_the_container(sandbox: LocalDockerBackend, docker_bin: str) -> None:
    r = sandbox.run_python("import time\nwhile True:\n    time.sleep(1)\n", 4, {})
    assert r.timed_out and r.exit_code == -9
    left = subprocess.run(
        [docker_bin, "ps", "--filter", "name=jmd-sbx-", "-q"], capture_output=True, text=True
    ).stdout.strip()
    assert left == "", "container still running after the timeout"


def test_agent_feature_step_end_to_end_through_docker(
    sandbox: LocalDockerBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harness.agent.models import RunBudget
    from harness.agent.planners import ScriptedPlanner
    from harness.agent.runner import AgentRunner
    from harness.agent.store import RunStore
    from tests.unit.test_agent_runner import cfg_for
    from tests.unit.test_feature_step import _skewed

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATA_TOOLS_ROOTS", str(data))
    monkeypatch.setenv("EXPERIMENTS_DIR", str(tmp_path / "exp"))
    monkeypatch.setenv("JMD_SANDBOX", "docker")
    budget = RunBudget(flaml_budget_s=0, tune_trials=0)
    cfg = cfg_for(_skewed(data), sandbox_features=True, budget=budget)
    runner = AgentRunner(RunStore(tmp_path / "r.db"), ScriptedPlanner(), run_root=tmp_path / "r")
    res = runner.run(cfg)
    assert res["status"] == "done" and not res["failures"]
    eng = RunStore(tmp_path / "r.db").checkpoints(cfg.run_id)[-1][1]["engineered"]
    assert (
        eng["sandbox"] == "LocalDockerBackend" and eng["n_columns_after"] > eng["n_columns_before"]
    )
