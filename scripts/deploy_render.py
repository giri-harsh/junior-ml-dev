"""Create/verify the public demo on Render (free plan) through the Render API.

    python scripts/deploy_render.py create     # create the service from the GitHub repo (main)
    python scripts/deploy_render.py wait       # poll deploys, print build-log tail on failure
    python scripts/deploy_render.py verify     # live checks + cold start + sample-run p50

Reads RENDER_API_KEY (and RENDER_SERVICE_ID) from the main checkout's .env BY NAME and never
prints them. Secrets set on the service: JWT_SECRET, APPROVAL_SECRET, DEMO_ADMIN_PASSWORD, all
freshly generated; the admin password is written to the local .env and never printed. No LLM, E2B or
Hugging Face key is ever sent.
"""

from __future__ import annotations

import json
import secrets
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API = "https://api.render.com/v1"
REPO = "https://github.com/giri-harsh/junior-ml-dev"
SERVICE_NAME = "junior-ml-dev-demo"
SETTING_NAMES = ("RENDER_API_KEY", "RENDER_SERVICE_ID", "DEMO_URL")
SECRET_NAMES = ("JWT_SECRET", "APPROVAL_SECRET", "DEMO_ADMIN_PASSWORD")
PLAIN_ENV = {
    "DEMO_MODE": "1", "DEMO_MAX_WALL_S": "60", "DEMO_SOFT_WALL_S": "35", "DEMO_FLAML_S": "0",
    "DEMO_LEAKAGE_S": "8", "DEMO_ZYGOTE": "1", "DEMO_LEAKAGE_MODE": "skip",
    "DEMO_PROXY_HOPS": "1", "COOKIE_SECURE": "1",
}  # fmt: skip
ROOT = Path(__file__).resolve().parents[1]


def env_path() -> Path:
    import subprocess

    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, text=True, check=True, cwd=ROOT,
    ).stdout.strip()  # fmt: skip
    return Path(common).parent / ".env"


def read_env_names(path: Path, names: tuple[str, ...]) -> dict[str, str]:
    """Only the named keys; indented lines and quotes are handled; values are never printed."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        if k.strip() in names:
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def set_local_env(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [x for x in lines if x.strip().split("=", 1)[0].strip() != key]
    lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def call(key: str, method: str, path: str, body: Any = None, timeout: float = 60) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json",
                 "Content-Type": "application/json"},
    )  # fmt: skip
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")[:300]
        raise SystemExit(f"Render API {method} {path}: HTTP {e.code} {msg}") from None


def service_body(owner_id: str, env_values: dict[str, str]) -> dict[str, Any]:
    """The create-service request. `env_values` holds only the three generated secrets."""
    env = [{"key": k, "value": v} for k, v in {**PLAIN_ENV, **env_values}.items()]
    return {
        "type": "web_service", "name": SERVICE_NAME, "ownerId": owner_id, "repo": REPO,
        "branch": "main", "autoDeploy": "yes", "envVars": env,
        "serviceDetails": {
            "runtime": "docker", "plan": "free", "region": "oregon", "healthCheckPath": "/health",
            "envSpecificDetails": {"dockerfilePath": "./Dockerfile.render", "dockerContext": "."},
        },
    }  # fmt: skip


def cmd_create(key: str, envp: Path) -> int:
    owners = call(key, "GET", "/owners?limit=20")
    owner_id = owners[0]["owner"]["id"]
    existing = [s["service"] for s in call(key, "GET", f"/services?name={SERVICE_NAME}&limit=5")]
    if existing:
        print(
            "service exists:", existing[0]["id"], existing[0].get("serviceDetails", {}).get("url")
        )
        return 0
    sec = {n: secrets.token_urlsafe(36) for n in SECRET_NAMES}
    set_local_env(
        envp, "DEMO_ADMIN_PASSWORD", sec["DEMO_ADMIN_PASSWORD"]
    )  # local only, never printed
    svc = call(key, "POST", "/services", service_body(owner_id, sec))
    s = svc.get("service", svc)
    set_local_env(envp, "RENDER_SERVICE_ID", s["id"])
    print("created service", s["id"], s.get("serviceDetails", {}).get("url"))
    return 0


def deploy_status(key: str, sid: str) -> tuple[str, str]:
    ds = call(key, "GET", f"/services/{sid}/deploys?limit=1")
    d = ds[0]["deploy"] if ds else {}
    return str(d.get("id", "")), str(d.get("status", "none"))


def build_log_tail(key: str, sid: str, owner_id: str, n: int = 60) -> str:
    q = f"/logs?ownerId={owner_id}&resource={sid}&type=build&limit={n}&direction=backward"
    try:
        logs = call(key, "GET", q)
    except SystemExit as e:
        return f"(log fetch failed: {e})"
    msgs = [x.get("message", "") for x in logs.get("logs", [])]
    return "\n".join(reversed(msgs))[-6000:]


def cmd_wait(key: str, sid: str, timeout_s: int = 1500) -> int:
    t0 = time.time()
    last = ""
    while time.time() - t0 < timeout_s:
        did, st = deploy_status(key, sid)
        if st != last:
            print(f"{int(time.time() - t0):>4}s deploy {did[:12]} {st}")
            last = st
        if st == "live":
            return 0
        if st in {"build_failed", "update_failed", "canceled", "pre_deploy_failed"}:
            owner_id = call(key, "GET", "/owners?limit=1")[0]["owner"]["id"]
            print(build_log_tail(key, sid, owner_id))
            return 1
        time.sleep(20)
    print("timeout waiting for deploy")
    return 2


def http(
    url: str, method: str = "GET", body: Any = None, timeout: float = 120
) -> tuple[int, Any, float]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})  # fmt: skip
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        raw, code = e.read(), e.code
    dt = time.perf_counter() - t0
    try:
        return code, json.loads(raw), dt
    except ValueError:
        return code, raw[:200], dt


def cmd_verify(key: str, sid: str) -> int:
    svc = call(key, "GET", f"/services/{sid}")
    url = svc["serviceDetails"]["url"].rstrip("/")
    checks: dict[str, Any] = {"url": url}
    code, _, cold = http(url + "/health", timeout=180)
    checks["health_status"] = code
    checks["first_request_s"] = round(cold, 1)  # cold start if the service was idle
    checks["landing_status"] = http(url + "/")[0]
    checks["admin_without_auth"] = http(url + "/demo/api/admin/runs")[0]
    checks["upload_rejected"] = http(url + "/v1/datasets", "POST", {})[0]
    checks["deploy_absent"] = http(url + "/v1/deploy", "POST", {})[0]
    times: list[float] = []
    for _ in range(3):
        code, body, _ = http(url + "/demo/api/runs", "POST", {"sample": "diabetes"})
        if code != 202:
            checks["run_submit"] = (code, str(body)[:120])
            break
        rid = body["run_id"]
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 150:
            c, st, _ = http(f"{url}/demo/api/runs/{rid}")
            if isinstance(st, dict) and st.get("status") in {
                "done",
                "failed",
                "budget_exhausted",
                "timeout",
            }:
                checks.setdefault("run_status", []).append(st.get("status"))
                break
            time.sleep(1)
        times.append(time.perf_counter() - t0)
        rep = http(f"{url}/demo/api/runs/{rid}/report")[0]
        checks.setdefault("report_status", []).append(rep)
        time.sleep(2)
    if times:
        checks["sample_run_p50_s"] = round(statistics.median(times), 1)
        checks["sample_run_s"] = [round(t, 1) for t in times]
    print(json.dumps(checks, indent=1))
    ok = (
        checks["health_status"] == 200 and checks["landing_status"] == 200
        and checks["admin_without_auth"] == 401
        and checks["upload_rejected"] in {401, 403, 404, 405}
        and bool(times) and all(r == 200 for r in checks.get("report_status", [0]))
    )  # fmt: skip
    print("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    a = sys.argv[1:] if argv is None else argv
    cmd = a[0] if a else "create"
    envp = env_path()
    cfg = read_env_names(envp, SETTING_NAMES)
    key = cfg.get("RENDER_API_KEY")
    if not key:
        print("RENDER_API_KEY missing")
        return 0
    if cmd == "create":
        return cmd_create(key, envp)
    sid = cfg.get("RENDER_SERVICE_ID") or ""
    if not sid:
        print("RENDER_SERVICE_ID missing: run `create` first")
        return 1
    if cmd == "wait":
        return cmd_wait(key, sid)
    if cmd == "verify":
        return cmd_verify(key, sid)
    raise SystemExit("usage: deploy_render.py create|wait|verify")


if __name__ == "__main__":
    sys.exit(main())
