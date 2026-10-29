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


COMMANDS = {
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
