"""Build the static frontend for ml.harshgiri.site into apps/web/demo-static/.

The landing page and the live-run shell, rendered from the same templates and assets the backend
serves, plus /demo/api/info baked in so the datasets show before the backend wakes up. Vercel
serves the folder as is; its build step (build.mjs) only writes the backend URL into config.js.

    python scripts/build_frontend.py
"""

from __future__ import annotations

import html
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.demo import ASSETS, WEB, run_shell  # noqa: E402
from apps.api.demo.config import REPO_URL, DemoSettings  # noqa: E402
from apps.api.demo.datasets import catalog  # noqa: E402
from apps.api.demo.landing import render_landing  # noqa: E402
from apps.api.demo.samples import public_info  # noqa: E402
from apps.api.demo.service import public_limits  # noqa: E402

OUT = ROOT / "apps" / "web" / "demo-static"
FALLBACK_API = "https://junior-ml-dev-demo.onrender.com"


def render_env() -> dict[str, str]:
    """The DEMO_* values the Render service runs with (render.yaml), so the baked limits match."""
    svc = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))["services"][0]
    return {e["key"]: str(e["value"]) for e in svc["envVars"] if e["key"].startswith("DEMO_")
            and "value" in e}  # fmt: skip


def info_json(data_dir: Path) -> str:
    """Same shape as GET /demo/api/info; the page refreshes it from the backend once awake."""
    cat = {c["key"]: c for c in catalog(data_dir)}
    samples = [{**s, **cat.get(s["key"], {})} for s in public_info(data_dir)]
    with patch.dict(os.environ, render_env()):
        limits = public_limits(DemoSettings.from_env())
    info = {"demo": True, "limits": limits, "samples": samples, "repo": REPO_URL}
    return html.escape(json.dumps(info), quote=True)


def build(out: Path = OUT, data_dir: Path | None = None, now: datetime | None = None) -> list[str]:
    data = data_dir or ROOT / "data" / "demo" / "samples"
    metrics = (ROOT / "docs" / "METRICS.md").read_text(encoding="utf-8")
    template = (WEB / "landing.template.html").read_text(encoding="utf-8")
    assets = out / "demo-assets"
    if assets.exists():
        shutil.rmtree(assets)
    shutil.copytree(ASSETS, assets)
    pages = {
        "index.html": render_landing(metrics, template, now=now, info_json=info_json(data)),
        "run.html": run_shell(),
        "demo-assets/config.js": f"window.JMD_API = {json.dumps(FALLBACK_API)};\n",
    }
    for rel, text in pages.items():
        (out / rel).write_text(text, encoding="utf-8", newline="\n")
    return sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())


if __name__ == "__main__":
    files = build()
    print(f"wrote {len(files)} files to {OUT.relative_to(ROOT)}")
