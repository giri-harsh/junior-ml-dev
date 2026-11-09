"""Build, check, publish and verify the static demo site (GitHub Pages).

    python scripts/deploy_static.py build [--reuse]   # pre-compute 3 runs (--reuse: cached), site/
    python scripts/deploy_static.py check             # allowlist, secret and path-leak scan
    python scripts/deploy_static.py publish [--dry-run]
    python scripts/deploy_static.py verify [URL]      # crawl the live site, compare with site/

`publish` creates the PUBLIC repo giri-harsh/junior-ml-dev-demo (only the contents of site/ are
ever pushed: no source code, no .env, no cassettes, no benchmark data), enables GitHub Pages from
`main` at `/`, waits for the URL and runs `verify`. The main source repository is never touched
and never made public. CI usage (the Pages build workflow) is reserved in scripts/budget.py first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.deploy_space import (  # noqa: E402
    PROTECTED_NAMES,
    UploadGuardError,
    budget_script,
    env_file_path,
    forbidden_reason,
    read_env_names,
    scan_upload_set,
)

OWNER = "giri-harsh"
REPO_NAME = "junior-ml-dev-demo"
REPO = f"{OWNER}/{REPO_NAME}"
PAGES_URL = f"https://{OWNER}.github.io/{REPO_NAME}/"
SOURCE_REPO = f"{OWNER}/junior-ml-dev"
SITE_DIR = ROOT / "site"
CACHE_DIR = ROOT / "data" / "demo" / "static_runs"
ALLOWED_SUFFIX = {".html", ".css", ".svg", ".txt", ".md"}
ALLOWED_NAMES = {".nojekyll"}
# Text that must never appear in published pages: local paths, user names, internal docs.
LEAK_MARKERS = (
    "C:\\Users", "C:/Users", "/Users/", "/home/", "AppData", "worktrees", "2006h",
    "NEEDS_HARSH", "PROGRESS.md", "AUTOPILOT", "Prod_rag", ".env",
)  # fmt: skip
# Pattern leaks are reported by label only, never by the matched text.
LEAK_PATTERNS: dict[str, re.Pattern[str]] = {
    "email-address": re.compile(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
    ),
}
AUTHOR = ("Harsh Giri", "2006.harshgiri@gmail.com")


# --- guard ---------------------------------------------------------------------------------------
def site_files(site_dir: Path) -> list[str]:
    """Every file under site_dir; raises if one has a type that a static site never needs."""
    files = sorted(p.relative_to(site_dir).as_posix() for p in site_dir.rglob("*") if p.is_file())
    bad = [f for f in files if Path(f).suffix.lower() not in ALLOWED_SUFFIX
           and Path(f).name not in ALLOWED_NAMES]  # fmt: skip
    if bad:
        raise UploadGuardError(f"refusing to publish unexpected file types: {', '.join(bad[:10])}")
    return files


def leak_hits(site_dir: Path, files: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for rel in files:
        text = (site_dir / rel).read_text(encoding="utf-8", errors="replace")
        out.extend((rel, m) for m in LEAK_MARKERS if m in text)
        out.extend((rel, label) for label, pat in LEAK_PATTERNS.items() if pat.search(text))
    return out


def check_site(site_dir: Path, secret_values: dict[str, str] | None = None) -> list[str]:
    """Allowlist, hard-deny, secret-pattern, literal-secret and local-path scans. Returns the
    files; raises UploadGuardError on any finding (naming the rule and file, never the match)."""
    if not site_dir.is_dir():
        raise UploadGuardError(f"{site_dir} does not exist: run `build` first")
    files = site_files(site_dir)
    if "index.html" not in files:
        raise UploadGuardError("site/index.html is missing")
    bad = [(f, why) for f in files if (why := forbidden_reason(f))]
    if bad:
        raise UploadGuardError("forbidden files: " + "; ".join(f"{f} ({w})" for f, w in bad[:10]))
    hits = scan_upload_set(site_dir, files, secret_values)
    if hits:
        shown = "; ".join(f"{h.path}:{h.line} [{h.rule}]" for h in hits[:10])
        raise UploadGuardError(f"secret scan hit, publish aborted: {shown}")
    leaks = leak_hits(site_dir, files)
    if leaks:
        shown = "; ".join(f"{f} [{m}]" for f, m in leaks[:10])
        raise UploadGuardError(f"local-path or internal-doc marker in published files: {shown}")
    return files


# --- budget --------------------------------------------------------------------------------------
def ledger(action: str, kind: str, n: int, reserved: int | None = None) -> bool:
    script = budget_script()
    if script is None:
        return False  # fail closed
    cmd = [sys.executable, str(script), action, kind, str(n)]
    if reserved is not None:
        cmd.append(str(reserved))
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=script.parents[1], timeout=60)
    return res.returncode == 0


# --- process helpers -----------------------------------------------------------------------------
def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    res = subprocess.run(
        cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=300, check=False
    )
    if check and res.returncode != 0:
        tail = (res.stderr or res.stdout).strip().splitlines()[-3:]
        raise RuntimeError(f"{' '.join(cmd[:3])} failed ({res.returncode}): {' | '.join(tail)}")
    return res


def repo_visibility(repo: str = SOURCE_REPO) -> bool | None:
    """True if the source repo is private, False if public, None if unknown (no gh / no access)."""
    try:
        res = run(["gh", "repo", "view", repo, "--json", "isPrivate"], check=False)
        return bool(json.loads(res.stdout)["isPrivate"]) if res.returncode == 0 else None
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return None


# --- build ---------------------------------------------------------------------------------------
def build(
    site_dir: Path, cache_dir: Path, *, reuse: bool, data_dir: Path | None = None
) -> list[str]:
    from apps.space.static_site import build_site, precompute_runs

    if not reuse:
        data = data_dir or ROOT / "data" / "demo" / "samples"
        if not (data / "manifest.json").is_file():
            from apps.api.demo.prepare import prepare_samples

            prepare_samples(data)
        precompute_runs(data, cache_dir)
    metrics = (ROOT / "docs" / "METRICS.md").read_text(encoding="utf-8")
    if site_dir.exists():  # clear the contents, not the directory (a server may be using it)
        for child in site_dir.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    written = build_site(site_dir, cache_dir, metrics, repo_private=repo_visibility())
    return written


# --- publish -------------------------------------------------------------------------------------
def git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_AUTHOR_NAME=AUTHOR[0], GIT_AUTHOR_EMAIL=AUTHOR[1],
        GIT_COMMITTER_NAME=AUTHOR[0], GIT_COMMITTER_EMAIL=AUTHOR[1],
    )  # fmt: skip
    return env


def push_site(
    site_dir: Path, files: list[str], repo: str = REPO, remote_url: str | None = None
) -> str:
    """Fresh single-commit history containing exactly `files`, pushed to main of the demo repo."""
    work = Path(tempfile.mkdtemp(prefix="jmd-site-"))
    try:
        for rel in files:
            dest = work / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(site_dir / rel, dest)
        env = git_env()
        run(["git", "init", "-q", "-b", "main"], cwd=work, env=env)
        run(["git", "add", "-A"], cwd=work, env=env)
        run(["git", "commit", "-q", "-m", "Publish static demo site"], cwd=work, env=env)
        sha = run(["git", "rev-parse", "HEAD"], cwd=work, env=env).stdout.strip()
        url = remote_url or f"https://github.com/{repo}.git"
        run(["git", "remote", "add", "origin", url], cwd=work, env=env)
        helper = "credential.helper=!gh auth git-credential"
        run(["git", "-c", helper, "push", "-q", "--force", "origin", "main"], cwd=work, env=env)
        return sha
    finally:
        shutil.rmtree(work, ignore_errors=True)


def enable_pages(repo: str = REPO) -> None:
    body = ["-f", "source[branch]=main", "-f", "source[path]=/"]
    res = run(["gh", "api", "-X", "POST", f"repos/{repo}/pages", *body], check=False)
    if res.returncode != 0:  # already enabled: update the source instead
        run(["gh", "api", "-X", "PUT", f"repos/{repo}/pages", *body])


def ensure_repo(repo: str = REPO) -> bool:
    """Create the public demo repo if missing. Returns True when it was created now."""
    if run(["gh", "repo", "view", repo, "--json", "name"], check=False).returncode == 0:
        return False
    run([
        "gh", "repo", "create", repo, "--public",
        "--description", "Static demo site for junior-ml-dev (pre-computed runs, verified numbers)",
    ])  # fmt: skip
    return True


# --- verify --------------------------------------------------------------------------------------
@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class SiteReport:
    checks: list[Check] = field(default_factory=list)
    latency_ms: list[float] = field(default_factory=list)
    pages: int = 0

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    def to_json(self) -> dict[str, Any]:
        lat = sorted(self.latency_ms)
        return {
            "ok": self.ok,
            "pages_fetched": self.pages,
            "latency_ms_p50": round(statistics.median(lat), 1) if lat else None,
            "latency_ms_max": round(lat[-1], 1) if lat else None,
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in self.checks],
        }


def format_site_report(rep: SiteReport) -> str:
    lines = [f"[{'PASS' if c.ok else 'FAIL'}] {c.name}: {c.detail}" for c in rep.checks]
    j = rep.to_json()
    lines.append(f"page fetch latency: p50 {j['latency_ms_p50']} ms, max {j['latency_ms_max']} ms "
                 f"over {len(rep.latency_ms)} requests")  # fmt: skip
    lines.append("RESULT: " + ("ALL CHECKS PASSED" if rep.ok else "FAILED"))
    return "\n".join(lines)


HREF = re.compile(r"""(?:href|src)=["']([^"'#]+)["']""")


def internal_links(page_html: str, page_url: str, base: str) -> list[str]:
    from urllib.parse import urljoin, urlparse

    out = []
    for raw in HREF.findall(page_html):
        if raw.startswith(("mailto:", "javascript:", "data:")):
            continue
        full = urljoin(page_url, raw)
        if urlparse(full).netloc == urlparse(base).netloc and full.startswith(base):
            out.append(full.split("?")[0])
    return sorted(set(out))


def verify_site(
    client: Any, base: str, site_dir: Path, *, repeats: int = 5,
    clock: Callable[[], float] = time.perf_counter,
) -> SiteReport:  # fmt: skip
    """Fetch every local file from the live URL (hash must match), crawl internal links, check
    the pages that matter, and time page fetches. `client.get(url)` must return status_code/text."""
    rep = SiteReport()
    base = base if base.endswith("/") else base + "/"

    def add(name: str, ok: object, detail: str = "") -> None:
        rep.checks.append(Check(name, bool(ok), detail))

    def get(url: str) -> Any:
        t0 = clock()
        r = client.get(url)
        rep.latency_ms.append((clock() - t0) * 1000)
        rep.pages += 1
        return r

    files = site_files(site_dir)
    mismatch, missing = [], []
    for rel in files:
        if rel in {"README.md", ".nojekyll", "404.html"}:
            continue  # not served as pages worth hashing (.nojekyll is empty)
        r = get(base + rel)
        if r.status_code != 200:
            missing.append(f"{rel} -> {r.status_code}")
            continue
        local = (site_dir / rel).read_bytes()
        live = getattr(r, "content", r.text.encode("utf-8"))
        if hashlib.sha256(live).hexdigest() != hashlib.sha256(local).hexdigest():
            mismatch.append(rel)
    add(
        "every built page is served (200)",
        not missing,
        "; ".join(missing[:5]) or f"{len(files)} files",
    )
    add(
        "served bytes equal the built site", not mismatch, ", ".join(mismatch[:5]) or "sha256 match"
    )

    index = get(base + "index.html")
    add(
        "home renders",
        index.status_code == 200 and "<h1>" in index.text,
        f"status {index.status_code}",
    )
    scores = re.findall(
        r"\d\.\d{3} \[[^\]]+\]", (site_dir / "results.html").read_text(encoding="utf-8")
    )
    results = get(base + "results.html")
    shown = bool(scores) and all(sc in results.text for sc in scores[:2])
    add("results page shows the headline numbers from METRICS.md", shown, f"{len(scores)} cells")
    arch = get(base + "architecture.html")
    add("architecture page renders its diagram", "<svg" in arch.text, f"status {arch.status_code}")
    runs = sorted({f.split("/")[1] for f in files if f.startswith("runs/")})
    add("example runs present", len(runs) >= 3, ", ".join(runs))
    for key in runs:
        rep_page = get(f"{base}runs/{key}/report.html")
        good = rep_page.status_code == 200 and "planner=scripted" in rep_page.text
        add(f"report renders: {key}", good, f"status {rep_page.status_code}")

    broken = []
    seen: set[str] = set()
    for page_url in [base + "index.html", base + "results.html", base + "architecture.html"] + [
        f"{base}runs/{k}/index.html" for k in runs
    ]:
        resp = get(page_url)
        for link in internal_links(resp.text, page_url, base):
            if link in seen:
                continue
            seen.add(link)
            if get(link).status_code != 200:
                broken.append(link)
    add("no broken internal links", not broken, f"{len(seen)} links; " + ", ".join(broken[:5]))
    for _ in range(repeats):
        get(base + "index.html")
    return rep


def wait_for_url(
    client: Any, url: str, *, attempts: int = 30, interval_s: float = 15.0,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bool, int]:  # fmt: skip
    status = 0
    for i in range(1, attempts + 1):
        try:
            status = int(client.get(url).status_code)
        except Exception:
            status = 0
        if status == 200:
            return True, i
        if i < attempts:
            sleep(interval_s)
    return False, attempts


def wait_for_match(
    client: Any, url: str, expected: bytes, *, attempts: int = 40, interval_s: float = 15.0,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bool, int]:  # fmt: skip
    """Poll until `url` serves exactly `expected`. A bare 200 is not enough on a redeploy: the
    previous version keeps answering 200 until the Pages workflow finishes."""
    want = hashlib.sha256(expected).hexdigest()
    for i in range(1, attempts + 1):
        try:
            r = client.get(url)
            got = getattr(r, "content", r.text.encode("utf-8"))
            if int(r.status_code) == 200 and hashlib.sha256(got).hexdigest() == want:
                return True, i
        except Exception:
            pass
        if i < attempts:
            sleep(interval_s)
    return False, attempts


def workflow_runs(repo: str = REPO) -> int:
    res = run(
        ["gh", "run", "list", "-R", repo, "--limit", "100", "--json", "databaseId"], check=False
    )
    try:
        return len(json.loads(res.stdout or "[]"))
    except ValueError:
        return 0


# --- CLI -----------------------------------------------------------------------------------------
def make_client() -> Any:
    import httpx

    return httpx.Client(timeout=30, follow_redirects=True, headers={"user-agent": "demo-verify"})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("command", choices=["build", "check", "publish", "verify"])
    ap.add_argument("url", nargs="?", default=PAGES_URL)
    ap.add_argument("--reuse", action="store_true", help="build: reuse cached pre-computed runs")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--site", type=Path, default=SITE_DIR)
    ap.add_argument("--json-out", type=Path, default=None)
    ns = ap.parse_args(argv)

    scan_env = read_env_names(env_file_path(), PROTECTED_NAMES)  # values used only to scan
    secrets_for_scan = {k: v for k, v in scan_env.items() if v}

    if ns.command == "build":
        written = build(ns.site, CACHE_DIR, reuse=ns.reuse)
        print(f"wrote {len(written)} files to {ns.site}")
        files = check_site(ns.site, secrets_for_scan)
        print(f"check: {len(files)} files clean")
        return 0
    try:
        if ns.command in {"check", "publish"}:
            files = check_site(ns.site, secrets_for_scan)
            print(f"check: {len(files)} files clean")
            if ns.command == "check":
                return 0
    except UploadGuardError as exc:
        print(f"ABORT: {exc}", file=sys.stderr)
        return 2

    if ns.command == "publish":
        if ns.dry_run:
            return 0
        if not ledger("reserve", "ci_runs", 2) or not ledger("reserve", "ci_minutes", 3):
            ledger("commit", "ci_runs", 0, 2)
            print("ci budget denied: publish deferred (re-run later)", file=sys.stderr)
            return 0
        sha = ""
        try:
            created = ensure_repo()
            runs_before = workflow_runs() if not created else 0
            sha = push_site(ns.site, files)
            enable_pages()
        except Exception as exc:
            print(f"PUBLISH FAILED: {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
            ledger("commit", "ci_runs", 0, 2)
            ledger("commit", "ci_minutes", 0, 3)
            return 1
        print(
            f"pushed {sha[:10]} to {REPO} ({'created' if created else 'existing'}); Pages enabled"
        )
        client = make_client()
        base = ns.url if ns.url.endswith("/") else ns.url + "/"
        ok, tries = wait_for_match(
            client, base + "index.html", (ns.site / "index.html").read_bytes()
        )
        new_runs = max(1, workflow_runs() - runs_before)  # runs this publish caused
        ledger("commit", "ci_runs", new_runs, 2)
        ledger("commit", "ci_minutes", 2, 3)
        if not ok:
            print(f"new version not served after {tries} polls: {ns.url}", file=sys.stderr)
            return 1
        print(f"live (new version) after {tries} poll(s): {ns.url}")
        ns.command = "verify"

    rep = verify_site(make_client(), ns.url, ns.site)
    print(format_site_report(rep))
    if ns.json_out:
        ns.json_out.parent.mkdir(parents=True, exist_ok=True)
        ns.json_out.write_text(json.dumps(rep.to_json(), indent=1), encoding="utf-8")
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
