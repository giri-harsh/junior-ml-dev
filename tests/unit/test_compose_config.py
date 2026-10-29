"""Static checks of the compose file (the only validation possible without Docker)."""

from __future__ import annotations

from pathlib import Path

import yaml

COMPOSE = Path("deploy/compose/docker-compose.yml")


def _load() -> dict:  # type: ignore[type-arg]
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_app_profile_has_all_five_services_with_healthchecks() -> None:
    svcs = _load()["services"]
    for name in ("postgres", "redis", "minio", "api", "worker"):
        assert name in svcs, name
        assert "healthcheck" in svcs[name], f"{name} needs a healthcheck"
        assert "app" in svcs[name]["profiles"] or name in {"api", "worker"}
    for name in ("api", "worker"):
        deps = svcs[name]["depends_on"]
        assert {d: v["condition"] for d, v in deps.items()} == dict.fromkeys(
            ("postgres", "redis", "minio"), "service_healthy"
        )


def test_state_lives_in_named_volumes_and_ports_are_remappable() -> None:
    cfg = _load()
    assert {"appdata", "pgdata", "miniodata"} <= set(cfg["volumes"])
    for name in ("postgres", "redis", "minio", "api"):
        port = cfg["services"][name]["ports"][0]
        assert "${" in port, f"{name} port should be remappable via .env"
    for name in ("api", "worker"):
        assert cfg["services"][name]["volumes"] == ["appdata:/app/data"]


def test_secrets_are_required_not_defaulted() -> None:
    env = _load()["services"]["api"]["environment"]
    assert env["JWT_SECRET"].startswith("${JWT_SECRET:?")
    assert env["APPROVAL_SECRET"].startswith("${APPROVAL_SECRET:?")


def test_worker_uses_arq_and_postgres_runs() -> None:
    svc = _load()["services"]["worker"]
    assert svc["command"][0] == "arq" and svc["environment"]["QUEUE_BACKEND"] == "arq"
    assert svc["environment"]["RUNS_DATABASE_URL"].startswith("postgresql+psycopg://")


def test_dockerfile_and_ignore_exist_and_exclude_data() -> None:
    assert "uv sync --frozen" in Path("deploy/compose/app.Dockerfile").read_text()
    ignore = Path(".dockerignore").read_text().split()
    assert {"data", "scorer_data", ".env"} <= set(ignore)


def test_ci_workflow_runs_lint_types_unit_tests_and_gitleaks() -> None:
    wf = yaml.safe_load(Path(".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = " ".join(str(s) for s in wf["jobs"]["checks"]["steps"])
    for needle in ("ruff check", "ruff format --check", "mypy", "pytest", "not infra", "gitleaks"):
        assert needle in steps, needle
    assert {"checks", "compose-validate"} <= set(wf["jobs"])
    assert wf["concurrency"]["cancel-in-progress"] is True
    assert all("timeout-minutes" in j for j in wf["jobs"].values())


def test_infra_workflow_has_services_compose_and_timeouts() -> None:
    wf = yaml.safe_load(Path(".github/workflows/infra.yml").read_text(encoding="utf-8"))
    assert {"services", "compose"} <= set(wf["jobs"])
    svc = wf["jobs"]["services"]
    assert {"postgres", "redis"} <= set(svc["services"])
    assert all("health-cmd" in s["options"] for s in svc["services"].values())
    assert svc["timeout-minutes"] <= 30 and wf["jobs"]["compose"]["timeout-minutes"] <= 30
    assert wf["concurrency"]["cancel-in-progress"] is True


def test_minio_is_built_from_the_release_binary_with_a_curl_healthcheck() -> None:
    svc = _load()["services"]["minio"]
    assert svc["build"]["dockerfile"] == "minio.Dockerfile"
    assert svc["healthcheck"]["test"][:2] == ["CMD", "curl"]
    assert "curl" in Path("deploy/compose/minio.Dockerfile").read_text()
