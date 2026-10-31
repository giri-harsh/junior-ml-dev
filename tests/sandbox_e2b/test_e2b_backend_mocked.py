"""E2BBackend against a MOCKED SDK: always runs, no network, no key, no `e2b` install needed.

The fake mirrors the e2b 2.62 surface the backend uses (Sandbox.create / .commands.run /
.files.write|list|read / .kill, CommandExitException and TimeoutException by shape). The live
behaviour is tested separately in tests/e2b (marker `e2b`)."""

from __future__ import annotations

import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Any

import pytest

from harness.sandbox import backends
from harness.sandbox.backends import (
    E2B_WORKDIR,
    MAX_OUT_FILE,
    MAX_OUTPUT,
    E2BBackend,
    E2BUnavailable,
    LocalDockerBackend,
    PolicyRefused,
    backend_from_env,
    run_checked,
)


class CommandExitException(Exception):  # same shape as e2b.CommandExitException
    def __init__(self, stdout: str, stderr: str, exit_code: int) -> None:
        super().__init__(f"exit {exit_code}")
        self.stdout, self.stderr, self.exit_code = stdout, stderr, exit_code


class TimeoutException(Exception):  # same name as e2b.TimeoutException
    pass


@dataclass
class Entry:
    name: str
    type: str = "file"
    size: int = 1


@dataclass
class Result:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


@dataclass
class FakeBox:
    behaviour: str = "ok"
    fs: dict[str, bytes] = field(default_factory=dict)
    extra_entries: list[Entry] = field(default_factory=list)
    calls: list[tuple[str, Any]] = field(default_factory=list)
    killed: threading.Event = field(default_factory=threading.Event)
    kill_raises: bool = False
    fail_write: bool = False

    def __post_init__(self) -> None:
        self.commands = self
        self.files = self

    # --- commands
    def run(self, cmd: str, **kw: Any) -> Result:
        self.calls.append(("run", (cmd, kw)))
        if cmd.startswith("mkdir"):
            return Result()
        if self.behaviour == "exit3":
            raise CommandExitException("partial", "boom", 3)
        if self.behaviour == "sdk_timeout":
            raise TimeoutException("deadline")
        if self.behaviour == "hang":
            self.killed.wait(30)  # released by kill(), like a real connection dropping
            raise RuntimeError("sandbox killed")
        if self.behaviour == "big":
            return Result(stdout="x" * (MAX_OUTPUT + 500))
        self.fs[f"{E2B_WORKDIR}/out_a.txt"] = b"A"
        self.fs[f"{E2B_WORKDIR}/notes.txt"] = b"not an output"
        return Result(stdout="hello\n")

    # --- files
    def write(self, path: str, data: bytes, **kw: Any) -> None:
        self.calls.append(("write", path))
        if self.fail_write:
            raise OSError("upload failed")
        self.fs[path] = data

    def list(self, path: str) -> list[Entry]:
        assert path == E2B_WORKDIR
        names = sorted(p.rsplit("/", 1)[1] for p in self.fs if p.count("/") == 2)
        return [Entry(n, size=len(self.fs[f"{E2B_WORKDIR}/{n}"])) for n in names] + (
            self.extra_entries
        )

    def read(self, path: str, format: str = "text", **kw: Any) -> bytes:
        assert format == "bytes"
        return self.fs[path]

    def kill(self) -> bool:
        self.calls.append(("kill", None))
        self.killed.set()
        if self.kill_raises:
            raise RuntimeError("kill failed")
        return True


class FakeSDK:
    def __init__(self, **box_kw: Any) -> None:
        self.box_kw = box_kw
        self.boxes: list[FakeBox] = []
        self.create_kw: list[dict[str, Any]] = []

    def create(self, **kw: Any) -> FakeBox:
        self.create_kw.append(kw)
        box = FakeBox(**self.box_kw)
        self.boxes.append(box)
        return box


def backend(sdk: FakeSDK) -> E2BBackend:
    return E2BBackend(api_key="test-key-not-real", sdk=sdk)


def kinds(box: FakeBox) -> list[str]:
    return [k for k, _ in box.calls]


def test_normal_exec_returns_output_and_only_out_files_and_kills() -> None:
    sdk = FakeSDK()
    r = backend(sdk).run_python("print('hello')", 10, {"train.csv": b"a,b\n1,2\n"})
    assert (r.stdout, r.exit_code, r.timed_out) == ("hello\n", 0, False)
    assert r.files == {"out_a.txt": b"A"}  # notes.txt is not an out_* file
    box = sdk.boxes[0]
    assert box.fs[f"{E2B_WORKDIR}/main.py"] == b"print('hello')"
    assert box.fs[f"{E2B_WORKDIR}/train.csv"] == b"a,b\n1,2\n"
    assert kinds(box)[-1] == "kill" and box.killed.is_set()


def test_sandbox_is_created_with_internet_disabled_and_a_server_side_lifetime() -> None:
    sdk = FakeSDK()
    backend(sdk).run_python("pass", 10, {})
    kw = sdk.create_kw[0]
    assert kw["allow_internet_access"] is False
    assert kw["timeout"] > 10  # server-side expiry outlives the exec timeout
    assert "template" not in kw


def test_template_comes_from_arg_or_env(monkeypatch: pytest.MonkeyPatch) -> None:
    sdk = FakeSDK()
    E2BBackend(api_key="k", template="my-ds", sdk=sdk).run_python("pass", 5, {})
    monkeypatch.setenv("JMD_E2B_TEMPLATE", "from-env")
    E2BBackend(api_key="k", sdk=sdk).run_python("pass", 5, {})
    assert [k["template"] for k in sdk.create_kw] == ["my-ds", "from-env"]


def test_nonzero_exit_is_a_result_not_an_exception() -> None:
    sdk = FakeSDK(behaviour="exit3")
    r = backend(sdk).run_python("raise SystemExit(3)", 10, {})
    assert (r.exit_code, r.stderr, r.stdout, r.timed_out) == (3, "boom", "partial", False)
    assert sdk.boxes[0].killed.is_set()


def test_sdk_side_timeout_is_reported_as_timed_out_and_killed() -> None:
    sdk = FakeSDK(behaviour="sdk_timeout")
    r = backend(sdk).run_python("while True: pass", 4, {})
    assert r.timed_out and r.exit_code == -9 and r.stderr == "timeout" and r.files == {}
    assert sdk.boxes[0].killed.is_set()


def test_hung_sdk_call_is_force_killed_at_the_wall_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backends, "E2B_GRACE_S", 0.2)
    sdk = FakeSDK(behaviour="hang")
    be = backend(sdk)
    r = be.run_python("while True: pass", 0.2, {})
    assert r.timed_out and r.exit_code == -9
    assert sdk.boxes[0].killed.is_set()  # the kill is what releases the blocked call
    assert r.duration_s < 5


def test_kill_runs_when_upload_fails_and_the_original_error_surfaces() -> None:
    sdk = FakeSDK(fail_write=True)
    with pytest.raises(OSError, match="upload failed"):
        backend(sdk).run_python("pass", 10, {})
    assert sdk.boxes[0].killed.is_set()


def test_kill_failure_never_masks_the_result_and_is_counted() -> None:
    sdk = FakeSDK(kill_raises=True)
    be = backend(sdk)
    r = be.run_python("pass", 10, {})
    assert r.exit_code == 0 and be.kill_failures == 1


def test_unsafe_upload_path_is_refused_before_a_sandbox_is_created() -> None:
    sdk = FakeSDK()
    with pytest.raises(ValueError, match="unsafe path"):
        backend(sdk).run_python("pass", 10, {"../evil": b"x"})
    assert sdk.boxes == []


def test_output_is_truncated() -> None:
    r = backend(FakeSDK(behaviour="big")).run_python("pass", 10, {})
    assert len(r.stdout) == MAX_OUTPUT


def test_oversized_and_non_file_outputs_are_not_downloaded() -> None:
    sdk = FakeSDK(
        extra_entries=[
            Entry("out_huge.bin", size=MAX_OUT_FILE + 1),
            Entry("out_dir", type="dir"),
        ]
    )
    r = backend(sdk).run_python("pass", 10, {})
    assert set(r.files) == {"out_a.txt"}


def test_timings_are_recorded_for_the_latency_measurement() -> None:
    be = backend(FakeSDK())
    be.run_python("pass", 10, {})
    assert {"create_s", "upload_s", "exec_s", "download_s", "kill_s"} <= set(be.last_timings)


def test_no_key_means_unavailable_and_nothing_is_created(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    sdk = FakeSDK()
    with pytest.raises(E2BUnavailable):
        E2BBackend(sdk=sdk).run_python("pass", 1, {})
    assert sdk.boxes == []
    # explicit stub contract kept for older callers: it is both NotImplementedError and RuntimeError
    assert issubclass(E2BUnavailable, NotImplementedError)
    assert issubclass(E2BUnavailable, RuntimeError)


def test_missing_sdk_is_unavailable_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "e2b", None)  # `from e2b import ...` -> ImportError
    with pytest.raises(E2BUnavailable, match="not installed"):
        E2BBackend(api_key="k").run_python("pass", 1, {})


def test_package_imports_without_the_e2b_sdk() -> None:
    code = (
        "import sys; sys.modules['e2b'] = None\n"
        "import harness.sandbox.backends as b\n"
        "assert b.E2BBackend.name == 'e2b'\n"
    )
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def test_backend_from_env_selects_e2b(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JMD_SANDBOX", "e2b")
    assert isinstance(backend_from_env(), E2BBackend)
    monkeypatch.setenv("JMD_SANDBOX", "docker")
    assert isinstance(backend_from_env(), LocalDockerBackend)


def test_policy_still_runs_first_through_run_checked() -> None:
    sdk = FakeSDK()
    with pytest.raises(PolicyRefused):
        run_checked(backend(sdk), "import socket", 5)
    assert sdk.boxes == []  # a refused program never costs a sandbox
    r = run_checked(backend(sdk), "print('hello')", 5)
    assert r.stdout == "hello\n" and len(sdk.boxes) == 1
