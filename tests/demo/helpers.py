"""Shared builders for the demo tests: synthetic samples, a fresh app, a fake executor."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI

from apps.api.demo.config import DemoSettings
from apps.api.demo.prepare import prepare_samples
from apps.api.demo.service import DemoJob, ExecOutcome
from apps.api.routes.admin import router as admin_router
from apps.api.routes.datasets import router as datasets_router
from apps.api.routes.runs import router as runs_router


def make_raw_samples(raw: Path, n: int = 300) -> None:
    """Tiny stand-ins named like the real samples, in the shape OpenML returns them."""
    rng = np.random.default_rng(1)
    raw.mkdir(parents=True, exist_ok=True)
    a, b = rng.normal(size=n), rng.normal(size=n)
    pos = (a + 0.5 * b + rng.normal(scale=0.6, size=n)) > 0
    pd.DataFrame(
        {"a": a, "b": b, "class": np.where(pos, "tested_positive", "tested_negative")}
    ).to_csv(raw / "diabetes.csv", index=False)
    pd.DataFrame(
        {
            "a": a,
            "b": b,
            "cat": rng.choice(["u", "v", "w"], n),
            "class": np.where(pos, "bad", "good"),
        }
    ).to_csv(raw / "credit-g.csv", index=False)
    pd.DataFrame({"a": a, "b": b, "class": a * 2 + b + rng.normal(scale=0.2, size=n)}).to_csv(
        raw / "wine-quality.csv", index=False
    )


def make_settings(tmp: Path, **kw: object) -> DemoSettings:
    base = DemoSettings(
        data_dir=tmp / "samples", state_dir=tmp / "state", site_dir=tmp / "site",
        max_wall_s=90.0, soft_wall_s=55.0, flaml_s=15.0, queue_max=3, history_cap=20,
        history_ttl_s=3600.0, ip_runs_per_window=50, ip_window_s=600.0,
        global_runs_per_hour=500, read_per_min=10_000, proxy_hops=1,
    )  # fmt: skip
    from dataclasses import replace

    return replace(base, **kw)  # type: ignore[arg-type]


def make_samples(tmp: Path) -> Path:
    raw = tmp / "raw"
    make_raw_samples(raw)
    prepare_samples(tmp / "samples", from_dir=raw)
    return tmp / "samples"


def fresh_app() -> FastAPI:
    """The same routers `apps.api.main` includes, on a throw-away app (never mutate the real one)."""
    app = FastAPI()
    app.include_router(datasets_router)
    app.include_router(admin_router)
    app.include_router(runs_router)
    return app


class FakeExecutor:
    """Stands in for the child process; records how many executions overlap."""

    def __init__(self, delay: float = 0.0, status: str = "done") -> None:
        self.delay, self.status = delay, status
        self.current = 0
        self.peak = 0
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, job: DemoJob) -> ExecOutcome:
        with self._lock:
            self.current += 1
            self.peak = max(self.peak, self.current)
            self.calls.append(job.run_id)
        try:
            time.sleep(self.delay)
            out = job.run_dir / "out" / job.run_id
            out.mkdir(parents=True, exist_ok=True)
            html = out / "report.html"
            html.write_text("<html><body>planner=scripted report</body></html>", encoding="utf-8")
            result = {
                "status": "done", "chosen_family": "linear", "val_score": 0.9, "review": "APPROVE",
                "n_steps": 5, "latency_s": 1.0, "dropped": [], "unresolved": [],
                "report": {"html": str(html)},
            }  # fmt: skip
            return ExecOutcome(self.status, result)
        finally:
            with self._lock:
                self.current -= 1


def wait_until(pred: object, timeout: float = 15.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if pred():  # type: ignore[operator]
            return True
        time.sleep(0.02)
    return False
