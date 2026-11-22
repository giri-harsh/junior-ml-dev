"""Static frontend + backend warm-up: /health reports readiness without loading anything, early
runs get 503 warming_up, CORS lets only the frontend origins in, and the committed static build
matches what scripts/build_frontend.py generates."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.demo.service import DemoService
from scripts import build_frontend

REPO = Path(__file__).resolve().parents[2]
FRONT = "https://ml.harshgiri.site"


def test_health_reports_readiness_and_early_runs_get_503(
    app_service: tuple[FastAPI, DemoService], client: TestClient
) -> None:
    app, _ = app_service
    assert client.get("/health").json() == {"status": "ok", "demo": True, "model_loaded": True}
    app.state.demo_ready = lambda: False
    assert client.get("/health").json()["model_loaded"] is False
    r = client.post("/demo/api/runs", json={"sample": "diabetes"})
    assert r.status_code == 503 and r.json() == {"status": "warming_up"}
    assert r.headers["retry-after"] == "5"
    app.state.demo_ready = lambda: True
    assert client.post("/demo/api/runs", json={"sample": "diabetes"}).status_code == 202


def test_cors_allows_only_the_frontend_and_local_dev(client: TestClient) -> None:
    for origin in (FRONT, "http://localhost:5173", "http://127.0.0.1:8080"):
        r = client.get("/health", headers={"Origin": origin})
        assert r.headers["access-control-allow-origin"] == origin
        assert "access-control-allow-credentials" not in r.headers
    for origin in ("https://evil.example", "https://ml.harshgiri.site.evil.example"):
        r = client.get("/demo/api/info", headers={"Origin": origin})
        assert "access-control-allow-origin" not in r.headers
    pre = client.options("/demo/api/runs", headers={
        "Origin": FRONT, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })  # fmt: skip
    assert pre.status_code == 200 and "POST" in pre.headers["access-control-allow-methods"]


def test_committed_static_frontend_is_current(tmp_path: Path) -> None:
    built = build_frontend.build(tmp_path)
    committed = REPO / "apps" / "web" / "demo-static"
    stamp = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d UTC")
    for rel in built:
        a = stamp.sub("", (tmp_path / rel).read_text(encoding="utf-8"))
        b = stamp.sub("", (committed / rel).read_text(encoding="utf-8"))
        assert a == b, f"{rel} is stale: run python scripts/build_frontend.py"
    index = (committed / "index.html").read_text(encoding="utf-8")
    assert 'id="info" hidden data-v="{' in index and "diabetes" in index  # datasets baked in
    assert 'src="/demo-assets/config.js"' in index
    config = (committed / "demo-assets" / "config.js").read_text(encoding="utf-8")
    assert build_frontend.FALLBACK_API in config
    assert (REPO / "apps" / "web" / "demo" / "assets" / "config.js").read_text(
        encoding="utf-8"
    ).count('window.JMD_API = "";') == 1  # the backend-served pages stay same-origin
