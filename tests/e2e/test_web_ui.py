"""E2E tests for React web UI (PRD S9.5).

These tests require:
1. Node.js and npm (to run Playwright)
2. Playwright browsers installed (npx playwright install chromium)
3. API server running at http://localhost:8000

Tests run via subprocess calling: cd apps/web && npx playwright test
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def has_node() -> bool:
    """Check if Node.js is available."""
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True, timeout=5)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def has_playwright() -> bool:
    """Check if Playwright is installed in apps/web."""
    web_dir = Path(__file__).parents[2] / "apps" / "web"
    return (web_dir / "node_modules" / "@playwright" / "test").exists()


def api_is_running() -> bool:
    """Check if API server is accessible."""
    import socket

    try:
        with socket.create_connection(("localhost", 8000), timeout=2):
            return True
    except (TimeoutError, OSError):
        return False


@pytest.mark.skipif(not has_node(), reason="Node.js not available")
@pytest.mark.skipif(
    not has_playwright(), reason="Playwright not installed (run: cd apps/web && npm install)"
)
@pytest.mark.skipif(not api_is_running(), reason="API server not running at localhost:8000")
def test_web_ui_e2e() -> None:
    """Run Playwright e2e tests for the React run viewer.

    PRD S9.5: e2e tests verify the UI works end-to-end.
    """
    web_dir = Path(__file__).parents[2] / "apps" / "web"

    # Set environment variables for tests
    env = os.environ.copy()
    # Admin credentials if available
    if "ADMIN_USER" in env and "ADMIN_PASSWORD" in env:
        pass  # Already set

    # Run Playwright tests
    result = subprocess.run(
        ["npx", "playwright", "test"],
        cwd=web_dir,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )

    # Print output for debugging
    if result.stdout:
        print("\n=== Playwright stdout ===")
        print(result.stdout)
    if result.stderr:
        print("\n=== Playwright stderr ===")
        print(result.stderr)

    # Check result
    assert result.returncode == 0, f"Playwright tests failed with exit code {result.returncode}"


@pytest.mark.skipif(not has_node(), reason="Node.js not available")
def test_playwright_config_exists() -> None:
    """Verify Playwright config exists."""
    web_dir = Path(__file__).parents[2] / "apps" / "web"
    config = web_dir / "playwright.config.js"
    assert config.exists(), "playwright.config.js not found"


@pytest.mark.skipif(not has_node(), reason="Node.js not available")
def test_e2e_tests_exist() -> None:
    """Verify e2e test files exist."""
    web_dir = Path(__file__).parents[2] / "apps" / "web"
    e2e_dir = web_dir / "e2e"
    assert e2e_dir.exists(), "e2e directory not found"

    test_files = list(e2e_dir.glob("*.spec.js"))
    assert len(test_files) > 0, "No .spec.js files found in e2e directory"
