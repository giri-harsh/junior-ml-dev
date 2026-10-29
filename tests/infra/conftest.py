"""Infra tests need real services. Each test skips (never fails) when its service is unreachable."""

from __future__ import annotations

import os
import shutil
import socket
from urllib.parse import urlparse

import pytest

PG_URL = os.environ.get("INFRA_PG_URL", "postgresql+psycopg://jmd:jmd@localhost:5432/jmd")
REDIS_URL = os.environ.get("INFRA_REDIS_URL", "redis://localhost:6379/0")
MINIO = os.environ.get("INFRA_MINIO_ENDPOINT", "localhost:9000")


REQUIRE = os.environ.get("INFRA_REQUIRE") == "1"  # CI: a missing service is a failure


def unavailable(msg: str) -> None:
    if REQUIRE:
        pytest.fail(msg)
    pytest.skip(msg)


def reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _hp(url: str, default: int) -> tuple[str, int]:
    u = urlparse(url)
    return u.hostname or "localhost", u.port or default


@pytest.fixture
def pg_url() -> str:
    if not reachable(*_hp(PG_URL, 5432)):
        unavailable("postgres not reachable")
    return PG_URL


@pytest.fixture
def redis_url() -> str:
    if not reachable(*_hp(REDIS_URL, 6379)):
        unavailable("redis not reachable")
    return REDIS_URL


@pytest.fixture
def minio_endpoint() -> str:
    host, _, port = MINIO.partition(":")
    if not reachable(host, int(port or 9000)):
        unavailable("minio not reachable")
    return MINIO


@pytest.fixture
def docker_bin() -> str:
    exe = shutil.which("docker")
    if exe is None:
        unavailable("docker not installed")
    import subprocess

    if subprocess.run([exe, "info"], capture_output=True).returncode != 0:
        unavailable("docker daemon not running")
    return exe
