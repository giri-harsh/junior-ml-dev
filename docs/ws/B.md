# Workstream B: public demo on Hugging Face Spaces (docker SDK)

Status: everything is built and tested locally. The live Space is NOT deployed: Hugging Face
refused to create it (HTTP 402, "hosting Gradio and Docker Spaces on free cpu-basic requires a PRO
subscription"). No live number below is from a Space.

## Resume (one line)

```
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/deploy_space.py && PYTHONUTF8=1 .venv/Scripts/python.exe scripts/deploy_space.py --verify auto --json-out data/demo/verify_live.json
```

Needs `HF_TOKEN` in `.env` (present) on an account that can host Docker Spaces (PRO, or a paid
hardware tier), and `hf_build` budget (`python scripts/budget.py reserve hf_build 1` is called by the
script itself, right before the commit that starts the build; denied means deferred). Optional
`.env` names: `DEMO_PRIVATE=1` (private Space), `DEMO_SPACE_ID` (written by the script after the
first deploy so reruns update the same Space). Dry run, no network and no token:
`python scripts/deploy_space.py --dry-run`.

## What was built

| Part | File |
|---|---|
| Demo guard, `install(app)` (no-op unless `DEMO_MODE=1`) | `apps/api/demo/__init__.py`, `guard.py` |
| Run service: one-at-a-time queue, per-IP/global limits, history cap, hard kill | `apps/api/demo/service.py` |
| Scripted-only runner without sandbox/deploy tools; child entry point | `apps/api/demo/runner.py`, `run_job.py` |
| Public API `/demo/api/*`, `/health` | `apps/api/demo/routes.py` |
| Space entrypoint `uvicorn apps.api.demo.app:app` | `apps/api/demo/app.py` |
| Samples (OpenML 37, 31, 40691; fetched at build) and landing renderer | `samples.py`, `prepare.py`, `landing.py` |
| Landing page + try-it UI (no Node, no inline script) | `apps/web/demo/` |
| Image (python:3.12-slim, `uv export --no-dev` from `uv.lock`, port 7860) | `Dockerfile.space` |
| Upload allowlist | `.spaceignore` |
| Deploy, upload guard, secret scan, verify | `scripts/deploy_space.py` |
| Tests (58 + the demo suite below) | `tests/demo/` |

## How the demo constraints are enforced (in code, not by convention)

- `DEMO_MODE=1` only: `install()` returns `None` and touches nothing otherwise; the Space entrypoint
  refuses to start when `DEMO_MODE != 1`.
- No uploads: every `/v1/datasets*` route is removed and the middleware answers 403 to any
  multipart request or dataset-namespace call. No deploy: routes containing `deploy` are removed and
  answer 404; `POST /v1/runs` and `/resume` are removed (403), so a run can only start through
  `POST /demo/api/runs {"sample": "<key>"}` (pydantic `extra=forbid`: no budget, dataset, deploy or
  code field exists).
- No sandbox / code execution: `DemoAgentRunner` deletes `engineer_features`, `check_code_policy`,
  `package_model`, `deploy_local` from its tool registry; configs with `sandbox_features`, `deploy`
  or a non-scripted planner are refused; `JMD_SANDBOX`, `QUEUE_BACKEND`, `E2B_API_KEY` are removed from
  the process environment; the run child gets a minimal environment (no JWT/approval/API secrets).
- Budgets: wall 90 s hard (child process tree killed), soft wall 55 s (agent wraps up), FLAML 15 s
  (ceiling 20). Env overrides can only lower these.
- One run at a time: single worker thread over `harness.queue.SQLiteJobQueue`; at most 1 running + 3
  queued; one active run per address (409); per-IP 4 runs / 10 min and 40 runs / hour globally (429);
  reads 240/min/IP; admin login 10/min/IP.
- History: newest 20 finished runs, max 6 h; older rows and their directories are deleted; a
  restart marks leftover runs `interrupted`.
- Admin: `/v1/audit*`, `/v1/runs` (GET), `/v1/jobs/*`, `/v1/approvals/*`, `/demo/api/admin/runs` need the
  admin cookie (401 otherwise). Login uses `DEMO_ADMIN_PASSWORD` (argon2-hashed at start), `Secure` cookie.

## Secrets and the upload guard

- Space secrets: only `JWT_SECRET`, `APPROVAL_SECRET`, `DEMO_ADMIN_PASSWORD`, generated with
  `secrets.token_urlsafe` on every deploy. The admin password is written to the local `.env` and never
  printed. GROQ / GEMINI / E2B keys are not read for upload and never set on the Space.
- Upload set = `.spaceignore` allowlist (117 files today), then a hard-deny check (`.env*`,
  cassettes, `benchmarks/**` other than 5 code files, any `docs/` file except `METRICS.md` (so not
  `NEEDS_HARSH.md`), `tests/`, databases, keys, csv/parquet), then a scan with the repo's
  `scripts/secret_scan.py` patterns plus an HF-token pattern plus the literal values of the local
  secrets. Findings print file, line and rule name, never the match. Any hit aborts (exit 2).

## Verification checklist (`--verify <url|auto>`)

Checks: `/health` 200 (time to first 200 = cold start), landing renders and links the repo, admin
endpoints 401, upload rejected, deploy absent, 3 sample runs each < 90 s with p50, report renders.
Exit 0 only if all pass. Unit-tested against a local TestClient (pass case, a non-demo app that
accepts uploads fails, an unreachable service reports no invented numbers).

Local measurement, NOT the Space (Windows dev machine, real server on 127.0.0.1:7860, real
subprocess runs, source: `data/demo/verify_local.json`, not committed): all 11 checks passed;
3 sample runs 44.1 s, 48.1 s, 36.1 s (p50 44.1 s); `/health` 0.1 s. A 2 vCPU Space will be slower;
expect the 90 s limit to be tight for `credit-g`. Cold start on a real Space includes the image pull
and is unmeasured.

## Assumptions to check on the first live run

- Client IP: `DEMO_PROXY_HOPS=1` takes the last `X-Forwarded-For` entry. If Hugging Face adds more
  than one proxy hop, every visitor shares one limit bucket (fails closed, so the global cap and the
  queue still hold). Adjust `DEMO_PROXY_HOPS` in `Dockerfile.space` after checking the header.
- `nvidia-nccl-cu12` (xgboost's optional GPU wheel, the only CUDA package in `uv.lock`) is dropped in
  the image and the build runs an import smoke test; if that import fails, remove the `grep -v` line.
- The Docker build was not run (no Docker here). `uv export` was run and the dependency list checked.
- The Space is served inside an iframe on huggingface.co; the admin cookie is `SameSite=Strict`, so
  admin login works on the direct `*.hf.space` URL only.
- Sample fetch happens during the image build (OpenML needs to be reachable; one retry).

## Requested cross-path change (optional)

Wiring into the main app is not needed for the Space (`apps/api/demo/app.py` installs it), only to
make `uvicorn apps.api.main:app` honour `DEMO_MODE=1`:

```diff
--- a/apps/api/main.py
+++ b/apps/api/main.py
@@
 from apps.api.routes.runs import router as runs_router
+from apps.api.demo import install as install_demo
@@
 @app.get("/readyz")
 def readyz(response: Response) -> dict[str, str]:
@@
     return {"status": "ready", "db": "up"}
+
+
+install_demo(app)  # strict no-op unless DEMO_MODE=1
```

No `pyproject.toml` change is needed (`huggingface_hub==2.4.0` is only used by the deploy script; add
it to a dev/ops dependency group if you want it in CI: `uv add --dev huggingface_hub==2.4.0`).
