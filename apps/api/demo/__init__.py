"""Public demo mode.

    from apps.api.demo import install
    install(app)   # strict no-op unless DEMO_MODE=1

When DEMO_MODE=1 the app is locked down in code (see `guard`): no uploads, no deploy, no sandbox
or code execution, scripted planner only, per-run wall clock and FLAML ceilings, one run at a
time, per-IP and global rate limits, a capped run history, and admin-only admin endpoints.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from apps.api.demo.config import DemoSettings, demo_enabled
from apps.api.demo.guard import GuardMiddleware, strip_routes
from apps.api.demo.routes import landing_response
from apps.api.demo.routes import router as demo_router
from apps.api.demo.service import DemoService, Executor, subprocess_executor

__all__ = ["DemoService", "DemoSettings", "demo_enabled", "install"]

ASSETS = Path(__file__).resolve().parents[2] / "web" / "demo" / "assets"
# Settings that could open a door the demo keeps shut; removed from the process environment.
_UNSAFE_ENV = ("JMD_SANDBOX", "QUEUE_BACKEND", "OBJECT_STORE", "JMD_WORKER", "E2B_API_KEY")


def _configure_admin() -> None:
    """DEMO_ADMIN_PASSWORD (a Space secret) becomes the single admin's argon2 hash."""
    pw = os.environ.pop("DEMO_ADMIN_PASSWORD", "")
    if pw and not os.environ.get("ADMIN_PASSWORD_HASH"):
        from harness.security.auth import hash_password

        os.environ["ADMIN_PASSWORD_HASH"] = hash_password(pw)
    os.environ.setdefault("ADMIN_USER", "admin")
    os.environ.setdefault("COOKIE_SECURE", "1")


def install(
    app: FastAPI, settings: DemoSettings | None = None, executor: Executor | None = None
) -> DemoService | None:
    if not demo_enabled():
        return None
    if getattr(app.state, "demo_service", None) is not None:
        return app.state.demo_service  # type: ignore[no-any-return]
    for name in _UNSAFE_ENV:
        os.environ.pop(name, None)
    _configure_admin()
    s = settings or DemoSettings.from_env()
    service = DemoService(s, executor or subprocess_executor)
    app.state.demo_service = service
    app.state.demo_removed_routes = strip_routes(app)
    app.include_router(demo_router)

    @app.get("/", include_in_schema=False)
    def landing() -> Any:
        return landing_response(s.site_dir)

    if ASSETS.is_dir():
        app.mount("/demo-assets", StaticFiles(directory=ASSETS), name="demo-assets")
    app.add_middleware(
        GuardMiddleware,  # type: ignore[arg-type]
        settings=s,
        read_limiter=service.read_limiter,
    )

    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(a: FastAPI) -> AsyncIterator[Any]:
        service.start()
        try:
            async with inner(a) as state:
                yield state
        finally:
            service.stop()

    app.router.lifespan_context = lifespan
    return service
