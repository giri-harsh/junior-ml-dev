"""Windows job-object limits for the subprocess sandbox. These run the sandbox backend directly
(bypassing the code policy on purpose) to prove the OS-level limits hold even if the policy fails.
Skipped on non-Windows platforms (an environment limit, not a logic skip)."""

from __future__ import annotations

import os
import sys

import pytest

from harness.sandbox.backends import SubprocessSandbox

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows job objects")


def test_normal_code_still_runs() -> None:
    r = SubprocessSandbox().run_python("print(sum(range(10)))", 20, {})
    assert r.exit_code == 0 and r.stdout.strip() == "45" and not r.timed_out


def test_memory_bomb_is_stopped() -> None:
    r = SubprocessSandbox().run_python("x = bytearray(6 * 1024**3); print('allocated')", 30, {})
    assert "allocated" not in r.stdout and r.exit_code != 0


def test_child_process_spawn_is_blocked() -> None:
    code = (
        "import subprocess, sys\n"
        f"p = subprocess.run([r'{sys.executable}', '-c', 'print(1)'], capture_output=True)\n"
        "print('spawned', p.returncode)\n"
    )
    r = SubprocessSandbox().run_python(code, 30, {})
    assert "spawned 0" not in r.stdout


def test_timeout_kills_the_tree() -> None:
    r = SubprocessSandbox().run_python("import time\nwhile True: time.sleep(0.1)", 2, {})
    assert r.timed_out and r.exit_code == -9 and r.duration_s < 15
