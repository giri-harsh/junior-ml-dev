"""Space entrypoint: `uvicorn apps.api.demo.app:app --port 7860`.

Imports the regular API app and installs demo mode on it explicitly, so the Space does not depend
on `apps/api/main.py` calling `install`. DEMO_MODE must be 1: the entrypoint refuses to start
the full (upload-capable) API by mistake.
"""

from __future__ import annotations

import os

os.environ.setdefault("DEMO_MODE", "1")

from apps.api.demo import demo_enabled, install  # noqa: E402
from apps.api.main import app  # noqa: E402

if not demo_enabled():
    raise RuntimeError("apps.api.demo.app requires DEMO_MODE=1")
install(app)
