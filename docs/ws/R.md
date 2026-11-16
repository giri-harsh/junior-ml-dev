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

## What happened on the live free instance (2026-11-09)

| Step | Finding |
|---|---|
| first deploy (per-run subprocess) | every run hit the 60 s wall: the child needed 43.8 s just to import pandas / scikit-learn / lightgbm (2.0 s locally, about 22x slower) |
| FLAML off, leakage budget 8 s | no help: `detect_leakage` ran 57 s because a single detector cannot be interrupted between its budget checks |
| warm fork server (`apps/api/demo/zygote.py`) | imports once at boot, forks a child per run (POSIX only; the Windows/dev path is unchanged) |
| leakage detectors skipped in demo (`DEMO_LEAKAGE_MODE=skip`) | recorded as a PARTIAL check (the reviewer treats it as a warning); the full detectors still run everywhere else |
| result | 3/3 sample runs `done`, reports 200, p50 49.8 s; admin 401, upload 403, deploy path 404 |
| cold start after >15 min idle | health 32.7 s; first run 105.8 s end to end (it waits for the warm worker) |

Source: `benchmarks/results/demo_render_v1.json`. The public status of a run now shows per-step
timings (`progress`), which is how the import and leakage costs were found. The free plan CPU and
a 512 MB limit are the constraints; live peak memory is not visible through the Render API.

## Custom domain (ml.harshgiri.site)

The demo is host-agnostic, so a custom domain needs no code change: the pages call the API with
relative same-origin paths, there is no CORS middleware (same-origin requests need none) and no
host allowlist, and the admin cookie is host-only (no `Domain` attribute, `HttpOnly`,
`SameSite=Strict`, `Secure`), so login works separately on each address.
`tests/demo/test_hosts.py` checks this for `ml.harshgiri.site`, the Render URL and a `*.hf.space`
URL.

As of 2026-11-15 `ml.harshgiri.site` has no DNS record (NXDOMAIN at the domain's Namecheap
nameservers and at 1.1.1.1), and there is no junior-ml-dev Hugging Face Space (the free Docker
Space needs PRO; the demo runs on Render). To serve the demo at the custom domain:

1. Render dashboard > junior-ml-dev-demo > Settings > Custom Domains > add `ml.harshgiri.site`.
2. Namecheap > harshgiri.site > Advanced DNS > add `CNAME` host `ml` value
   `junior-ml-dev-demo.onrender.com`.
3. Wait for Render to verify the domain and issue the certificate, then switch the README and
   `apps/space/static_site.py` `LIVE_URL` to `https://ml.harshgiri.site`, keeping the Render URL
   as the fallback.

Final setup (live since 2026-11-16): `ml.harshgiri.site` is a custom domain on the Render service
junior-ml-dev-demo, verified with the certificate issued, and Namecheap has `CNAME` host `ml` value
`junior-ml-dev-demo.onrender.com`. `deploy.harshgiri.site` was removed from the
calorie-tracker service to free the free plan's custom-domain slot. The README
and `LIVE_URL` point at `https://ml.harshgiri.site`; `https://junior-ml-dev-demo.onrender.com`
stays as the fallback. Checked with `curl --doh-url https://dns.google/dns-query
https://ml.harshgiri.site/health`: `{"status":"ok","demo":true}`, TLS verified.
