"""Demo entrypoint: `uvicorn apps.api.demo.app:app --port $PORT`.

Builds a LIGHT FastAPI app (admin login router + demo routes) instead of importing the full
`apps.api.main`, which pulls pandas, scikit-learn, SQLAlchemy and Redis into the web process
(about 215 MB). The agent runs in a child process (`run_job`), so the web process stays small:
the free Render plan allows 512 MB for the whole process tree. Upload, dataset, run-submission and
deploy routes do not exist here at all, and the guard middleware still refuses those paths.
DEMO_MODE must be 1: the entrypoint refuses to start otherwise.
"""

from __future__ import annotations

import os

os.environ.setdefault("DEMO_MODE", "1")

from fastapi import FastAPI  # noqa: E402

from apps.api.demo import demo_enabled, install  # noqa: E402
from apps.api.routes.admin import router as admin_router  # noqa: E402

if not demo_enabled():
    raise RuntimeError("apps.api.demo.app requires DEMO_MODE=1")

app = FastAPI(title="junior-ml-dev demo", version="0.3")
app.include_router(admin_router)
install(app)
