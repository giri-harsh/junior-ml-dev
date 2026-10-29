"""Cross-platform task runner (Makefile targets delegate here; works without `make`)."""

from __future__ import annotations

import shutil
import subprocess
import sys

COMPOSE = ["docker", "compose", "-f", "deploy/compose/docker-compose.yml"]


def run(*cmd: str) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd)


def lint() -> int:
    return (
        run("uv", "run", "ruff", "check", ".")
        or run("uv", "run", "ruff", "format", "--check", ".")
        or run("uv", "run", "mypy")
    )


def test() -> int:
    return run("uv", "run", "pytest", "-m", "not integration")


def test_integration() -> int:
    return run("uv", "run", "pytest", "-m", "integration")


def secrets() -> int:
    if shutil.which("gitleaks"):
        return run("gitleaks", "detect", "--config", ".gitleaks.toml", "--no-banner")
    return run(sys.executable, "scripts/secret_scan.py")


def up(profile: str = "micro") -> int:
    return run(*COMPOSE, "--profile", profile, "up", "-d", "--wait")


def down() -> int:
    return run(*COMPOSE, "--profile", "micro", "--profile", "full", "down")


def test_infra() -> int:
    return run("uv", "run", "pytest", "-m", "infra")


def hooks() -> int:
    return run("git", "config", "core.hooksPath", ".githooks")


def gate() -> int:
    """The merge gate: ruff check, ruff format --check, mypy, unit tests."""
    return (
        run("uv", "run", "ruff", "check", ".")
        or run("uv", "run", "ruff", "format", "--check", ".")
        or run("uv", "run", "mypy")
        or run("uv", "run", "pytest", "-q", "-m", "not infra and not llm and not compose")
    )


def docs() -> int:
    """Regenerate every generated doc: results, metrics, MCP tool docs, ADR index, changelog."""
    return (
        run("uv", "run", "python", "scripts/render_results.py")
        or run("uv", "run", "python", "scripts/render_metrics.py")
        or run("uv", "run", "python", "scripts/gen_mcp_docs.py")
        or run("uv", "run", "python", "scripts/gen_adr_index.py")
        or run("uv", "run", "python", "scripts/gen_changelog.py")
    )


def demo(*args: str) -> int:
    """One-command offline demo (add --deploy for the approval-gated deploy)."""
    return run("uv", "run", "python", "scripts/demo.py", *args)


def audit() -> int:
    """Dependency and code security scans (what the CI security job runs)."""
    return run("uv", "run", "--with", "pip-audit", "pip-audit", "--skip-editable") or run(
        "uv", "run", "--with", "bandit", "bandit", "-r", "apps", "harness", "mcp_servers",
        "leakage", "datastory", "trajectory", "benchmarks", "scripts", "-ll", "-q",
    )  # fmt: skip


def coverage() -> int:
    return run("uv", "run", "pytest", "-q", "-m", "not infra and not llm and not compose", "--cov")


def changelog() -> int:
    return run("uv", "run", "python", "scripts/gen_changelog.py")


COMMANDS = {
    "gate": gate,
    "docs": docs,
    "demo": demo,
    "audit": audit,
    "coverage": coverage,
    "changelog": changelog,
    "lint": lint,
    "test": test,
    "test-integration": test_integration,
    "test-infra": test_infra,
    "secrets": secrets,
    "up": up,
    "down": down,
    "hooks": hooks,
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in COMMANDS:
        print(f"usage: tasks.py {{{'|'.join(COMMANDS)}}}", file=sys.stderr)
        return 2
    return COMMANDS[argv[0]](*argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
