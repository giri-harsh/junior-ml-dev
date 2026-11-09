"""Web-side executor that talks to the warm fork server (`apps.api.demo.zygote`).

Same contract as `service.subprocess_executor` (job in, `ExecOutcome` out, the run is killed at the
hard wall clock), but the heavy imports happen once, in the zygote, not once per run. The time the
zygote needs to become ready is NOT part of a run's wall clock: a run waits for it while 'running'.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from apps.api.demo.service import REPO_ROOT, DemoJob, ExecOutcome, base_child_env


def _killpg(pid: int) -> None:
    if sys.platform == "win32":
        return
    with contextlib.suppress(OSError):
        os.killpg(pid, signal.SIGKILL)


class ZygoteExecutor:
    def __init__(
        self,
        cmd: list[str] | None = None,
        *,
        ready_timeout_s: float = 240.0,
        kill: Callable[[int], None] = _killpg,
    ) -> None:
        self.cmd = cmd or [sys.executable, "-m", "apps.api.demo.zygote"]
        self.ready_timeout_s = ready_timeout_s
        self._kill = kill
        self._lock = threading.Lock()  # one run at a time, and one spawner
        self._proc: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str] = queue.Queue()
        self._ready = threading.Event()
        self.imports_s: float | None = None

    # --- lifecycle ----------------------------------------------------------------------------
    def warm(self) -> None:
        """Start the zygote now (called at web start-up so the first visitor does not wait)."""
        with self._lock:
            self._ensure()

    def _ensure(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        self._ready.clear()
        self._lines = queue.Queue()
        self._proc = subprocess.Popen(  # noqa: S603
            self.cmd, cwd=REPO_ROOT, env=base_child_env(), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )  # fmt: skip
        threading.Thread(target=self._pump, args=(self._proc, self._lines), daemon=True).start()

    def _pump(self, proc: subprocess.Popen[str], lines: queue.Queue[str]) -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.strip()
            if line.startswith("ready"):
                for part in line.split():
                    if part.startswith("imports_s="):
                        self.imports_s = float(part.split("=", 1)[1])
                self._ready.set()
            else:
                lines.put(line)
        lines.put("eof")

    def close(self) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                self._proc.kill()
            self._proc = None

    # --- one job ------------------------------------------------------------------------------
    def __call__(self, job: DemoJob) -> ExecOutcome:
        with self._lock:
            self._ensure()
            if not self._ready.wait(self.ready_timeout_s):
                return ExecOutcome("failed", error="the run worker did not start in time")
            job.run_dir.mkdir(parents=True, exist_ok=True)
            job_file = job.run_dir / "job.json"
            job_file.write_text(
                json.dumps(
                    {
                        "config": job.config.model_dump(mode="json"), "run_dir": str(job.run_dir),
                        "max_wall_s": job.max_wall_s, "flaml_s": job.flaml_s,
                        "data_dir": str(job.data_dir.resolve()),
                    }
                ),
                encoding="utf-8",
            )  # fmt: skip
            assert self._proc is not None and self._proc.stdin is not None
            try:
                self._proc.stdin.write(str(job_file) + "\n")
                self._proc.stdin.flush()
            except OSError:
                self._proc = None
                return ExecOutcome("failed", error="the run worker is not available")
            return self._await(job)

    def _await(self, job: DemoJob) -> ExecOutcome:
        pid = -1
        t0 = time.monotonic()
        while True:
            left = max(0.1, job.max_wall_s - (time.monotonic() - t0))
            try:
                msg = self._lines.get(timeout=left)
            except queue.Empty:
                if pid > 0:
                    self._kill(pid)
                    self._drain_done(10.0)
                return ExecOutcome(
                    "timeout", error=f"killed at the {job.max_wall_s:.0f} s wall limit"
                )
            if msg == "eof":
                self._proc = None
                return ExecOutcome("failed", error="the run worker exited")
            if msg.startswith("started "):
                pid = int(msg.split()[1])
            elif msg.startswith("done "):
                return self._outcome(job, int(msg.split()[2]))

    def _drain_done(self, timeout_s: float) -> None:
        with contextlib.suppress(queue.Empty):
            while not self._lines.get(timeout=timeout_s).startswith(("done ", "eof")):
                pass

    def _outcome(self, job: DemoJob, code: int) -> ExecOutcome:
        result_file = job.run_dir / "result.json"
        if code != 0 or not result_file.is_file():
            log = job.run_dir / "job.log"
            tail = log.read_text(encoding="utf-8", errors="replace")[-300:] if log.is_file() else ""
            return ExecOutcome("failed", error=f"exit {code}: {tail}")
        result: dict[str, Any] = json.loads(result_file.read_text(encoding="utf-8"))
        return ExecOutcome(str(result.get("status", "failed")), result)
