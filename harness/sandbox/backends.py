"""Sandbox backends behind one interface.

- SubprocessSandbox: dev/test only. NOT an isolation boundary (same user, same network).
- LocalDockerBackend: builds a locked-down `docker run` command (network none, read-only root,
  non-root, cpu/mem/pid caps). Execution needs Docker: NOT RUN here.
- E2BBackend: one fresh E2B microVM per exec (internet disabled at creation), always killed in a
  `finally`. Needs the optional `e2b` SDK (imported lazily) and E2B_API_KEY. Unit tests use a
  mocked SDK; the live suite is tests/e2b (marker `e2b`).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from harness.policies.code_policy import PolicyResult, check_code
from harness.sandbox import winjob

ALLOWED_PACKAGES = {
    "scikit-learn", "lightgbm", "xgboost", "catboost", "optuna", "shap", "scipy", "pandas", "numpy",
}  # fmt: skip
MAX_OUTPUT = 100_000


class ExecResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    duration_s: float
    files: dict[str, bytes] = {}  # workspace files named out_* written by the code (<= 50 MB each)


class PolicyRefused(RuntimeError):
    def __init__(self, result: PolicyResult) -> None:
        super().__init__("; ".join(f"{v.rule}@{v.line}: {v.detail}" for v in result.violations))
        self.result = result


class SandboxBackend(Protocol):
    name: str

    def run_python(self, code: str, timeout_s: float, files: dict[str, bytes]) -> ExecResult: ...


def run_checked(
    backend: SandboxBackend,
    code: str,
    timeout_s: float = 30.0,
    files: dict[str, bytes] | None = None,
) -> ExecResult:
    """Policy first, then a fresh sandbox run. The only entry point agents should use."""
    policy = check_code(code)
    if not policy.allowed:
        raise PolicyRefused(policy)
    return backend.run_python(code, min(timeout_s, 300.0), files or {})


MAX_OUT_FILE = 50 * 1024 * 1024
# tmpfs path INSIDE the container, not a host path
_CONTAINER_TMP = "/tmp:rw,size=64m"  # nosec B108


def collect_outputs(work: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for p in sorted(work.glob("out_*")):
        if p.is_file() and p.stat().st_size <= MAX_OUT_FILE:
            out[p.name] = p.read_bytes()
    return out


def safe_relpath(rel: str) -> str:
    """Relative, forward-slash path without traversal (also rejects rooted paths on Windows)."""
    p = PurePosixPath(rel)
    if (
        not rel
        or rel.startswith(("/", "\\"))
        or "\\" in rel
        or ":" in rel
        or p.is_absolute()
        or ".." in p.parts
    ):
        raise ValueError(f"unsafe path: {rel!r}")
    return rel


class SubprocessSandbox:
    """Fresh temp workspace per run, scrubbed environment, hard timeout. Dev/test only."""

    name = "subprocess-UNISOLATED"  # Windows job limits reduce blast radius; still not isolation

    def run_python(self, code: str, timeout_s: float, files: dict[str, bytes]) -> ExecResult:
        work = Path(tempfile.mkdtemp(prefix="jmd-sbx-"))
        try:
            for rel, data in files.items():
                target = work / safe_relpath(rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            env = {
                "PATH": os.environ.get("PATH", ""),
                "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
                "PYTHONHASHSEED": "0",
            }
            t0 = time.perf_counter()
            proc = subprocess.Popen(
                [sys.executable, "-I", "-c", code],
                cwd=work,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            job = winjob.assign(proc)  # Windows: memory + process-count limits, kill-on-close
            try:
                out, err = proc.communicate(timeout=timeout_s)
                rc, timed_out = proc.returncode, False
            except subprocess.TimeoutExpired:
                if job:
                    job.terminate()  # kills the whole tree, not just the direct child
                proc.kill()
                out, _ = proc.communicate()
                err, rc, timed_out = "timeout", -9, True
            finally:
                if job:
                    job.close()
            return ExecResult(
                stdout=out[:MAX_OUTPUT],
                stderr=err[:MAX_OUTPUT],
                exit_code=rc,
                timed_out=timed_out,
                duration_s=round(time.perf_counter() - t0, 3),
                files=collect_outputs(work),
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)


class LocalDockerBackend:
    name = "local-docker"

    def __init__(
        self, image: str = "jmd-sandbox:latest", cpus: float = 1.0, memory: str = "1g"
    ) -> None:
        self.image, self.cpus, self.memory = image, cpus, memory

    def command(self, workspace: Path, name: str = "") -> list[str]:
        named = ["--name", name] if name else []
        return [
            "docker", "run", "--rm", *named, "--network", "none", "--read-only",
            "--user", "65534:65534", "--cpus", str(self.cpus), "--memory", self.memory,
            "--pids-limit", "128", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--tmpfs", _CONTAINER_TMP, "-v", f"{workspace}:/workspace:rw", "-w", "/workspace",
            self.image, "python", "-I", "/workspace/main.py",
        ]  # fmt: skip

    def run_python(self, code: str, timeout_s: float, files: dict[str, bytes]) -> ExecResult:
        if shutil.which("docker") is None:
            raise RuntimeError("docker not available: LocalDockerBackend NOT RUN (see KNOWN_GAPS)")
        work = Path(tempfile.mkdtemp(prefix="jmd-docker-"))
        name = f"jmd-sbx-{uuid.uuid4().hex[:12]}"
        try:
            work.chmod(0o777)  # the container runs as uid 65534, not as the host user
            (work / "main.py").write_text(code, encoding="utf-8")
            for rel, data in files.items():
                target = work / safe_relpath(rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                target.chmod(0o644)
            t0 = time.perf_counter()
            try:
                p = subprocess.run(
                    self.command(work, name), capture_output=True, text=True, timeout=timeout_s
                )
                return ExecResult(
                    stdout=p.stdout[:MAX_OUTPUT], stderr=p.stderr[:MAX_OUTPUT],
                    exit_code=p.returncode, timed_out=False,
                    duration_s=round(time.perf_counter() - t0, 3), files=collect_outputs(work),
                )  # fmt: skip
            except subprocess.TimeoutExpired:
                # killing the docker CLI would leave the container running: kill it by name
                subprocess.run(["docker", "kill", name], capture_output=True, timeout=30)
                return ExecResult(
                    stdout="", stderr="timeout", exit_code=-9, timed_out=True,
                    duration_s=round(time.perf_counter() - t0, 3),
                )  # fmt: skip
        finally:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)
            shutil.rmtree(work, ignore_errors=True)


class E2BUnavailable(NotImplementedError, RuntimeError):
    """E2B cannot be used here: SDK not installed or E2B_API_KEY not set. Nothing was run."""


_log = logging.getLogger(__name__)
E2B_WORKDIR = "/workspace"  # same path as the Docker backend, so agent code is portable
E2B_LIFETIME_MARGIN_S = 30  # server-side expiry = timeout + margin: bounds cost if our kill fails
E2B_GRACE_S = 5.0  # extra wall-clock allowed past the command timeout before the force-kill


def _load_e2b_sdk() -> Any:
    try:
        from e2b import Sandbox  # lazy: the package must import without the optional SDK
    except ImportError as e:
        raise E2BUnavailable("e2b SDK not installed (pip install 'e2b>=2.62,<3')") from e
    return Sandbox


def _entry_is_file(entry: Any) -> bool:
    kind = getattr(entry, "type", None)
    return str(getattr(kind, "value", kind)).lower() == "file"


class E2BBackend:
    """One fresh E2B sandbox per exec. Internet is disabled at creation (`allow_internet_access`).

    Lifecycle per call: create -> upload main.py + the given files -> run with a wall-clock limit
    -> download top-level `out_*` files -> kill (in `finally`, also on timeout and on any error).
    If the SDK call hangs past timeout + grace, the sandbox is killed from this thread, which
    breaks the blocked call; the sandbox also expires server-side after timeout + margin.
    `sdk` (a Sandbox-like class with `.create(**kw)`) is injectable for the mocked unit tests.
    """

    name = "e2b"

    def __init__(
        self,
        api_key: str | None = None,
        template: str | None = None,
        sdk: Any = None,
        python: str = "python3",
    ) -> None:
        self._api_key = api_key
        self.template = template or os.environ.get("JMD_E2B_TEMPLATE") or None
        self._sdk = sdk
        self.python = python
        self.last_timings: dict[str, float] = {}  # create_s/upload_s/exec_s/download_s/kill_s
        self.kill_failures = 0

    def run_python(self, code: str, timeout_s: float, files: dict[str, bytes]) -> ExecResult:
        key = self._api_key or os.environ.get("E2B_API_KEY", "")
        if not key:
            raise E2BUnavailable("E2B_API_KEY not set: E2BBackend NOT RUN")
        uploads = {safe_relpath(rel): data for rel, data in files.items()}  # before any spend
        sdk = self._sdk if self._sdk is not None else _load_e2b_sdk()
        timings: dict[str, float] = {}
        t0 = time.perf_counter()
        kw: dict[str, Any] = {
            "timeout": int(timeout_s) + E2B_LIFETIME_MARGIN_S,
            "allow_internet_access": False,
            "metadata": {"app": "junior-ml-dev"},
            "api_key": key,
            "request_timeout": 60.0,
        }
        if self.template:
            kw["template"] = self.template
        box = sdk.create(**kw)
        timings["create_s"] = round(time.perf_counter() - t0, 3)
        pool: ThreadPoolExecutor | None = None
        try:
            t1 = time.perf_counter()
            box.commands.run(
                f"mkdir -p {E2B_WORKDIR} && chown $(id -u user):$(id -g user) {E2B_WORKDIR}",
                user="root", timeout=30, request_timeout=30,
            )  # fmt: skip
            box.files.write(f"{E2B_WORKDIR}/main.py", code.encode("utf-8"), request_timeout=60)
            for rel, data in uploads.items():
                box.files.write(f"{E2B_WORKDIR}/{rel}", data, request_timeout=120)
            timings["upload_s"] = round(time.perf_counter() - t1, 3)

            t2 = time.perf_counter()
            pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jmd-e2b")
            fut = pool.submit(self._exec, box, timeout_s)
            try:
                stdout, stderr, rc = fut.result(timeout=timeout_s + E2B_GRACE_S)
            except FutureTimeout:
                stdout, stderr, rc = "", "timeout", -9
            timed_out = rc == -9 and stderr == "timeout"
            timings["exec_s"] = round(time.perf_counter() - t2, 3)

            out_files: dict[str, bytes] = {}
            if not timed_out:
                t3 = time.perf_counter()
                out_files = self._download(box)
                timings["download_s"] = round(time.perf_counter() - t3, 3)
            return ExecResult(
                stdout=stdout[:MAX_OUTPUT], stderr=stderr[:MAX_OUTPUT], exit_code=rc,
                timed_out=timed_out, duration_s=round(time.perf_counter() - t0, 3),
                files=out_files,
            )  # fmt: skip
        finally:
            t4 = time.perf_counter()
            try:
                box.kill()
            except Exception:  # noqa: BLE001 - never mask the result; server-side expiry bounds it
                self.kill_failures += 1
                _log.warning("e2b sandbox kill failed (it will expire server-side)")
            timings["kill_s"] = round(time.perf_counter() - t4, 3)
            self.last_timings = timings
            if pool is not None:
                pool.shutdown(wait=False, cancel_futures=True)

    def _exec(self, box: Any, timeout_s: float) -> tuple[str, str, int]:
        try:
            r = box.commands.run(
                f"{self.python} main.py", cwd=E2B_WORKDIR, timeout=timeout_s, request_timeout=30
            )
        except Exception as e:  # noqa: BLE001 - classified by shape: the SDK is imported lazily
            if type(e).__name__ == "TimeoutException":
                return "", "timeout", -9
            if hasattr(e, "exit_code"):  # CommandExitException: a non-zero exit is a result
                return (
                    str(getattr(e, "stdout", "") or ""),
                    str(getattr(e, "stderr", "") or ""),
                    int(e.exit_code),
                )
            raise
        return str(r.stdout or ""), str(r.stderr or ""), int(r.exit_code)

    def _download(self, box: Any) -> dict[str, bytes]:
        out: dict[str, bytes] = {}
        for entry in sorted(box.files.list(E2B_WORKDIR), key=lambda e: str(e.name)):
            name = str(entry.name)
            size = getattr(entry, "size", 0) or 0
            if _entry_is_file(entry) and name.startswith("out_") and size <= MAX_OUT_FILE:
                out[name] = bytes(box.files.read(f"{E2B_WORKDIR}/{name}", format="bytes"))
        return out


def backend_from_env() -> SandboxBackend:
    """JMD_SANDBOX=docker | e2b | local-unsafe (subprocess; NOT isolation). Unset: refuse."""
    choice = os.environ.get("JMD_SANDBOX", "")
    if choice == "docker":
        return LocalDockerBackend()
    if choice == "e2b":
        return E2BBackend()
    if choice == "local-unsafe":
        return SubprocessSandbox()
    raise RuntimeError("no sandbox backend configured: set JMD_SANDBOX=docker (or e2b)")


def package_allowed(pkg: str) -> bool:
    return pkg.strip().lower() in ALLOWED_PACKAGES
