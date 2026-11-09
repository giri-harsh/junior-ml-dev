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


def _deploy_render() -> object:
    sys.path.insert(0, str(ROOT / "scripts"))
    import deploy_render

    return deploy_render


def test_render_service_body_carries_only_demo_settings_and_generated_secrets() -> None:
    dr = _deploy_render()
    body = dr.service_body(
        "tea-x", {"JWT_SECRET": "a", "APPROVAL_SECRET": "b", "DEMO_ADMIN_PASSWORD": "c"}
    )  # type: ignore[attr-defined]
    keys = {e["key"] for e in body["envVars"]}
    assert keys == {*dr.PLAIN_ENV, *dr.SECRET_NAMES}  # type: ignore[attr-defined]
    assert not any(k.startswith(("GROQ", "GEMINI", "E2B", "HF_", "RENDER")) for k in keys)
    d = body["serviceDetails"]
    assert d["plan"] == "free" and d["healthCheckPath"] == "/health" and d["runtime"] == "docker"
    assert body["branch"] == "main" and body["autoDeploy"] == "yes"


def test_render_env_helpers_read_only_named_keys_and_handle_indent(tmp_path: Path) -> None:
    dr = _deploy_render()
    p = tmp_path / ".env"
    p.write_text("GROQ_API_KEY=x\n   RENDER_API_KEY = 'abc'\n# c\nOTHER=1\n", encoding="utf-8")
    got = dr.read_env_names(p, dr.SETTING_NAMES)  # type: ignore[attr-defined]
    assert got == {"RENDER_API_KEY": "abc"}
    dr.set_local_env(p, "DEMO_ADMIN_PASSWORD", "pw")  # type: ignore[attr-defined]
    dr.set_local_env(p, "DEMO_ADMIN_PASSWORD", "pw2")  # type: ignore[attr-defined]
    lines = [x for x in p.read_text(encoding="utf-8").splitlines() if x.startswith("DEMO_ADMIN")]
    assert lines == ["DEMO_ADMIN_PASSWORD=pw2"]
