"""E2B backend, for real. Mirrors tests/infra/test_sandbox_docker.py. The backend is called
directly (bypassing the code policy on purpose) to prove the sandbox limits hold even if the policy
were fooled. Each test costs one sandbox creation from the shared budget."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from harness.sandbox.backends import E2BBackend

pytestmark = pytest.mark.e2b


# The default E2B template is bare python 3.11 (no numpy/pandas/pyarrow). Data-science tests need a
# template that has them (internet is off by design, so pip install inside the sandbox is not an
# option; docs/ws/A.md). JMD_E2B_TEMPLATE: numpy+pandas (public `code-interpreter-v1` works).
# JMD_E2B_PARQUET_TEMPLATE: additionally pyarrow (needs a custom template; `code-interpreter-v1`
# has no parquet engine).
needs_template = pytest.mark.skipif(
    not os.environ.get("JMD_E2B_TEMPLATE"),
    reason="needs JMD_E2B_TEMPLATE with numpy+pandas (default template has none)",
)
needs_parquet_template = pytest.mark.skipif(
    not os.environ.get("JMD_E2B_PARQUET_TEMPLATE"),
    reason="needs JMD_E2B_PARQUET_TEMPLATE with pandas+pyarrow+sklearn (custom template)",
)


def test_normal_code_runs_and_returns_output_files(sandbox: E2BBackend) -> None:
    code = "import json\njson.dump({'a': [1, 2]}, open('out_x.json', 'w'))\nprint('ok')\n"
    r = sandbox.run_python(code, 60, {})
    assert r.exit_code == 0 and r.stdout.strip() == "ok" and "out_x.json" in r.files
    assert not r.timed_out


@needs_parquet_template
def test_pandas_parquet_output_roundtrip(parquet_sandbox: E2BBackend) -> None:
    sandbox = parquet_sandbox
    code = (
        "import pandas as pd\n"
        "pd.DataFrame({'a': [1, 2]}).to_parquet('out_x.parquet')\n"
        "print('ok')\n"
    )
    r = sandbox.run_python(code, 60, {})
    assert r.exit_code == 0 and r.stdout.strip() == "ok" and "out_x.parquet" in r.files


def test_uploaded_files_are_visible_in_the_workdir(sandbox: E2BBackend) -> None:
    code = "print(open('in.txt').read().strip())\nopen('out_y.txt', 'w').write('done')\n"
    r = sandbox.run_python(code, 60, {"in.txt": b"hello e2b\n"})
    assert r.stdout.strip() == "hello e2b" and r.files == {"out_y.txt": b"done"}


def test_nonzero_exit_and_stderr_are_reported(sandbox: E2BBackend) -> None:
    r = sandbox.run_python("import sys\nprint('x', file=sys.stderr)\nsys.exit(3)\n", 60, {})
    assert r.exit_code == 3 and "x" in r.stderr and not r.timed_out


def test_network_is_blocked(sandbox: E2BBackend) -> None:
    # Live finding (docs/ws/A.md): with allow_internet_access=False the TCP handshake to an outside
    # IP still completes (a bare connect() is NOT a valid probe), but no byte is ever exchanged and
    # DNS fails. So the test requires an actual data exchange and a name lookup to both fail.
    code = (
        "import socket\n"
        "def exchange(host, port, payload):\n"
        "    try:\n"
        "        s = socket.create_connection((host, port), timeout=5)\n"
        "        s.settimeout(5)\n"
        "        s.sendall(payload)\n"
        "        return bool(s.recv(16))\n"
        "    except OSError:\n"
        "        return False\n"
        "req = b'GET / HTTP/1.0\\r\\nHost: one.one.one.one\\r\\n\\r\\n'\n"
        "print('TCP_DATA=%d' % exchange('1.1.1.1', 80, req))\n"
        "try:\n"
        "    socket.gethostbyname('example.com')\n"
        "    print('DNS=1')\n"
        "except OSError:\n"
        "    print('DNS=0')\n"
    )
    r = sandbox.run_python(code, 60, {})
    assert r.stdout.split() == ["TCP_DATA=0", "DNS=0"], r.stdout


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


@needs_template
def test_agent_written_feature_code_end_to_end_csv(sandbox: E2BBackend) -> None:
    """Policy -> E2B -> engineered CSV back, without parquet (works on code-interpreter-v1)."""
    import io

    import numpy as np
    import pandas as pd

    from harness.sandbox.backends import run_checked

    code = (
        "import numpy as np\n"
        "import pandas as pd\n"
        "df = pd.read_csv('train.csv')\n"
        "df['fe_log1p_a'] = np.log1p(df['a'])\n"
        "df.to_csv('out_train.csv', index=False)\n"
        "print(len(df.columns))\n"
    )
    df = pd.DataFrame({"a": np.arange(1.0, 51.0), "y": np.arange(50) % 2})
    r = run_checked(sandbox, code, 60.0, {"train.csv": df.to_csv(index=False).encode()})
    assert r.exit_code == 0, r.stderr
    out = pd.read_csv(io.BytesIO(r.files["out_train.csv"]))
    assert list(out.columns) == ["a", "y", "fe_log1p_a"] and r.stdout.strip() == "3"
    assert np.allclose(out["fe_log1p_a"], np.log1p(df["a"]))


@needs_parquet_template
def test_agent_feature_step_end_to_end_through_e2b(
    parquet_sandbox: E2BBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox = parquet_sandbox
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
