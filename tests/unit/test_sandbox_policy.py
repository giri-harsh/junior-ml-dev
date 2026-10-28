from __future__ import annotations

import asyncio
import base64
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from harness.policies.code_policy import check_code
from harness.sandbox.backends import (
    E2BBackend,
    LocalDockerBackend,
    PolicyRefused,
    SubprocessSandbox,
    package_allowed,
    run_checked,
    safe_relpath,
)

ROOT = Path(__file__).resolve().parents[2]

GOOD = """
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
x = np.arange(10).reshape(-1, 1)
print(LogisticRegression().fit(x, x.ravel() % 2).predict(x).sum())
with open("/workspace/out.txt", "w") as fh:
    fh.write("ok")
"""

BAD = {
    "import socket": "banned_import",
    "import subprocess": "banned_import",
    "import requests": "banned_import",
    "from urllib.request import urlopen": "banned_import",
    "import http.client": "banned_import",
    "import ftplib": "banned_import",
    "import smtplib": "banned_import",
    "import ctypes": "banned_import",
    "import socket as s": "banned_import",
    "from subprocess import run as r": "banned_import",
    "import importlib\nimportlib.import_module('x')": "banned_import",
    "eval('1+1')": "banned_call",
    "exec('x=1')": "banned_call",
    "compile('x', 'f', 'exec')": "banned_call",
    "__import__('os')": "banned_call",
    "import os\nos.system('ls')": "banned_call",
    "import os\nos.popen('ls')": "banned_call",
    "import os as o\no.system('ls')": "banned_call",
    "from os import system as sh\nsh('ls')": "banned_call",
    "import os\ngetattr(os, 'system')('ls')": "banned_call",
    "().__class__.__bases__[0].__subclasses__()": "banned_attribute",
    "f = lambda: 0\nf.__globals__": "banned_attribute",
    "print(__builtins__)": "banned_name",
    "open('/workspace/../etc/passwd')": "hidden_path",
    "open('/etc/passwd')": "hidden_path",
    "open('/tmp/x')": "path_outside_workspace",
    "open('scorer_data/test_labels.parquet')": "hidden_path",
    "import pandas as pd\npd.read_csv('/scorer_data/x.csv')": "hidden_path",
    "p = '/workspace/a'\nopen(p)": "dynamic_open_path",
    "def f(:": "syntax_error",
}


def test_good_training_snippet_is_allowed() -> None:
    r = check_code(GOOD)
    assert r.allowed, r.violations


@pytest.mark.parametrize(("code", "rule"), list(BAD.items()))
def test_every_banned_fixture_is_blocked(code: str, rule: str) -> None:
    r = check_code(code)
    assert not r.allowed
    assert rule in {v.rule for v in r.violations}, r.violations


def test_policy_refusal_happens_before_execution(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    code = f"open({str(marker)!r}, 'w').write('x')\nimport socket"
    with pytest.raises(PolicyRefused):
        run_checked(SubprocessSandbox(), code)
    assert not marker.exists()


def test_subprocess_sandbox_runs_and_isolates_workspace_and_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_SECRET_TOKEN", "hunter2")
    code = (
        "import os, pathlib\n"
        "print('secret=', os.environ.get('FAKE_SECRET_TOKEN'))\n"
        "print(pathlib.Path('in.txt').read_text())\n"
        "print(sorted(p.name for p in pathlib.Path('.').iterdir()))\n"
    )
    res = run_checked(SubprocessSandbox(), code, files={"in.txt": b"hello"})
    assert res.exit_code == 0 and "secret= None" in res.stdout and "hello" in res.stdout
    assert "hunter2" not in res.stdout and res.stdout.strip().endswith("['in.txt']")


def test_fresh_workspace_per_run() -> None:
    sb = SubprocessSandbox()
    run_checked(sb, "open('leftover.txt', 'w').write('x')")
    res = run_checked(sb, "import os\nprint(os.path.exists('leftover.txt'))")
    assert "False" in res.stdout


def test_timeout_kills_the_run() -> None:
    res = run_checked(SubprocessSandbox(), "while True:\n    pass", timeout_s=1.0)
    assert res.timed_out and res.exit_code == -9 and res.duration_s < 10


def test_runtime_error_is_reported_not_raised() -> None:
    res = run_checked(SubprocessSandbox(), "raise ValueError('boom')")
    assert res.exit_code != 0 and "ValueError" in res.stderr


@pytest.mark.parametrize("bad", ["../x", "/abs", "a/../../b", "a\\b", ""])
def test_unsafe_upload_paths_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        safe_relpath(bad)


def test_docker_command_is_locked_down() -> None:
    cmd = LocalDockerBackend().command(Path("/tmp/w"))
    for flag in ("--network", "none", "--read-only", "--cap-drop", "ALL", "--pids-limit"):
        assert flag in cmd
    assert cmd[cmd.index("--user") + 1] == "65534:65534" and "no-new-privileges" in cmd


def test_e2b_is_an_explicit_stub() -> None:
    with pytest.raises(NotImplementedError):
        E2BBackend().run_python("print(1)", 1, {})


def test_package_allow_list() -> None:
    assert package_allowed("LightGBM") and not package_allowed("requests")


async def _mcp_calls(env_extra: dict[str, str]) -> dict[str, object]:
    env = {**os.environ, "PYTHONPATH": str(ROOT), **env_extra}
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_servers.sandbox_exec.server"],
        env=env,
        cwd=str(ROOT),
    )
    out: dict[str, object] = {}
    async with AsyncExitStack() as stack:
        errlog = stack.enter_context(open(os.devnull, "w"))  # noqa: SIM115
        read, write = await stack.enter_async_context(stdio_client(params, errlog=errlog))
        s = await stack.enter_async_context(ClientSession(read, write))
        await s.initialize()
        out["tools"] = sorted(t.name for t in (await s.list_tools()).tools)
        out["ok"] = await s.call_tool(
            "run_python",
            {
                "request": {
                    "code": "print(open('a.txt').read())",
                    "files_b64": {"a.txt": base64.b64encode(b"hi").decode()},
                }
            },
        )
        out["blocked"] = await s.call_tool("run_python", {"request": {"code": "import socket"}})
        out["pkg"] = await s.call_tool("install_allowed", {"request": {"package": "shap"}})
        out["invalid"] = await s.call_tool(
            "run_python", {"request": {"code": "", "timeout_s": 9999}}
        )
    return out


def test_mcp_server_with_local_unsafe_backend() -> None:
    res = asyncio.run(asyncio.wait_for(_mcp_calls({"JMD_SANDBOX": "local-unsafe"}), 120))
    assert res["tools"] == ["check_policy", "install_allowed", "run_python"]
    ok = res["ok"].structured_content  # type: ignore[attr-defined]
    assert ok["allowed"] and "hi" in ok["result"]["stdout"]
    blocked = res["blocked"].structured_content  # type: ignore[attr-defined]
    assert not blocked["allowed"] and "banned_import" in blocked["violations"][0]
    assert res["pkg"].structured_content["allowed"] is True  # type: ignore[attr-defined]
    assert res["invalid"].is_error  # type: ignore[attr-defined]


def test_mcp_server_refuses_without_a_backend() -> None:
    res = asyncio.run(asyncio.wait_for(_mcp_calls({"JMD_SANDBOX": ""}), 120))
    assert res["ok"].is_error  # type: ignore[attr-defined]
    assert not res["blocked"].is_error  # policy refusal needs no backend  # type: ignore[attr-defined]
