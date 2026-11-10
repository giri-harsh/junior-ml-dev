"""Demo-mode enforcement: routes are removed from the app, and a middleware refuses the rest.

Two independent layers so that neither a missed route nor a new one can reopen a closed door:
1. `strip_routes` deletes upload, run-submission, resume, deploy, UI and DB-readiness routes.
2. `GuardMiddleware` refuses (before routing) any upload-shaped request, any mutation of the
   dataset/run/deploy namespaces, oversized bodies, and floods of reads and login attempts.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from apps.api.demo.config import DemoSettings
from harness.security.ratelimit import RateLimiter

MAX_BODY_BYTES = 8 * 1024  # every legitimate demo request is a few dozen bytes of JSON
DEPLOY = re.compile(r"deploy", re.IGNORECASE)
DATASETS = re.compile(r"^/v1/datasets(/|$)")
RUNS_WRITE = re.compile(r"^/v1/runs(/[^/]+/resume)?/?$")
READS = ("GET", "HEAD", "OPTIONS")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def client_ip(request: Request, hops: int) -> str:
    """The caller's address. With `hops` trusted proxies in front, the entry `hops` places from
    the right of X-Forwarded-For is the one the outermost trusted proxy saw; earlier entries are
    client-supplied and ignored. With hops=0 the header is not trusted at all."""
    if hops > 0:
        parts = [
            p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()
        ]
        if len(parts) >= hops:
            return parts[-hops]
    return request.client.host if request.client else "unknown"


def is_blocked_route(path: str, methods: set[str]) -> bool:
    if DEPLOY.search(path) or DATASETS.match(path):
        return True
    if path in {"/ui", "/readyz"}:
        return True
    return bool(RUNS_WRITE.match(path) and "POST" in methods)


def _route_key(route: Any) -> tuple[str, set[str]] | None:
    path = getattr(route, "path", None)
    return (path, set(getattr(route, "methods", None) or ())) if isinstance(path, str) else None


def strip_routes(app: FastAPI) -> list[str]:
    """Remove every blocked route from this app (never from the shared module-level routers).

    FastAPI >= 0.16x includes routers lazily (`_IncludedRouter` wrappers that point at the shared
    router object), so an included router is replaced by a filtered copy; plain routes and older
    FastAPI versions are filtered in place. Returns 'METHODS path' for what was removed."""
    kept: list[Any] = []
    removed: list[str] = []

    def keep(route: Any) -> bool:
        key = _route_key(route)
        if key is not None and is_blocked_route(*key):
            removed.append(f"{','.join(sorted(key[1]))} {key[0]}")
            return False
        return True

    for r in app.router.routes:
        inner = getattr(r, "original_router", None)
        if inner is not None and hasattr(r, "include_context"):
            filtered = APIRouter()
            filtered.routes.extend(x for x in inner.routes if keep(x))
            wrapper: Any = type(r)
            kept.append(wrapper(original_router=filtered, include_context=r.include_context))
        elif keep(r):
            kept.append(r)
    app.router.routes[:] = kept
    return removed


class GuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, settings: DemoSettings, read_limiter: RateLimiter) -> None:
        super().__init__(app)
        self.s = settings
        self.read_limiter = read_limiter
        self.login_limiter = RateLimiter(10, 60.0)
        self.download_limiter = RateLimiter(30, 60.0)  # sample CSV downloads, per address

    @staticmethod
    def _deny(status: int, detail: str, retry_after: int | None = None) -> Response:
        headers = dict(SECURITY_HEADERS)
        if retry_after is not None:
            headers["Retry-After"] = str(retry_after)
        return JSONResponse({"detail": detail}, status_code=status, headers=headers)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path, method = request.url.path, request.method.upper()
        ctype = request.headers.get("content-type", "").lower()
        ip = client_ip(request, self.s.proxy_hops)
        if DEPLOY.search(path):
            return self._deny(404, "not found")  # there is no deploy endpoint in the demo
        if ctype.startswith("multipart/") or "filename=" in request.headers.get(
            "content-disposition", ""
        ):
            return self._deny(403, "uploads are disabled in the demo")
        if DATASETS.match(path) or (method not in READS and RUNS_WRITE.match(path)):
            return self._deny(403, "disabled in the demo")
        try:
            length = int(request.headers.get("content-length", "0") or 0)
        except ValueError:
            return self._deny(400, "bad content-length")
        if length > MAX_BODY_BYTES:
            return self._deny(413, "request body too large")
        if path == "/v1/auth/login" and not self.login_limiter.allow(ip):
            return self._deny(429, "too many login attempts", 30)
        if path.startswith("/datasets/") and not self.download_limiter.allow(ip):
            return self._deny(429, "too many downloads", 30)
        if (
            path.startswith("/demo/api/")
            and not (
                method == "POST" and path == "/demo/api/runs"  # runs have their own, stricter limit
            )
            and not self.read_limiter.allow(ip)
        ):
            return self._deny(429, "too many requests", 10)
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response
