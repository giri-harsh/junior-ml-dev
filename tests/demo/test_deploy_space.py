"""scripts/deploy_space.py: upload guard, secrets, token handling, live flow (fake Hub), verify."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.demo import install
from scripts import deploy_space as ds
from tests.demo.helpers import FakeExecutor, fresh_app, make_settings

REPO = Path(__file__).resolve().parents[2]

# built from pieces so this file never contains a literal that looks like a real key
FAKE_GROQ = "gsk_" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
FAKE_HF = "hf_" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
FAKE_AWS = "AKIA" + "ABCDEFGHIJKLMNOP"


def tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


ALLOW_ALL = "*\n!apps/**\n!docs/**\n!benchmarks/**\n!tests/**\n!.env*\n!Dockerfile.space\n"


# --- the allowlist ---------------------------------------------------------------------------
def test_spaceignore_is_a_deny_by_default_allowlist(tmp_path: Path) -> None:
    tree(tmp_path, {"apps/a.py": "x=1\n", "apps/__pycache__/a.pyc": "z", "notes.txt": "n",
                    "scripts/x.py": "y=1\n", ".spaceignore": "*\n!apps/**\n**/__pycache__/**\n*.pyc\n"})  # fmt: skip
    rules = ds.parse_spaceignore((tmp_path / ".spaceignore").read_text(encoding="utf-8"))
    assert ds.upload_set(tmp_path, rules) == ["apps/a.py"]


def test_the_real_upload_set_is_clean_and_complete() -> None:
    files = ds.check_upload_set(REPO, REPO / ".spaceignore", {})
    s = set(files)
    for need in ("Dockerfile.space", "pyproject.toml", "uv.lock", "docs/METRICS.md",
                 "apps/api/main.py", "apps/api/demo/__init__.py", "apps/web/demo/landing.template.html",
                 "apps/web/dist/index.html", "harness/agent/runner.py", "benchmarks/metrics.py"):  # fmt: skip
        assert need in s, need
    for rel in s:
        assert ds.forbidden_reason(rel) is None, rel
        assert not rel.startswith(("tests/", "scripts/", "docs/ws/", ".github/", "data/"))
    assert "docs/NEEDS_HARSH.md" not in s and ".env" not in s
    assert not [r for r in s if "cassette" in r or r.startswith("benchmarks/results")]
    ops = dict(ds.space_operations(REPO, files))
    assert "Dockerfile" in ops and "Dockerfile.space" not in ops
    assert ops["README.md"].startswith(b"---\n") and b"sdk: docker" in ops["README.md"]
    assert b"app_port: 7860" in ops["README.md"]


@pytest.mark.parametrize(
    "rel",
    [".env", ".env.local", "tests/cassettes/c.jsonl", "x/cassettes/y.txt", "benchmarks/results/a.json",
     "benchmarks/critic_set_v6.json", "docs/NEEDS_HARSH.md", "docs/ws/B.md", "data/runs.db",
     "apps/api/state.db", "keys/server.pem"],
)  # fmt: skip
def test_forbidden_files_abort_the_upload_even_if_the_allowlist_includes_them(
    tmp_path: Path, rel: str
) -> None:
    tree(tmp_path, {"apps/ok.py": "x=1\n", rel: "harmless text\n", ".spaceignore": "*\n!**\n"})
    with pytest.raises(ds.UploadGuardError, match="forbidden"):
        ds.check_upload_set(tmp_path, tmp_path / ".spaceignore", {})


# --- the secret scan -------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("planted", "rule"),
    [
        (f'key = "{FAKE_GROQ}"\n', "groq-key"),
        (f"token: {FAKE_HF}\n", "huggingface-token"),
        (f"aws = '{FAKE_AWS}'\n", "aws-access-key"),
        ("-----BEGIN " + "PRIVATE KEY-----\n", "private-key"),
    ],
)
def test_scanner_catches_a_planted_fake_secret_and_never_echoes_it(
    tmp_path: Path, planted: str, rule: str
) -> None:
    tree(tmp_path, {"apps/ok.py": "x = 1\n", "apps/leak.py": "import os\n" + planted,
                    ".spaceignore": "*\n!apps/**\n"})  # fmt: skip
    with pytest.raises(ds.UploadGuardError) as ei:
        ds.check_upload_set(tmp_path, tmp_path / ".spaceignore", {})
    msg = str(ei.value)
    assert "apps/leak.py:2" in msg and rule in msg
    for frag in (FAKE_GROQ, FAKE_HF, FAKE_AWS):
        assert frag not in msg


def test_scanner_catches_the_literal_value_of_a_local_secret(tmp_path: Path) -> None:
    tree(
        tmp_path,
        {"apps/cfg.py": 'NOTE = "zz-local-secret-value-12345"\n', ".spaceignore": "*\n!apps/**\n"},
    )
    with pytest.raises(ds.UploadGuardError) as ei:
        ds.check_upload_set(
            tmp_path, tmp_path / ".spaceignore", {"GROQ_API_KEY": "zz-local-secret-value-12345"}
        )
    assert "literal-value:GROQ_API_KEY" in str(ei.value) and "zz-local" not in str(ei.value)
    # a clean tree passes
    (tmp_path / "apps" / "cfg.py").write_text("NOTE = 1\n", encoding="utf-8")
    assert ds.check_upload_set(
        tmp_path, tmp_path / ".spaceignore", {"GROQ_API_KEY": "zz-local-secret-value-12345"}
    )


# --- token handling ---------------------------------------------------------------------------
def test_exits_cleanly_with_a_message_when_hf_token_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=not-used\nDEMO_PRIVATE=1\n", encoding="utf-8")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    assert ds.main(["--env-file", str(env)]) == 0
    assert capsys.readouterr().out.strip() == "HF_TOKEN missing"
    assert env.read_text(encoding="utf-8") == "GROQ_API_KEY=not-used\nDEMO_PRIVATE=1\n"  # untouched


def test_script_as_a_subprocess_without_a_token(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SOMETHING=1\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "HF_TOKEN"}
    env.update(JMD_ENV_FILE=str(env_file), PYTHONUTF8="1")
    res = subprocess.run([sys.executable, str(REPO / "scripts" / "deploy_space.py")],
                         capture_output=True, text=True, env=env, cwd=REPO, timeout=120)  # fmt: skip
    assert res.returncode == 0 and res.stdout.strip() == "HF_TOKEN missing"


def test_env_helpers_read_by_name_and_update_in_place(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text("# c\nHF_TOKEN='tok-123'\nOTHER=1\nDEMO_ADMIN_PASSWORD=old\n", encoding="utf-8")
    e = ds.read_env_names(p, ds.SETTING_NAMES)
    assert e == {"HF_TOKEN": "tok-123"}  # allowlist loader: OTHER=1 and the password are skipped
    assert ds.read_env_names(p, ("OTHER",)) == {"OTHER": "1"}
    ds.set_env_var(p, "DEMO_ADMIN_PASSWORD", "new")
    ds.set_env_var(p, "DEMO_SPACE_ID", "me/space")
    assert (
        p.read_text(encoding="utf-8")
        == "# c\nHF_TOKEN='tok-123'\nOTHER=1\nDEMO_ADMIN_PASSWORD=new\nDEMO_SPACE_ID=me/space\n"
    )


def test_generated_secrets_are_fresh_and_strong() -> None:
    a, b = ds.generate_secrets(), ds.generate_secrets()
    assert set(a) == {"JWT_SECRET", "APPROVAL_SECRET", "DEMO_ADMIN_PASSWORD"}
    assert a != b and all(len(v) >= 30 for v in a.values()) and len(set(a.values())) == 3


# --- the live flow against a fake Hub -----------------------------------------------------------
class FakeStage:
    def __init__(self, stage: str) -> None:
        self.stage = stage


class FakeApi:
    def __init__(self, stages: list[str], taken: set[str] | None = None) -> None:
        self.stages = list(stages)
        self.taken = taken or set()
        self.created: list[tuple[str, dict[str, Any]]] = []
        self.secrets: dict[str, str] = {}
        self.commits: list[Any] = []
        self.polls = 0

    def whoami(self, token: Any = None) -> dict[str, Any]:
        return {"name": "someone"}

    def create_repo(self, repo_id: str, **kw: Any) -> None:
        if repo_id in self.taken and not kw.get("exist_ok"):
            raise RuntimeError("409 Conflict: You already created this space repo")
        self.created.append((repo_id, kw))

    def add_space_secret(self, repo_id: str, key: str, value: str, **kw: Any) -> None:
        self.secrets[key] = value

    def create_commit(self, repo_id: str, operations: Any, **kw: Any) -> None:
        self.commits.append(list(operations))

    def get_space_runtime(self, repo_id: str, **kw: Any) -> FakeStage:
        self.polls += 1
        return FakeStage(self.stages.pop(0) if len(self.stages) > 1 else self.stages[0])

    def fetch_space_logs(self, repo_id: str, **kw: Any) -> list[str]:
        return [f"line {i}" for i in range(200)]


def run_live(api: FakeApi, tmp_path: Path, **kw: Any) -> ds.DeployResult:
    env = tmp_path / ".env"
    env.write_text("HF_TOKEN=tok\n", encoding="utf-8")
    ops = [("Dockerfile", b"FROM x\n"), ("README.md", b"r\n")]
    return ds.live_deploy(api, "tok", ops, private=kw.pop("private", False), existing_space="",
        op_factory=lambda p, b: (p, b),
                          env_path=env, sleep=lambda s: None, **kw)  # fmt: skip


def test_live_deploy_sets_only_three_fresh_secrets_and_writes_the_password_locally(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeApi(["BUILDING", "BUILDING", "RUNNING"])
    calls: list[str] = []
    res = run_live(api, tmp_path, private=True, reserve=lambda: calls.append("reserve") or True,
                   commit=lambda n: calls.append(f"commit{n}"))  # fmt: skip
    assert res.ok and res.stage == "RUNNING" and res.attempts == 3
    assert set(api.secrets) == {"JWT_SECRET", "APPROVAL_SECRET", "DEMO_ADMIN_PASSWORD"}
    assert not any(
        "GROQ" in k or "GEMINI" in k or "E2B" in k or "HF_TOKEN" in k for k in api.secrets
    )
    assert api.created[0][0] == "someone/junior-ml-dev"
    assert api.created[0][1]["private"] is True and api.created[0][1]["space_sdk"] == "docker"
    assert calls == ["reserve", "commit1"] and len(api.commits) == 1
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert f"DEMO_ADMIN_PASSWORD={api.secrets['DEMO_ADMIN_PASSWORD']}" in env_text
    assert "DEMO_SPACE_ID=someone/junior-ml-dev" in env_text
    out = capsys.readouterr()
    assert api.secrets["DEMO_ADMIN_PASSWORD"] not in out.out + out.err


def test_live_deploy_falls_back_to_the_demo_suffix_when_the_name_is_taken(tmp_path: Path) -> None:
    api = FakeApi(["RUNNING"], taken={"someone/junior-ml-dev"})
    res = run_live(api, tmp_path)
    assert res.ok and res.repo_id == "someone/junior-ml-dev-demo"
    assert res.url == "https://someone-junior-ml-dev-demo.hf.space"


def test_budget_denied_means_no_build_is_started(tmp_path: Path) -> None:
    api = FakeApi(["RUNNING"])
    res = run_live(api, tmp_path, reserve=lambda: False)
    assert not res.ok and "budget" in res.note and api.commits == []


def test_build_polling_is_bounded_and_failures_return_the_last_60_log_lines(tmp_path: Path) -> None:
    stuck = FakeApi(["BUILDING"])
    res = run_live(stuck, tmp_path)
    assert not res.ok and res.attempts == 6 and stuck.polls == 6
    assert len(res.log_tail) == 60 and res.log_tail[-1] == "line 199"
    broken = FakeApi(["BUILDING", "BUILD_ERROR"])
    res = run_live(broken, tmp_path)
    assert (
        not res.ok and res.stage == "BUILD_ERROR" and res.attempts == 2 and len(res.log_tail) == 60
    )


# --- the verification checklist ---------------------------------------------------------------
def test_verify_passes_against_a_local_demo_app(demo_env: Path, tmp_path: Path) -> None:
    app = fresh_app()
    service = install(app, make_settings(tmp_path, ip_runs_per_window=20), FakeExecutor(delay=0.05))
    assert service is not None
    (service.s.site_dir).mkdir(parents=True, exist_ok=True)
    (service.s.site_dir / "index.html").write_text(f"<html>{ds.REPO_URL}</html>", encoding="utf-8")
    with TestClient(app, base_url="https://testserver") as c:  # lifespan starts the worker
        rep = ds.verify(c, runs=3, poll_s=0.05, health_timeout_s=10)
    names = {x.name: x.ok for x in rep.checks}
    assert rep.ok, ds.format_report(rep)
    for n in ("health 200", "landing page renders", "admin endpoint needs auth", "admin audit needs auth",
              "upload rejected", "no deploy endpoint", "report renders"):  # fmt: skip
        assert names[n], n
    assert (
        len(rep.run_seconds) == 3
        and rep.sample_run_p50_s is not None
        and rep.cold_start_s is not None
    )
    assert (
        sorted(rep.run_seconds)[1] == rep.sample_run_p50_s
        or abs(sorted(rep.run_seconds)[1] - rep.sample_run_p50_s) < 0.01
    )
    assert "ALL CHECKS PASSED" in ds.format_report(rep)
    assert rep.to_json()["ok"] is True


def test_verify_auto_needs_a_recorded_space(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEMO_SPACE_ID", raising=False)
    env = tmp_path / ".env"
    env.write_text("OTHER=1\n", encoding="utf-8")
    assert ds.main(["--verify", "auto", "--env-file", str(env)]) == 2
    assert "DEMO_SPACE_ID" in capsys.readouterr().err
    assert ds.space_url("Someone/junior-ml-dev") == "https://someone-junior-ml-dev.hf.space"


def test_verify_fails_against_an_app_that_accepts_uploads() -> None:
    app = fresh_app()  # the regular API, no demo guard
    app.add_api_route("/health", lambda: {"status": "ok"})
    with TestClient(app) as c:
        rep = ds.verify(c, runs=1, poll_s=0.01, health_timeout_s=2)
    failed = {x.name for x in rep.checks if not x.ok}
    assert not rep.ok and "upload rejected" in failed


def test_verify_reports_an_unreachable_service_instead_of_inventing_numbers() -> None:
    class Down:
        def get(self, url: str, **kw: Any) -> Any:
            raise ConnectionError("down")

        post = get

    now = [0.0]

    def clock() -> float:
        now[0] += 1.0
        return now[0]

    rep = ds.verify(
        Down(), runs=3, health_timeout_s=5, poll_s=0.0, clock=clock, sleep=lambda s: None
    )
    assert not rep.ok and rep.run_seconds == [] and rep.sample_run_p50_s is None
    assert [c.name for c in rep.checks] == ["health 200"]
