"""Sandbox backend logic that needs neither Docker nor E2B: output collection, the docker run
lifecycle against a recording stand-in for the `docker` CLI, SDK loading and backend selection."""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from harness.sandbox import backends
from harness.sandbox.backends import (
    MAX_OUT_FILE,
    E2BBackend,
    E2BUnavailable,
    LocalDockerBackend,
    SubprocessSandbox,
    backend_from_env,
    collect_outputs,
    package_allowed,
)


def test_collect_outputs_takes_only_regular_out_files_within_the_size_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "out_b.txt").write_bytes(b"bb")
    (tmp_path / "out_a.bin").write_bytes(b"a")
    (tmp_path / "other.txt").write_bytes(b"ignored")
    (tmp_path / "out_dir").mkdir()  # a directory named out_* is not a file
    (tmp_path / "out_big.bin").write_bytes(b"x" * 20)
    monkeypatch.setattr(backends, "MAX_OUT_FILE", 10)
    got = collect_outputs(tmp_path)
    assert got == {"out_a.bin": b"a", "out_b.txt": b"bb"}
    assert list(got) == ["out_a.bin", "out_b.txt"]  # sorted
    assert MAX_OUT_FILE == 50 * 1024 * 1024


def test_subprocess_sandbox_returns_stdout_and_out_files_and_cleans_up() -> None:
    code = "import os\nprint('hi')\nopen('out_x.txt','w').write(open('in.txt').read()+'!')\n"
    r = SubprocessSandbox().run_python(code, 20, {"in.txt": b"data"})
    assert r.exit_code == 0 and not r.timed_out
    assert r.stdout.strip() == "hi"
    assert r.files == {"out_x.txt": b"data!"}


def test_subprocess_sandbox_rejects_traversal_in_uploaded_names() -> None:
    with pytest.raises(ValueError, match="unsafe path"):
        SubprocessSandbox().run_python("pass", 5, {"../evil.py": b"x"})


# --- LocalDockerBackend against a fake `docker` CLI -------------------------------------------------
class FakeDocker:
    """Records every `subprocess.run` call the backend makes and plays the docker CLI."""

    def __init__(self, *, timeout: bool = False, rc: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.timeout, self.rc = timeout, rc
        self.workspace: Path | None = None

    def __call__(self, cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        if cmd[:2] == ["docker", "run"]:
            mount = cmd[cmd.index("-v") + 1]
            self.workspace = Path(mount.rsplit(":/workspace", 1)[0])
            assert (self.workspace / "main.py").read_text(encoding="utf-8") == "print(1)"
            if self.timeout:
                raise subprocess.TimeoutExpired(cmd, kw["timeout"])
            (self.workspace / "out_result.txt").write_bytes(b"done")
            return subprocess.CompletedProcess(cmd, self.rc, stdout="o" * 5, stderr="e")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def test_docker_command_is_locked_down(tmp_path: Path) -> None:
    cmd = LocalDockerBackend(image="img:1", cpus=2.0, memory="512m").command(tmp_path, "nm")
    assert cmd[:6] == ["docker", "run", "--rm", "--name", "nm", "--network"]
    assert cmd[cmd.index("--network") + 1] == "none"
    assert "--read-only" in cmd
    assert cmd[cmd.index("--user") + 1] == "65534:65534"
    assert cmd[cmd.index("--cpus") + 1] == "2.0" and cmd[cmd.index("--memory") + 1] == "512m"
    assert cmd[cmd.index("--cap-drop") + 1] == "ALL"
    assert cmd[cmd.index("--security-opt") + 1] == "no-new-privileges"
    assert cmd[-4:] == ["img:1", "python", "-I", "/workspace/main.py"]
    assert "--name" not in LocalDockerBackend().command(tmp_path)  # unnamed when no name given


def test_docker_not_installed_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backends.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="docker not available"):
        LocalDockerBackend().run_python("pass", 5, {})


def test_docker_run_collects_output_and_always_removes_the_container_and_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeDocker()
    monkeypatch.setattr(backends.shutil, "which", lambda _: "docker")
    monkeypatch.setattr(backends.subprocess, "run", fake)
    r = LocalDockerBackend().run_python("print(1)", 12, {"data/in.csv": b"1,2"})
    assert (r.exit_code, r.timed_out, r.stdout, r.stderr) == (0, False, "ooooo", "e")
    assert r.files == {"out_result.txt": b"done"}
    run_cmd, rm_cmd = fake.calls
    name = run_cmd[run_cmd.index("--name") + 1]
    assert name.startswith("jmd-sbx-") and rm_cmd == ["docker", "rm", "-f", name]
    assert fake.workspace is not None and not fake.workspace.exists()


def test_docker_nonzero_exit_is_a_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backends.shutil, "which", lambda _: "docker")
    monkeypatch.setattr(backends.subprocess, "run", FakeDocker(rc=7))
    r = LocalDockerBackend().run_python("print(1)", 12, {})
    assert r.exit_code == 7 and not r.timed_out


def test_docker_timeout_kills_the_container_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeDocker(timeout=True)
    monkeypatch.setattr(backends.shutil, "which", lambda _: "docker")
    monkeypatch.setattr(backends.subprocess, "run", fake)
    r = LocalDockerBackend().run_python("print(1)", 3, {})
    assert (r.timed_out, r.exit_code, r.stderr, r.files) == (True, -9, "timeout", {})
    run_cmd, kill_cmd, rm_cmd = fake.calls
    name = run_cmd[run_cmd.index("--name") + 1]
    assert kill_cmd == ["docker", "kill", name] and rm_cmd == ["docker", "rm", "-f", name]


def test_docker_refuses_unsafe_upload_names_but_still_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeDocker()
    monkeypatch.setattr(backends.shutil, "which", lambda _: "docker")
    monkeypatch.setattr(backends.subprocess, "run", fake)
    with pytest.raises(ValueError, match="unsafe path"):
        LocalDockerBackend().run_python("print(1)", 3, {"/abs/path": b"x"})
    assert [c[:3] for c in fake.calls] == [["docker", "rm", "-f"]]  # never started a container


# --- E2B SDK loading and backend selection -----------------------------------------------------------
def test_load_e2b_sdk_returns_the_sandbox_class(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = types.ModuleType("e2b")
    mod.Sandbox = type("Sandbox", (), {})  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "e2b", mod)
    assert backends._load_e2b_sdk() is mod.Sandbox  # type: ignore[attr-defined]


def test_load_e2b_sdk_without_the_package_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "e2b", None)  # makes `from e2b import ...` raise ImportError
    with pytest.raises(E2BUnavailable, match="not installed"):
        backends._load_e2b_sdk()


@pytest.mark.parametrize(
    ("choice", "cls"),
    [("docker", LocalDockerBackend), ("e2b", E2BBackend), ("local-unsafe", SubprocessSandbox)],
)
def test_backend_from_env_picks_the_configured_backend(
    monkeypatch: pytest.MonkeyPatch, choice: str, cls: type
) -> None:
    monkeypatch.setenv("JMD_SANDBOX", choice)
    be = backend_from_env()
    assert type(be) is cls


@pytest.mark.parametrize("choice", ["", "firecracker"])
def test_backend_from_env_refuses_when_unset_or_unknown(
    monkeypatch: pytest.MonkeyPatch, choice: str
) -> None:
    monkeypatch.setenv("JMD_SANDBOX", choice)
    with pytest.raises(RuntimeError, match="no sandbox backend configured"):
        backend_from_env()


def test_only_whitelisted_packages_are_allowed() -> None:
    assert package_allowed(" Scikit-Learn ")
    assert package_allowed("lightgbm")
    assert not package_allowed("requests")
    assert not package_allowed("")
