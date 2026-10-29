"""Agent runs: submit (admin), status, report, and Prometheus-style metrics.

Runs are queued in SQLite and executed by a worker (`execute_job`); a worker thread starts on app
startup only when JMD_WORKER=1, so tests and one-shot CLIs drive it explicitly.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from apps.api.routes.admin import approval_store, audit_log, require_admin
from apps.api.routes.datasets import get_store
from harness.agent.models import RunBudget, RunConfig, RunTask
from harness.agent.planners import ScriptedPlanner
from harness.agent.runner import AgentRunner
from harness.agent.sql_store import SqlRunStore, open_run_store
from harness.agent.store import RunStore
from harness.obs import render_metrics
from harness.queue import SQLiteJobQueue, Worker
from harness.queue_arq import ArqJobQueue
from harness.security.approvals import ApprovalStore
from harness.security.ratelimit import RateLimiter

router = APIRouter(tags=["runs"])
# per admin session: 10 run submissions/resumes per minute (RUNS_RATE_PER_MIN overrides)
limiter = RateLimiter(int(os.environ.get("RUNS_RATE_PER_MIN", "10")), 60.0)


def rate_limited(admin: str = Depends(require_admin)) -> str:
    if not limiter.allow(admin):
        raise HTTPException(
            429,
            "too many run submissions",
            headers={"Retry-After": str(int(limiter.retry_after(admin)) + 1)},
        )
    return admin


def _path(env: str, default: str) -> str:
    return os.environ.get(env, default)


def run_store() -> RunStore | SqlRunStore:
    return open_run_store(_path("RUNS_DB", "data/runs.db"))


def job_queue() -> SQLiteJobQueue | ArqJobQueue:
    if os.environ.get("QUEUE_BACKEND") == "arq":
        return ArqJobQueue()
    return SQLiteJobQueue(_path("JOBS_DB", "data/jobs.db"))


class RunSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(pattern=r"^[a-f0-9]{16}$")
    target: str = Field(min_length=1, max_length=256)
    task_type: Literal["binary", "multiclass", "regression"]
    metric: Literal["roc_auc", "pr_auc", "f1_macro", "rmse", "mae"]
    deploy: bool = False
    budget: RunBudget = Field(default_factory=RunBudget)


def _materialise(dataset_id: str) -> str:
    """Write the uploaded dataset as parquet under the data-tools allowed root."""
    import pandas as pd

    from apps.api.routes.datasets import _read_frame

    store = get_store()
    meta = store.get_json(dataset_id, "meta.json")
    blob = store.get_blob(dataset_id, "data.bin")
    if meta is None or blob is None or meta.get("status") != "ready":
        raise HTTPException(409, "dataset is not ready")
    out = Path(_path("RUN_INPUT_DIR", "data/run_inputs")) / f"{dataset_id}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df: pd.DataFrame = _read_frame(blob, meta["kind"])
    df.to_parquet(out)
    return str(out)


@router.post("/v1/runs", status_code=202)
def submit_run(body: RunSubmit, admin: str = Depends(rate_limited)) -> dict[str, str]:
    path = _materialise(body.dataset_id)
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    cfg = RunConfig(
        run_id=run_id,
        task=RunTask(
            name=body.dataset_id, data_path=path, target=body.target,
            task_type=body.task_type, metric=body.metric,
        ),
        budget=body.budget, deploy=body.deploy, mode="dev",
    )  # fmt: skip
    job_id = job_queue().enqueue(run_id, {"config": cfg.model_dump(mode="json")})
    audit_log().append(admin, "run_submitted", {"run_id": run_id, "dataset": body.dataset_id})
    return {"run_id": run_id, "job_id": job_id}


def execute_job(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = RunConfig.model_validate(payload["config"])
    approvals: ApprovalStore | None = None
    if os.environ.get("APPROVAL_SECRET"):
        approvals = approval_store()
    runner = AgentRunner(
        run_store(),
        ScriptedPlanner(),
        run_root=_path("RUN_ROOT", "data/runs"),
        audit=audit_log(),
        approvals=approvals,
        approval_token=payload.get("approval_token"),
    )

    return runner.run(cfg)


def work_once() -> bool:
    q = job_queue()
    if not isinstance(q, SQLiteJobQueue):
        raise RuntimeError("work_once drives the SQLite queue; arq workers run separately")
    return Worker(q, execute_job).run_once()


class ResumeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_token: str = Field(min_length=10, max_length=2000)


@router.post("/v1/runs/{run_id}/resume", status_code=202)
def resume_run(run_id: str, body: ResumeBody, admin: str = Depends(rate_limited)) -> dict[str, str]:
    """Continue a run that is `awaiting_approval`, supplying the single-use approval token."""
    store = run_store()
    if store.status(run_id) != "awaiting_approval":
        raise HTTPException(409, "run is not awaiting approval")
    cfg = store.config(run_id)
    payload = {"config": cfg.model_dump(mode="json"), "approval_token": body.approval_token}
    job_id = job_queue().enqueue(run_id, payload)
    audit_log().append(admin, "run_resumed", {"run_id": run_id})
    return {"run_id": run_id, "job_id": job_id}


@router.get("/ui", include_in_schema=False)
def ui() -> FileResponse:
    return FileResponse(Path(__file__).resolve().parents[1] / "static" / "index.html")


@router.get("/v1/runs/{run_id}")
def get_run(run_id: str, admin: str = Depends(require_admin)) -> dict[str, Any]:
    store = run_store()
    status = store.status(run_id)
    if status is None:
        raise HTTPException(404, "unknown run")
    return {"run_id": run_id, "status": status, "result": store.result(run_id)}


@router.get("/v1/runs/{run_id}/report")
def get_report(run_id: str, admin: str = Depends(require_admin)) -> FileResponse:
    res = run_store().result(run_id) or {}
    html = (res.get("report") or {}).get("html")
    if not html or not Path(html).exists():
        raise HTTPException(404, "report not available")
    return FileResponse(html, media_type="text/html")


@router.get("/metrics")
def metrics() -> Response:
    """Aggregate counters only (no run ids or data); safe to scrape unauthenticated."""
    store = run_store()
    text = render_metrics(store.list_runs(), store.step_stats())
    return Response(text, media_type="text/plain; version=0.0.4")
