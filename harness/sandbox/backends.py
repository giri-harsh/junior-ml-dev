"""Sandbox backends behind one interface.

- SubprocessSandbox: dev/test only. NOT an isolation boundary (same user, same network).
- LocalDockerBackend: builds a locked-down `docker run` command (network none, read-only root,
  non-root, cpu/mem/pid caps). Execution needs Docker: NOT RUN here.
- E2BBackend: STUB. Needs the e2b SDK and E2B_API_KEY.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Protocol

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


class E2BBackend:
    """STUB: wire the e2b SDK here (internet disabled at sandbox creation). NOT RUN."""

    name = "e2b"

    def run_python(self, code: str, timeout_s: float, files: dict[str, bytes]) -> ExecResult:
        raise NotImplementedError("E2BBackend is a STUB: needs the e2b SDK and E2B_API_KEY")


def backend_from_env() -> SandboxBackend:
    """JMD_SANDBOX=docker | local-unsafe (subprocess; NOT isolation). Unset: refuse."""
    choice = os.environ.get("JMD_SANDBOX", "")
    if choice == "docker":
        return LocalDockerBackend()
    if choice == "local-unsafe":
        return SubprocessSandbox()
    raise RuntimeError("no sandbox backend configured: set JMD_SANDBOX=docker")


def package_allowed(pkg: str) -> bool:
    return pkg.strip().lower() in ALLOWED_PACKAGES
