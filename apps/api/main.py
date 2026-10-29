"""API entrypoint. S1 ships only health probes."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from apps.api.routes.admin import router as admin_router
from apps.api.routes.datasets import router as datasets_router
from apps.api.routes.runs import router as runs_router
from trajectory.db import make_engine

app = FastAPI(title="junior-ml-dev", version="0.1.0")
app.include_router(datasets_router)
app.include_router(admin_router)
app.include_router(runs_router)

# The React run viewer is built only in CI (.github/workflows/web.yml) and committed as static
# files; when apps/web/dist exists it is served at /app/.
_dist = Path(__file__).resolve().parents[1] / "web" / "dist"
if _dist.is_dir():
    app.mount("/app", StaticFiles(directory=_dist, html=True), name="viewer")


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
