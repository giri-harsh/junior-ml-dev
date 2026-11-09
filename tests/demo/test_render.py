"""Render deployment artifacts: the blueprint, the Dockerfile and the web-process memory guard."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_blueprint_is_free_tier_with_health_check_and_no_secret_values() -> None:
    svc = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))["services"][0]
    assert svc["plan"] == "free" and svc["healthCheckPath"] == "/health"
    assert svc["runtime"] == "docker" and svc["dockerfilePath"] == "./Dockerfile.render"
    env = {e["key"]: e for e in svc["envVars"]}
    assert env["DEMO_MODE"]["value"] == "1"
    assert (
        float(env["DEMO_MAX_WALL_S"]["value"]) <= 60 and float(env["DEMO_FLAML_S"]["value"]) <= 15
    )
    for secret in ("JWT_SECRET", "APPROVAL_SECRET", "DEMO_ADMIN_PASSWORD"):
        assert env[secret].get("sync") is False and "value" not in env[secret]
    assert not any(k.startswith(("GROQ", "GEMINI", "E2B", "HF_")) for k in env)


def test_dockerfile_binds_to_the_render_port_and_enforces_demo_mode() -> None:
    text = (ROOT / "Dockerfile.render").read_text(encoding="utf-8")
    assert "0.0.0.0" in text and "${PORT" in text and "ENV DEMO_MODE=1" in text
    assert "--workers 1" in text and "USER 1000" in text


def test_demo_web_process_does_not_import_the_heavy_stack() -> None:
    """The web process must stay small (512 MB plan): the agent runs in a child process."""
    code = (
        "import sys, apps.api.demo.app\n"
        "heavy = [m for m in ('pandas', 'sklearn', 'scipy', 'pyarrow', 'sqlalchemy', 'redis')"
        " if m in sys.modules]\n"
        "print(','.join(heavy))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120,
        env={**os.environ, "DEMO_MODE": "1", "PYTHONPATH": str(ROOT)},
    )  # fmt: skip
    assert out.returncode == 0, out.stderr[-500:]
    assert out.stdout.strip() == "", f"heavy modules imported by the demo web process: {out.stdout}"
