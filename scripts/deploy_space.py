"""Deploy the public demo to a Hugging Face Space (docker SDK), or verify one that is running.

    python scripts/deploy_space.py --dry-run          # build + scan the upload set, no network
    python scripts/deploy_space.py                    # deploy (needs HF_TOKEN in .env)
    python scripts/deploy_space.py --verify <url>     # checklist + cold start + sample-run p50

Secrets: only JWT_SECRET, APPROVAL_SECRET and DEMO_ADMIN_PASSWORD are put on the Space, freshly
generated with `secrets` on every deploy. DEMO_ADMIN_PASSWORD is also written to the local .env
(never printed). GROQ / GEMINI / E2B keys are never read, uploaded or set. HF_TOKEN and
DEMO_PRIVATE are read from .env by name. Without HF_TOKEN the script prints "HF_TOKEN missing"
and exits 0.

Upload guard: the file set is an allowlist (`.spaceignore`), then checked against a hard-deny list
(.env, cassettes, benchmark data, docs other than METRICS.md, databases, keys) and scanned with the
repo's secret patterns plus the literal values of the local secrets. Any hit aborts the upload.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.secret_scan import PATTERNS as REPO_PATTERNS  # noqa: E402

REPO_URL = "https://github.com/giri-harsh/junior-ml-dev"
SPACE_NAME = "junior-ml-dev"
SPACE_SECRETS = ("JWT_SECRET", "APPROVAL_SECRET", "DEMO_ADMIN_PASSWORD")
# Names whose VALUES must never appear in the upload set. Read from .env only to scan for them.
PROTECTED_NAMES = (
    "HF_TOKEN", "GROQ_API_KEY", "GEMINI_API_KEY", "GROQ_FALLBACK_API_KEY", "E2B_API_KEY",
    "DEMO_ADMIN_PASSWORD", "JWT_SECRET", "APPROVAL_SECRET",
)  # fmt: skip
EXTRA_PATTERNS: dict[str, re.Pattern[str]] = {
    "huggingface-token": re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"),
}
SKIP_WALK_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".budget", ".mypy_cache"}
MAX_BUILD_ATTEMPTS = 6
UPLOAD_NAME = {"Dockerfile.space": "Dockerfile"}

# --- hard-deny list ------------------------------------------------------------------------------
BENCH_CODE_OK = {
    "benchmarks/__init__.py", "benchmarks/metrics.py", "benchmarks/tasks/__init__.py",
    "benchmarks/tasks/registry.py", "benchmarks/tasks/registry.yaml",
}  # fmt: skip
DENY_SUFFIX = (".parquet", ".csv", ".db", ".sqlite", ".sqlite3", ".pem", ".key", ".p12", ".pfx")


def forbidden_reason(rel: str) -> str | None:
    """Why this repo-relative posix path may never be uploaded, or None."""
    parts = rel.split("/")
    name = parts[-1]
    if name == ".env" or name.startswith(".env"):
        return "environment file"
    if "cassettes" in parts or (name.endswith(".jsonl") and "cassette" in rel):
        return "recorded LLM cassette"
    if parts[0] == "benchmarks" and rel not in BENCH_CODE_OK:
        return "benchmark data or results"
    if parts[0] == "docs" and rel != "docs/METRICS.md":
        return "documentation other than METRICS.md (includes docs/NEEDS_HARSH.md)"
    if parts[0] in {"tests", "scorer_data", "data", ".budget", ".git", ".github", ".githooks"}:
        return f"{parts[0]}/ is never part of the image"
    if name.lower().endswith(DENY_SUFFIX) or name.startswith("id_rsa"):
        return "data, database or key file"
    return None


# --- .spaceignore --------------------------------------------------------------------------------
@dataclass(frozen=True)
class Rule:
    allow: bool
    pattern: str
    regex: re.Pattern[str]


def _glob_to_regex(pat: str, anchored: bool) -> re.Pattern[str]:
    """A pattern matches a path, or any directory prefix of it (so `apps/api` allows the tree)."""
    anchored = anchored or "/" in pat.strip("/")
    pat = pat.strip("/")
    out, i = [], 0
    while i < len(pat):
        c = pat[i]
        if pat[i : i + 3] == "**/":
            out.append("(?:.*/)?")
            i += 3
        elif pat[i : i + 2] == "**":
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    body = "".join(out)
    prefix = "" if anchored else "(?:.*/)?"
    return re.compile(f"^{prefix}{body}(?:/.*)?$")


def parse_spaceignore(text: str) -> list[Rule]:
    rules = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        allow = line.startswith("!")
        pat = line[1:] if allow else line
        rules.append(Rule(allow, pat, _glob_to_regex(pat, anchored=allow)))
    return rules


def is_allowed(rules: list[Rule], rel: str) -> bool:
    verdict = False
    for r in rules:
        if r.regex.match(rel):
            verdict = r.allow
    return verdict


def walk_files(root: Path) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_WALK_DIRS)
        for f in sorted(filenames):
            out.append((Path(dirpath) / f).relative_to(root).as_posix())
    return out


class UploadGuardError(RuntimeError):
    pass


def upload_set(root: Path, rules: list[Rule]) -> list[str]:
    """Allowlisted files. Raises UploadGuardError if any is on the hard-deny list."""
    chosen = [rel for rel in walk_files(root) if is_allowed(rules, rel)]
    bad = [(rel, why) for rel in chosen if (why := forbidden_reason(rel))]
    if bad:
        detail = "; ".join(f"{rel} ({why})" for rel, why in bad[:10])
        raise UploadGuardError(f"refusing to upload forbidden files: {detail}")
    return chosen


# --- secret scan ---------------------------------------------------------------------------------
@dataclass(frozen=True)
class Finding:
    path: str
    rule: str
    line: int  # 0 for a literal-value hit


def scan_upload_set(
    root: Path, files: list[str], secret_values: dict[str, str] | None = None
) -> list[Finding]:
    """Regex patterns (the repo's secret_scan set plus HF tokens) and literal secret values.
    Findings carry a rule NAME and a line number only, never the matched text."""
    patterns = {**REPO_PATTERNS, **EXTRA_PATTERNS}
    values = {k: v for k, v in (secret_values or {}).items() if len(v) >= 8}
    found: list[Finding] = []
    for rel in files:
        data = (root / rel).read_bytes()
        for name, value in values.items():
            if value.encode() in data:
                found.append(Finding(rel, f"literal-value:{name}", 0))
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name, pat in patterns.items():
                if pat.search(line):
                    found.append(Finding(rel, name, lineno))
    return found


def check_upload_set(root: Path, spaceignore: Path, secret_values: dict[str, str]) -> list[str]:
    files = upload_set(root, parse_spaceignore(spaceignore.read_text(encoding="utf-8")))
    if not files:
        raise UploadGuardError("the upload set is empty")
    hits = scan_upload_set(root, files, secret_values)
    if hits:
        shown = "; ".join(f"{h.path}:{h.line} [{h.rule}]" for h in hits[:10])
        raise UploadGuardError(f"secret scan hit, upload aborted: {shown}")
    return files


# --- .env handling (by name, values never printed) -----------------------------------------------
def env_file_path() -> Path:
    override = os.environ.get("JMD_ENV_FILE")
    if override:
        return Path(override)
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True, cwd=ROOT, timeout=15,
        ).stdout.strip()  # fmt: skip
        main_env = Path(common).parent / ".env"
        if main_env.exists():
            return main_env
    except (OSError, subprocess.SubprocessError):
        pass
    return ROOT / ".env"


def parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip()] = v
    return out


def get_setting(env: dict[str, str], name: str) -> str:
    """From the .env file by name, then the process environment."""
    return env.get(name) or os.environ.get(name, "")


def set_env_var(path: Path, name: str, value: str) -> None:
    """Replace or append `NAME=value`, leaving every other line untouched."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    new = f"{name}={value}"
    for i, line in enumerate(lines):
        if line.partition("=")[0].strip() == name:
            lines[i] = new
            break
    else:
        lines.append(new)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def protected_values(env: dict[str, str]) -> dict[str, str]:
    return {n: get_setting(env, n) for n in PROTECTED_NAMES if get_setting(env, n)}


def generate_secrets() -> dict[str, str]:
    return {
        "JWT_SECRET": secrets.token_urlsafe(48),
        "APPROVAL_SECRET": secrets.token_urlsafe(48),
        "DEMO_ADMIN_PASSWORD": secrets.token_urlsafe(24),
    }


# --- Space files ---------------------------------------------------------------------------------
def space_readme() -> str:
    return (
        "---\n"
        "title: junior-ml-dev demo\n"
        "colorFrom: blue\n"
        "colorTo: indigo\n"
        "sdk: docker\n"
        "app_port: 7860\n"
        "pinned: false\n"
        "short_description: Scripted-planner demo of an agent that audits its own ML work\n"
        "---\n\n"
        "# junior-ml-dev demo\n\n"
        "A public demo of a junior ML engineer agent that profiles data, checks for leakage, "
        "trains "
        "models against baselines and reviews its own work. Scripted planner, three small public "
        "samples, no uploads. Source and numbers: "
        f"{REPO_URL}\n"
    )


def space_operations(root: Path, files: list[str]) -> list[tuple[str, bytes]]:
    ops = [(UPLOAD_NAME.get(rel, rel), (root / rel).read_bytes()) for rel in files]
    ops.append(("README.md", space_readme().encode("utf-8")))
    return ops


# --- budget --------------------------------------------------------------------------------------
def budget_script() -> Path | None:
    local = ROOT / "scripts" / "budget.py"
    if local.is_file():
        return local
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True, cwd=ROOT, timeout=15,
        ).stdout.strip()  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    cand = Path(common).parent / "scripts" / "budget.py"
    return cand if cand.is_file() else None


def budget_call(action: str, n: int, reserved: int | None = None) -> bool:
    """`budget.py <action> hf_build n [reserved]`; True when allowed (exit 0). A commit must pass
    `reserved` or the ledger keeps the full reservation."""
    script = budget_script()
    if script is None:
        return False  # no ledger found: fail closed, defer the live step
    res = subprocess.run(
        [sys.executable, str(script), action, "hf_build", str(n)]
        + ([str(reserved)] if reserved is not None else []),
        capture_output=True, text=True, cwd=script.parents[1], timeout=60,
    )  # fmt: skip
    return res.returncode == 0


# --- live deploy ---------------------------------------------------------------------------------
HubApi = Any  # huggingface_hub.HfApi, or a fake in tests


@dataclass
class DeployResult:
    ok: bool
    repo_id: str = ""
    url: str = ""
    stage: str = ""
    attempts: int = 0
    log_tail: list[str] = field(default_factory=list)
    note: str = ""


def space_url(repo_id: str) -> str:
    owner, _, name = repo_id.partition("/")
    return f"https://{owner.lower()}-{name.lower().replace('_', '-')}.hf.space"


def create_space(api: HubApi, user: str, private: bool, token: str, existing: str) -> str:
    """Create `<user>/junior-ml-dev`; fall back to the `-demo` suffix if the name is taken."""
    if existing:
        api.create_repo(existing, token=token, repo_type="space", space_sdk="docker",
                        private=private, exist_ok=True)  # fmt: skip
        return existing
    for name in (SPACE_NAME, f"{SPACE_NAME}-demo"):
        repo_id = f"{user}/{name}"
        try:
            api.create_repo(repo_id, token=token, repo_type="space", space_sdk="docker",
                            private=private, exist_ok=False)  # fmt: skip
            return repo_id
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 409 or "already" in str(exc).lower() or "exist" in str(exc).lower():
                continue
            raise
    raise UploadGuardError("both Space names are taken")


def log_tail(api: HubApi, repo_id: str, token: str, build: bool, n: int = 60) -> list[str]:
    try:
        lines = [str(x) for x in api.fetch_space_logs(repo_id, build=build, token=token)]
    except Exception as exc:
        return [f"(could not fetch logs: {type(exc).__name__})"]
    return lines[-n:]


def poll_build(
    api: HubApi, repo_id: str, token: str, *, attempts: int = MAX_BUILD_ATTEMPTS,
    interval_s: float = 90.0, sleep: Callable[[float], None] = time.sleep,
) -> DeployResult:  # fmt: skip
    stage = ""
    for i in range(1, attempts + 1):
        stage = str(getattr(api.get_space_runtime(repo_id, token=token), "stage", "")).split(".")[
            -1
        ]
        if stage == "RUNNING":
            return DeployResult(True, repo_id, space_url(repo_id), stage, i)
        if stage in {"BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR", "NO_APP_FILE"}:
            tail = log_tail(api, repo_id, token, build=stage != "RUNTIME_ERROR")
            return DeployResult(False, repo_id, space_url(repo_id), stage, i, tail,
                                f"Space entered {stage}")  # fmt: skip
        if i < attempts:
            sleep(interval_s)
    tail = log_tail(api, repo_id, token, build=True)
    return DeployResult(False, repo_id, space_url(repo_id), stage, attempts, tail,
                        f"not RUNNING after {attempts} polls (last stage {stage})")  # fmt: skip


def live_deploy(
    api: HubApi, token: str, ops: list[tuple[str, bytes]], *, private: bool,
    existing_space: str, env_path: Path, sleep: Callable[[float], None] = time.sleep,
    interval_s: float = 90.0, reserve: Callable[[], bool] = lambda: True,
    commit: Callable[[int], object] = lambda n: None,
    op_factory: Callable[[str, bytes], Any] | None = None,
) -> DeployResult:  # fmt: skip
    """whoami -> create Space -> secrets -> [reserve hf_build] -> one commit (= one build) -> poll.

    The budget is reserved only right before the commit that starts a build, and committed with
    the number of builds actually started (0 if the commit never happened)."""
    if op_factory is None:
        from huggingface_hub import (  # type: ignore[import-not-found,unused-ignore]
            CommitOperationAdd,
        )

        def op_factory(path: str, data: bytes) -> Any:
            return CommitOperationAdd(path_in_repo=path, path_or_fileobj=data)

    user = str(api.whoami(token=token)["name"])
    repo_id = create_space(api, user, private, token, existing_space)
    sec = generate_secrets()
    for key in SPACE_SECRETS:
        api.add_space_secret(repo_id, key, sec[key], token=token)
    set_env_var(env_path, "DEMO_ADMIN_PASSWORD", sec["DEMO_ADMIN_PASSWORD"])
    set_env_var(env_path, "DEMO_SPACE_ID", repo_id)
    if not reserve():
        note = "hf_build budget denied or ledger not found: build deferred"
        return DeployResult(False, repo_id, space_url(repo_id), "NOT_BUILT", 0, [], note)
    builds = 0
    try:
        operations = [op_factory(p, b) for p, b in ops]
        api.create_commit(repo_id, operations, token=token, repo_type="space",
                          commit_message="Deploy demo")  # fmt: skip
        builds = 1
    finally:
        commit(builds)
    return poll_build(api, repo_id, token, interval_s=interval_s, sleep=sleep)


# --- verification checklist ----------------------------------------------------------------------
HttpClient = Any  # httpx.Client or a Starlette TestClient


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class VerifyReport:
    checks: list[Check] = field(default_factory=list)
    cold_start_s: float | None = None
    run_seconds: list[float] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    @property
    def sample_run_p50_s(self) -> float | None:
        return round(statistics.median(self.run_seconds), 2) if self.run_seconds else None

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "cold_start_s": None if self.cold_start_s is None else round(self.cold_start_s, 2),
            "sample_run_seconds": [round(x, 2) for x in self.run_seconds],
            "sample_run_p50_s": self.sample_run_p50_s,
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in self.checks],
        }


def _run_sample(
    c: HttpClient, key: str, timeout_s: float, poll_s: float,
    clock: Callable[[], float], sleep: Callable[[float], None],
) -> tuple[bool, float, str, str]:  # fmt: skip
    t0 = clock()
    r = c.post("/demo/api/runs", json={"sample": key})
    if r.status_code != 202:
        return False, clock() - t0, "", f"submit returned {r.status_code}"
    run_id = str(r.json()["run_id"])
    while clock() - t0 < timeout_s + 30:
        st = c.get(f"/demo/api/runs/{run_id}").json()
        if st["status"] not in ("queued", "running"):
            return st["status"] == "done", clock() - t0, run_id, f"status {st['status']}"
        sleep(poll_s)
    return False, clock() - t0, run_id, "still running past the limit"


def verify(
    client: HttpClient, *, runs: int = 3, health_timeout_s: float = 300.0, poll_s: float = 2.0,
    run_limit_s: float = 90.0, clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> VerifyReport:  # fmt: skip
    rep = VerifyReport()

    def add(name: str, ok: object, detail: str = "") -> None:
        rep.checks.append(Check(name, bool(ok), detail))

    t0 = clock()
    status = 0
    while clock() - t0 < health_timeout_s:
        try:
            status = int(client.get("/health").status_code)
        except Exception:
            status = 0
        if status == 200:
            break
        sleep(poll_s)
    rep.cold_start_s = clock() - t0
    add("health 200", status == 200, f"{rep.cold_start_s:.1f} s to first 200")
    if status != 200:
        return rep

    land = client.get("/")
    add("landing page renders", land.status_code == 200 and REPO_URL in land.text,
        f"status {land.status_code}")  # fmt: skip
    admin_status = client.get("/demo/api/admin/runs").status_code
    add(
        "admin endpoint needs auth",
        admin_status == 401,
        f"GET /demo/api/admin/runs -> {admin_status}",
    )
    add("admin audit needs auth", client.get("/v1/audit").status_code == 401, "GET /v1/audit")
    up = client.post("/v1/datasets", files={"file": ("x.csv", b"a,b\n1,2\n")})
    add(
        "upload rejected",
        up.status_code in (403, 404, 405),
        f"POST /v1/datasets -> {up.status_code}",
    )
    dep = client.post("/v1/deploy", json={})
    add(
        "no deploy endpoint", dep.status_code in (403, 404), f"POST /v1/deploy -> {dep.status_code}"
    )

    info = client.get("/demo/api/info").json()
    samples = [s["key"] for s in info.get("samples", [])]
    add("samples available", bool(samples), f"{len(samples)} samples")
    if not samples:
        return rep
    first_run = ""
    for i in range(runs):
        ok, secs, run_id, detail = _run_sample(
            client, samples[i % len(samples)], run_limit_s, poll_s, clock, sleep
        )
        rep.run_seconds.append(secs)
        add(f"sample run {i + 1} finishes < {run_limit_s:.0f} s", ok and secs < run_limit_s,
            f"{secs:.1f} s, {detail}")  # fmt: skip
        first_run = first_run or (run_id if ok else "")
    if first_run:
        r = client.get(f"/demo/api/runs/{first_run}/report")
        add("report renders", r.status_code == 200 and "<html" in r.text.lower(),
            f"status {r.status_code}")  # fmt: skip
    else:
        add("report renders", False, "no finished run")
    return rep


def format_report(rep: VerifyReport) -> str:
    lines = [f"[{'PASS' if c.ok else 'FAIL'}] {c.name}: {c.detail}" for c in rep.checks]
    cold = "n/a" if rep.cold_start_s is None else f"{rep.cold_start_s:.1f} s"
    p50 = "n/a" if rep.sample_run_p50_s is None else f"{rep.sample_run_p50_s:.1f} s"
    lines.append(f"cold start (to first /health 200): {cold}")
    lines.append(f"sample-run p50 over {len(rep.run_seconds)} runs: {p50}")
    lines.append("RESULT: " + ("ALL CHECKS PASSED" if rep.ok else "FAILED"))
    return "\n".join(lines)


# --- CLI -----------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("--dry-run", action="store_true", help="build and scan the upload set only")
    ap.add_argument(
        "--verify", metavar="URL",
        help="run the verification checklist against URL ('auto' = the Space in DEMO_SPACE_ID)",
    )  # fmt: skip
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--json-out", type=Path, default=None)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--env-file", type=Path, default=None)
    ns = ap.parse_args(argv)

    if ns.verify:
        import httpx

        env = parse_env(ns.env_file or env_file_path())
        target = ns.verify
        if target == "auto":
            space_id = get_setting(env, "DEMO_SPACE_ID")
            if not space_id:
                print("no DEMO_SPACE_ID in .env: deploy first, or pass the URL", file=sys.stderr)
                return 2
            target = space_url(space_id)
        with httpx.Client(base_url=target.rstrip("/"), timeout=60, follow_redirects=True) as c:
            if get_setting(env, "DEMO_PRIVATE") == "1" and get_setting(env, "HF_TOKEN"):
                # a private Space is only reachable with the token
                c.headers["Authorization"] = f"Bearer {get_setting(env, 'HF_TOKEN')}"
            rep = verify(c, runs=ns.runs)
        print(format_report(rep))
        if ns.json_out:
            ns.json_out.parent.mkdir(parents=True, exist_ok=True)
            ns.json_out.write_text(json.dumps(rep.to_json(), indent=1), encoding="utf-8")
        return 0 if rep.ok else 1

    env_path = ns.env_file or env_file_path()
    env = parse_env(env_path)
    token = get_setting(env, "HF_TOKEN")
    if not ns.dry_run and not token:
        print("HF_TOKEN missing")
        return 0
    try:
        files = check_upload_set(ns.root, ns.root / ".spaceignore", protected_values(env))
    except UploadGuardError as exc:
        print(f"ABORT: {exc}", file=sys.stderr)
        return 2
    print(f"upload set: {len(files)} files, secret scan clean")
    if ns.dry_run:
        return 0
    from huggingface_hub import HfApi  # type: ignore[import-not-found,unused-ignore]

    private = get_setting(env, "DEMO_PRIVATE") == "1"
    try:
        res = live_deploy(
            HfApi(), token, space_operations(ns.root, files), private=private,
            existing_space=get_setting(env, "DEMO_SPACE_ID"), env_path=env_path,
            reserve=lambda: budget_call("reserve", 1), commit=lambda n: budget_call("commit", n, 1),
        )  # fmt: skip
    except Exception as exc:  # network / API error: report it without a traceback or any secret
        status = getattr(getattr(exc, "response", None), "status_code", "")
        text = str(exc).strip().splitlines()
        print(f"DEPLOY FAILED: {type(exc).__name__} {status}", file=sys.stderr)
        print(text[-1] if text else "", file=sys.stderr)
        if status == 402:
            print("Docker Spaces need an HF PRO subscription (or a paid hardware tier); "
                  "re-run after upgrading the account.", file=sys.stderr)  # fmt: skip
        return 1
    if not res.ok:
        print(f"DEPLOY FAILED: {res.note}", file=sys.stderr)
        print("\n".join(res.log_tail), file=sys.stderr)
        return 1
    print(f"Space is RUNNING: {res.url}  (repo {res.repo_id})")
    print(f"next: python scripts/deploy_space.py --verify {res.url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
