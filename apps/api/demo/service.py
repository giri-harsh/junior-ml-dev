"""Demo run service: admission control, a one-at-a-time queue, history cap and cleanup.

Admission (all checked under one lock, so concurrent submits cannot overshoot):
  unknown sample -> 404; this IP already has a queued/running run -> 409; per-IP window and the
  global hourly cap -> 429; queue full -> 429. Execution is a single worker thread that takes jobs
  from `SQLiteJobQueue` (FIFO) and runs each in a child process with a hard wall clock, so a hung
  or runaway run is killed and the next one starts. State is SQLite plus per-run directories.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from apps.api.demo.config import DemoSettings
from apps.api.demo.limits import enforce_demo_config
from apps.api.demo.samples import BY_KEY, Sample, sample_path
from harness.agent.models import RunBudget, RunConfig, RunTask
from harness.queue import SQLiteJobQueue, Worker
from harness.security.ratelimit import RateLimiter

ACTIVE = ("queued", "running")
REPO_ROOT = Path(__file__).resolve().parents[3]


class DemoError(Exception):
    def __init__(self, status: int, detail: str, retry_after: int | None = None) -> None:
        super().__init__(detail)
        self.status, self.detail, self.retry_after = status, detail, retry_after


@dataclass
class DemoJob:
    run_id: str
    run_dir: Path
    config: RunConfig
    max_wall_s: float
    flaml_s: float
    data_dir: Path
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecOutcome:
    status: str  # done | budget_exhausted | degenerate | failed | timeout
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""


Executor = Callable[[DemoJob], ExecOutcome]

_ENV_PASSTHROUGH = (
    "PATH", "SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE",
    "LANG", "LC_ALL", "PYTHONPATH", "VIRTUAL_ENV", "LD_LIBRARY_PATH",
)  # fmt: skip


def base_child_env() -> dict[str, str]:
    """Job-independent part of the run environment (also used by the warm fork server)."""
    env = {k: os.environ[k] for k in _ENV_PASSTHROUGH if k in os.environ}
    env.update(PYTHONUTF8="1", JMD_TRACE="off", DEMO_MODE="1", OMP_NUM_THREADS="2")
    if os.environ.get("DEMO_LEAKAGE_MODE") == "skip":
        env["JMD_LEAKAGE_MODE"] = "skip"  # the leakage detectors are too slow for the free CPU
    if os.environ.get("DEMO_LEAKAGE_S"):  # lowers (never raises) the leakage-detection budget
        env["JMD_LEAKAGE_BUDGET_S"] = os.environ["DEMO_LEAKAGE_S"]
    return env


def child_env(job: DemoJob) -> dict[str, str]:
    """Minimal environment for the run process: no JWT/approval/admin/API secrets reach it."""
    env = base_child_env()
    env.update(
        DATA_TOOLS_ROOTS=str(job.data_dir.resolve()),
        EXPERIMENTS_DIR=str((job.run_dir / "exp").resolve()),
        TRAJECTORY_DIR=str((job.run_dir / "traj").resolve()),
    )  # fmt: skip
    return env


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, check=False, timeout=15,
            )  # fmt: skip
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    proc.kill()


def subprocess_executor(job: DemoJob) -> ExecOutcome:
    """Run the job in a child Python process; kill the whole tree at the hard wall clock."""
    job.run_dir.mkdir(parents=True, exist_ok=True)
    job_file = job.run_dir / "job.json"
    job_file.write_text(
        json.dumps(
            {
                "config": job.config.model_dump(mode="json"), "run_dir": str(job.run_dir),
                "max_wall_s": job.max_wall_s, "flaml_s": job.flaml_s,
            }
        ),
        encoding="utf-8",
    )  # fmt: skip
    cmd = [sys.executable, "-m", "apps.api.demo.run_job", str(job_file)]
    kw: dict[str, Any] = {} if sys.platform == "win32" else {"start_new_session": True}
    with (job.run_dir / "job.log").open("wb") as log:
        proc = subprocess.Popen(  # noqa: S603
            cmd, cwd=REPO_ROOT, env=child_env(job), stdout=log, stderr=subprocess.STDOUT, **kw
        )
        try:
            code = proc.wait(timeout=job.max_wall_s)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            proc.wait(timeout=15)
            return ExecOutcome("timeout", error=f"killed at the {job.max_wall_s:.0f} s wall limit")
    result_file = job.run_dir / "result.json"
    if code != 0 or not result_file.is_file():
        tail = (job.run_dir / "job.log").read_text(encoding="utf-8", errors="replace")[-300:]
        return ExecOutcome("failed", error=f"exit {code}: {tail}")
    result = json.loads(result_file.read_text(encoding="utf-8"))
    return ExecOutcome(str(result.get("status", "failed")), result)


class DemoService:
    def __init__(
        self,
        settings: DemoSettings,
        executor: Executor = subprocess_executor,
        *,
        clock: Callable[[], float] = time.time,
        mono: Callable[[], float] = time.monotonic,
    ) -> None:
        self.s, self.executor, self.clock = settings, executor, clock
        self.state_dir = settings.state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / "demo.db"
        self.runs_dir = self.state_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.ip_limiter = RateLimiter(settings.ip_runs_per_window, settings.ip_window_s, clock=mono)
        self.global_limiter = RateLimiter(settings.global_runs_per_hour, 3600.0, clock=mono)
        self.read_limiter = RateLimiter(settings.read_per_min, 60.0, clock=mono)
        self._lock = threading.Lock()
        self._exec_lock = threading.Lock()  # asserts one execution at a time, whatever calls in
        with closing(self._db()) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS demo_runs (run_id TEXT PRIMARY KEY,"
                " sample TEXT NOT NULL, ip_hash TEXT NOT NULL, status TEXT NOT NULL,"
                " created REAL NOT NULL,"
                " started REAL, finished REAL, error TEXT, summary TEXT)"
            )
        self._recover()
        # a fresh queue file per process: jobs from a dead process are not resumed
        qpath = self.state_dir / "jobs.db"
        for suffix in ("", "-wal", "-shm"):
            Path(str(qpath) + suffix).unlink(missing_ok=True)
        self.queue = SQLiteJobQueue(qpath, max_attempts=1)
        self.worker = Worker(
            self.queue, self._handle, worker_id="demo", lease_s=settings.max_wall_s + 60
        )
        self._thread: threading.Thread | None = None

    # --- storage ------------------------------------------------------------------------------
    def _db(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=30, isolation_level=None)

    def _recover(self) -> None:
        """Runs left queued/running by a previous process can never finish: mark them."""
        with closing(self._db()) as c:
            c.execute(
                "UPDATE demo_runs SET status='interrupted', finished=? WHERE status IN"
                " ('queued','running')",
                (self.clock(),),
            )
        self.cleanup()

    @staticmethod
    def ip_hash(ip: str) -> str:
        return hashlib.sha256(ip.encode()).hexdigest()[:16]  # raw IPs are never stored

    def _row(self, run_id: str) -> dict[str, Any] | None:
        with closing(self._db()) as c:
            r = c.execute(
                "SELECT run_id, sample, status, created, started, finished, error, summary,"
                " ip_hash FROM demo_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
        if r is None:
            return None
        keys = ("run_id", "sample", "status", "created", "started", "finished", "error",
                "summary", "ip_hash")  # fmt: skip
        d = dict(zip(keys, r, strict=True))
        d["summary"] = json.loads(d["summary"]) if d["summary"] else None
        return d

    def _count_active(self, ip_hash: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM demo_runs WHERE status IN ('queued','running')"
        args: tuple[str, ...] = ()
        if ip_hash is not None:
            sql += " AND ip_hash=?"
            args = (ip_hash,)
        with closing(self._db()) as c:
            return int(c.execute(sql, args).fetchone()[0])

    # --- admission ----------------------------------------------------------------------------
    def build_config(self, run_id: str, sample: Sample, data_path: Path) -> RunConfig:
        cfg = RunConfig(
            run_id=run_id,
            task=RunTask(
                name=sample.key, data_path=str(data_path), target=sample.target,
                task_type=sample.task_type,
                metric=sample.metric,
            ),
            budget=RunBudget(
                max_steps=20, max_wall_s=self.s.soft_wall_s, max_tokens=0,
                flaml_budget_s=self.s.flaml_s, tune_trials=3, step_retries=1, selection="cv",
            ),
            planner="scripted", llm_mode="none", deploy=False, sandbox_features=False, mode="dev",
        )  # fmt: skip
        return enforce_demo_config(cfg, max_wall_s=self.s.max_wall_s, flaml_s=self.s.flaml_s)

    def submit(self, sample_key: str, ip: str) -> str:
        sample = BY_KEY.get(sample_key)
        try:
            path = sample_path(self.s.data_dir, sample_key) if sample else None
        except (KeyError, ValueError):
            path = None
        if sample is None or path is None:
            raise DemoError(404, "unknown sample")
        ih = self.ip_hash(ip)
        with self._lock:
            if self._count_active(ih) > 0:
                raise DemoError(409, "you already have a run queued or running", 5)
            if not self.ip_limiter.allow(ih):
                raise DemoError(
                    429, "too many runs from this address, try again later",
                    int(self.ip_limiter.retry_after(ih)) + 1,
                )  # fmt: skip
            if not self.global_limiter.allow("all"):
                raise DemoError(
                    429, "the demo is at its hourly capacity",
                    int(self.global_limiter.retry_after("all")) + 1,
                )  # fmt: skip
            if self._count_active() > self.s.queue_max:  # 1 running + queue_max waiting
                raise DemoError(429, "the demo queue is full, try again shortly", 15)
            run_id = f"demo-{uuid.uuid4().hex[:10]}"
            cfg = self.build_config(run_id, sample, path)
            with closing(self._db()) as c:
                c.execute(
                    "INSERT INTO demo_runs (run_id, sample, ip_hash, status, created)"
                    " VALUES (?,?,?,'queued',?)",
                    (run_id, sample.key, ih, self.clock()),
                )
            self.queue.enqueue(run_id, {"config": cfg.model_dump(mode="json")})
        return run_id

    # --- execution ----------------------------------------------------------------------------
    def _handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        cfg = RunConfig.model_validate(payload["config"])
        run_id = cfg.run_id
        with self._exec_lock:  # belt and braces: the single worker already serialises runs
            with closing(self._db()) as c:
                c.execute(
                    "UPDATE demo_runs SET status='running', started=? WHERE run_id=?",
                    (self.clock(), run_id),
                )
            job = DemoJob(
                run_id,
                self.runs_dir / run_id,
                cfg,
                self.s.max_wall_s,
                self.s.flaml_s,
                self.s.data_dir,
            )
            try:
                out = self.executor(job)
            except Exception as exc:
                out = ExecOutcome("failed", error=f"{type(exc).__name__}: {str(exc)[:200]}")
            self._finish(run_id, out)
        self.cleanup()
        return {}

    def _finish(self, run_id: str, out: ExecOutcome) -> None:
        r = out.result
        summary = None
        if r:
            summary = {
                "status": r.get("status"), "chosen_family": r.get("chosen_family"),
                "val_score": r.get("val_score"), "review": r.get("review"),
                "n_steps": r.get("n_steps"), "latency_s": r.get("latency_s"),
                "dropped": r.get("dropped"), "unresolved": r.get("unresolved"),
                "has_report": bool((r.get("report") or {}).get("html")),
                "report_html": (r.get("report") or {}).get("html"),
            }  # fmt: skip
        status = out.status if out.status in ("timeout", "failed") else "done"
        with closing(self._db()) as c:
            c.execute(
                "UPDATE demo_runs SET status=?, finished=?, error=?, summary=? WHERE run_id=?",
                (status, self.clock(), out.error[:400] or None,
                 json.dumps(summary, default=str) if summary else None, run_id),
            )  # fmt: skip

    def work_once(self) -> bool:
        return self.worker.run_once()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=lambda: self.worker.run_forever(poll_s=0.3, grace_s=1.0),
            name="demo-worker", daemon=True,
        )  # fmt: skip
        self._thread.start()

    def stop(self) -> None:
        self.worker.request_stop()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    # --- reads --------------------------------------------------------------------------------
    def progress(self, run_id: str) -> dict[str, Any] | None:
        """Steps the agent finished so far (tool name + seconds), read from the run's own SQLite
        checkpoints. Public: tool names and timings only, nothing from the data."""
        timeline: dict[str, Any] = {}
        tl = self.runs_dir / run_id / "timeline.json"
        if tl.is_file():
            try:
                raw = json.loads(tl.read_text(encoding="utf-8"))
                timeline = {"child_imports_s": raw.get("imports_s")}
            except (OSError, ValueError):
                timeline = {}
        db = self.runs_dir / run_id / "out" / "agent.db"
        if not db.is_file():
            db = self.runs_dir / run_id / "agent.db"
        if not db.is_file():
            return timeline or None
        try:
            with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1)) as c:
                rows = c.execute("SELECT record FROM checkpoints ORDER BY idx").fetchall()
        except sqlite3.Error:
            return None
        steps = []
        for (raw,) in rows:
            rec = json.loads(raw)
            steps.append((str(rec["step"]["tool"]), round(float(rec.get("latency_s", 0.0)), 1)))
        if not steps:
            return {**timeline, "steps_done": 0}
        return {**timeline, "steps_done": len(steps), "last_step": steps[-1][0], "steps": steps}

    def public_status(self, run_id: str) -> dict[str, Any] | None:
        row = self._row(run_id)
        if row is None:
            return None
        out: dict[str, Any] = {
            "run_id": row["run_id"], "sample": row["sample"], "status": row["status"],
            "created": row["created"], "started": row["started"], "finished": row["finished"],
        }  # fmt: skip
        if row["status"] == "queued":
            with closing(self._db()) as c:
                ahead = c.execute(
                    "SELECT COUNT(*) FROM demo_runs WHERE status IN ('queued','running')"
                    " AND created < ?",
                    (row["created"],),
                ).fetchone()[0]
            out["queue_position"] = int(ahead) + 1
        if row["summary"]:
            s = dict(row["summary"])
            s.pop("report_html", None)
            out["summary"] = s
        if row["status"] in ("failed", "timeout", "interrupted"):
            out["message"] = {
                "timeout": f"stopped at the {self.s.max_wall_s:.0f} s limit",
                "interrupted": "the server restarted before this run finished",
            }.get(row["status"], "the run failed")
        if row["status"] in ("running", "done", "failed", "timeout"):
            prog = self.progress(run_id)
            if prog is not None:
                out["progress"] = prog
        return out

    def report_path(self, run_id: str) -> Path | None:
        row = self._row(run_id)
        if row is None or not row["summary"]:
            return None
        html = row["summary"].get("report_html")
        if not html:
            return None
        p = Path(html).resolve()
        base = self.runs_dir.resolve()
        return p if p.is_file() and p.is_relative_to(base) else None

    def info(self) -> dict[str, Any]:
        return {
            "demo": True,
            "limits": {
                "max_wall_s": self.s.max_wall_s, "flaml_s": self.s.flaml_s,
                "queue_max": self.s.queue_max, "history_cap": self.s.history_cap,
                "ip_runs": self.s.ip_runs_per_window, "ip_window_s": self.s.ip_window_s,
            },
            "active_runs": self._count_active(),
        }  # fmt: skip

    def admin_list(self) -> list[dict[str, Any]]:
        with closing(self._db()) as c:
            rows = c.execute(
                "SELECT run_id, sample, status, created, started, finished, error, ip_hash"
                " FROM demo_runs ORDER BY created DESC LIMIT 200"
            ).fetchall()
        keys = ("run_id", "sample", "status", "created", "started", "finished", "error", "ip_hash")
        return [dict(zip(keys, r, strict=True)) for r in rows]

    # --- history cap --------------------------------------------------------------------------
    def cleanup(self) -> int:
        """Keep at most `history_cap` finished runs younger than the TTL; delete the rest and their
        directories. Active runs are never touched. Orphan directories are removed too."""
        now = self.clock()
        removed = 0
        with closing(self._db()) as c:
            fin = c.execute(
                "SELECT run_id, COALESCE(finished, created) FROM demo_runs"
                " WHERE status NOT IN ('queued','running')"
                " ORDER BY COALESCE(finished, created) DESC"
            ).fetchall()
            drop = [rid for i, (rid, t) in enumerate(fin)
                    if i >= self.s.history_cap or now - t > self.s.history_ttl_s]  # fmt: skip
            for rid in drop:
                c.execute("DELETE FROM demo_runs WHERE run_id=?", (rid,))
                shutil.rmtree(self.runs_dir / rid, ignore_errors=True)
                removed += 1
            known = {r[0] for r in c.execute("SELECT run_id FROM demo_runs")}
        if self.runs_dir.is_dir():
            for d in self.runs_dir.iterdir():
                if d.is_dir() and d.name not in known:
                    shutil.rmtree(d, ignore_errors=True)
        return removed
