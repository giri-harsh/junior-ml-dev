"""Public demo API: pick a bundled sample, start a run, poll it, read its report."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from apps.api.demo.config import REPO_URL
from apps.api.demo.datasets import catalog, download_path
from apps.api.demo.guard import client_ip
from apps.api.demo.pages import REPORT_CSP
from apps.api.demo.samples import public_info
from apps.api.demo.service import DemoError, DemoService
from apps.api.routes.admin import require_admin

router = APIRouter(tags=["demo"])
RUN_ID = r"^demo-[a-f0-9]{10}$"
DATASET_KEY = r"^[a-z][a-z0-9\-]{1,31}$"


class DemoRunBody(BaseModel):
    """Only a sample key: no dataset, target, budget, deploy flag or code can be supplied."""

    model_config = ConfigDict(extra="forbid")

    sample: str = Field(pattern=r"^[a-z][a-z0-9\-]{1,31}$")


def svc(request: Request) -> DemoService:
    service: DemoService = request.app.state.demo_service
    return service


Svc = Annotated[DemoService, Depends(svc)]


@router.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "demo": True}


@router.get("/demo/api/info")
def info(request: Request, service: Svc) -> dict[str, Any]:
    cat = {c["key"]: c for c in catalog(service.s.data_dir)}
    samples = [{**s, **cat.get(s["key"], {})} for s in public_info(service.s.data_dir)]
    return {**service.info(), "samples": samples, "repo": REPO_URL}


@router.post("/demo/api/runs", status_code=202)
def start_run(body: DemoRunBody, request: Request, service: Svc) -> JSONResponse:
    try:
        run_id = service.submit(body.sample, client_ip(request, service.s.proxy_hops))
    except DemoError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(exc.status, exc.detail, headers=headers) from None
    return JSONResponse({"run_id": run_id}, status_code=202)


@router.get("/demo/api/runs/{run_id}")
def run_status(run_id: str, service: Svc) -> dict[str, Any]:
    status = service.public_status(run_id) if re.match(RUN_ID, run_id) else None
    if status is None:
        raise HTTPException(404, "unknown run")
    return status


@router.get("/demo/api/runs/{run_id}/report")
def run_report(run_id: str, service: Svc) -> Response:
    if not re.match(RUN_ID, run_id):
        raise HTTPException(404, "report not available")
    headers = {"Content-Security-Policy": REPORT_CSP}
    page = service.report_html(run_id)
    if page is not None:
        return HTMLResponse(page, headers=headers)
    path = service.report_path(run_id)  # fallback: the plain harness report
    if path is None:
        raise HTTPException(404, "report not available")
    return FileResponse(path, media_type="text/html", headers=headers)


@router.get("/datasets/{name}.csv")
def dataset_csv(name: str, service: Svc) -> FileResponse:
    """The exact bytes the pipeline loads for a bundled sample (hash-verified on every read)."""
    if not re.match(DATASET_KEY, name):
        raise HTTPException(404, "unknown dataset")
    try:
        path = download_path(service.s.data_dir, name)
    except (KeyError, ValueError, OSError):
        raise HTTPException(404, "unknown dataset") from None
    return FileResponse(
        path, media_type="text/csv; charset=utf-8", filename=f"{name}.csv",
        content_disposition_type="attachment",
    )  # fmt: skip


@router.get("/runs/{run_id}", include_in_schema=False)
def run_page(run_id: str, request: Request) -> Response:
    """The live-run page. The same static shell for every id; the run is read over the API."""
    if not re.match(RUN_ID, run_id):
        raise HTTPException(404, "unknown run")
    shell: str = request.app.state.demo_run_page
    return HTMLResponse(shell)


@router.get("/demo/api/admin/runs")
def admin_runs(
    _admin: Annotated[str, Depends(require_admin)], service: Svc
) -> list[dict[str, Any]]:
    return service.admin_list()


def landing_response(site_dir: Path) -> Response:
    index = site_dir / "index.html"
    if index.is_file():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    return HTMLResponse(
        "<!doctype html><title>junior-ml-dev demo</title>"
        f'<h1>junior-ml-dev demo</h1><p>Landing page not built. <a href="{REPO_URL}">Repo</a></p>',
        status_code=200,
    )
