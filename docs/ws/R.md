# Render deployment notes (free plan, 512 MB)

Measured locally (Windows, `psutil` RSS of the whole process tree: web process + the run child),
demo caps `DEMO_MAX_WALL_S=60 DEMO_SOFT_WALL_S=45 DEMO_FLAML_S=15`, 3 bundled samples:

| Build of the web process | idle RSS | peak tree RSS (diabetes / credit-g / wine-quality) |
|---|---|---|
| before: `apps.api.demo.app` imported `apps.api.main` (pandas, sklearn, SQLAlchemy, Redis, ...) | 225 MB | 471 / 475 / 487 MB (over the 450 MB budget) |
| after: light app (admin router + demo routes), `enforce_demo_config` moved to `limits.py` | 63 MB | 309 / 312 / 327 MB |

FLAML was NOT dropped: with the light web process the peak is about 330 MB with FLAML at 15 s.
Run wall times locally: 44 / 47 / 35 s (all under the 60 s hard wall). The free Render CPU is
shared and slower, so live numbers are measured separately (see METRICS.md).

Regression guard: `tests/demo/test_render.py` fails if the demo entrypoint imports pandas/sklearn.
Linux RSS may differ from Windows; the live peak is not observable from the Render API.
