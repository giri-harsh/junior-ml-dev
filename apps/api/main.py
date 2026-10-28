"""API entrypoint. S1 ships only health probes."""

from __future__ import annotations

from fastapi import FastAPI, Response
from sqlalchemy import text

from apps.api.routes.datasets import router as datasets_router
from trajectory.db import make_engine

app = FastAPI(title="junior-ml-dev", version="0.1.0")
app.include_router(datasets_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz(response: Response) -> dict[str, str]:
    """Ready when Postgres answers. Redis/MinIO checks arrive with their first consumers."""
    try:
        with make_engine(connect_args={"connect_timeout": 2}).connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        response.status_code = 503
        return {"status": "not-ready", "db": "down"}
    return {"status": "ready", "db": "up"}
