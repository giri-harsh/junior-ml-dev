"""The demo is host-agnostic: it works unchanged on the Render URL, a *.hf.space URL and a custom
domain such as ml.harshgiri.site. Same-origin relative API calls, no CORS, no host allowlist, and a
host-only admin cookie (no Domain attribute), so login works separately on each address."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.demo.service import DemoService
from tests.demo.conftest import ADMIN_PW

REPO = Path(__file__).resolve().parents[2]
HOSTS = (
    "ml.harshgiri.site",
    "junior-ml-dev-demo.onrender.com",
    "pseudo-harsh-junior-ml-dev.hf.space",
)


@pytest.mark.parametrize("host", HOSTS)
def test_pages_api_and_admin_login_work_on_every_host(
    app_service: tuple[FastAPI, DemoService], host: str
) -> None:
    app, _ = app_service
    c = TestClient(app, base_url=f"https://{host}")
    assert c.get("/health").status_code == 200
    assert c.get("/runs/demo-0123456789").status_code == 200
    info = c.get("/demo/api/info")
    assert info.status_code == 200 and info.json()["samples"]
    assert c.get("/datasets/diabetes.csv").status_code == 200
    login = c.post("/v1/auth/login", json={"user": "admin", "password": ADMIN_PW})
    assert login.status_code == 200
    cookie = login.headers["set-cookie"].lower()
    assert "domain=" not in cookie  # host-only: valid for exactly the address that set it
    assert "httponly" in cookie and "samesite=strict" in cookie and "secure" in cookie
    assert c.get("/demo/api/admin/runs").status_code == 200  # the cookie works on this host


def test_a_cookie_from_one_host_is_not_sent_to_another(
    app_service: tuple[FastAPI, DemoService],
) -> None:
    app, _ = app_service
    a = TestClient(app, base_url="https://ml.harshgiri.site")
    assert a.post("/v1/auth/login", json={"user": "admin", "password": ADMIN_PW}).status_code == 200
    b = TestClient(app, base_url="https://junior-ml-dev-demo.onrender.com")
    assert b.get("/demo/api/admin/runs").status_code == 401  # each address logs in on its own


def test_no_cors_headers_and_no_host_allowlist(app_service: tuple[FastAPI, DemoService]) -> None:
    app, _ = app_service
    c = TestClient(app, base_url="https://ml.harshgiri.site")
    r = c.get("/demo/api/info", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200 and "access-control-allow-origin" not in r.headers
    names = {type(m.cls).__name__ if not isinstance(m.cls, type) else m.cls.__name__
             for m in app.user_middleware}  # fmt: skip
    assert "CORSMiddleware" not in names and "TrustedHostMiddleware" not in names


def test_front_ends_call_the_api_with_relative_paths() -> None:
    web = REPO / "apps" / "web"
    sources = [
        *(web / "demo" / "assets").glob("*.js"),
        web / "demo" / "landing.template.html",
        web / "demo" / "run.template.html",
        *(web / "src").glob("*.jsx"),
    ]
    for f in sources:
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"https?://[^\"' ]*(onrender\.com|hf\.space|harshgiri\.site)", text), f
        for call in re.findall(r"fetch\(\s*([^,)]+)", text):
            assert "http" not in call, (f, call)  # same-origin only
