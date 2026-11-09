"""Live E2B suite. Every test is skipped (never failed) without E2B_API_KEY or the `e2b` SDK, and
each sandbox creation is reserved from the shared budget ledger (kind `e2b`, run cap 60); a denied
reservation also skips. Run: see docs/ws/A.md."""

from __future__ import annotations

import importlib.util
import os

import pytest

from harness.sandbox.e2b_live import BudgetDenied, BudgetedE2B


def pytest_configure(config: pytest.Config) -> None:
    # also declared in pyproject.toml once the cross-path change lands; idempotent either way
    config.addinivalue_line("markers", "e2b: live E2B sandbox calls; skipped without E2B_API_KEY")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    reason = ""
    if not os.environ.get("E2B_API_KEY"):
        reason = "E2B_API_KEY not set"
    elif importlib.util.find_spec("e2b") is None:
        reason = "e2b SDK not installed"
    for item in items:
        if "tests/e2b/" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.e2b)
            if reason:
                item.add_marker(pytest.mark.skip(reason=reason))


class _SkipOnDeny(BudgetedE2B):
    def run_python(self, code, timeout_s, files):  # type: ignore[no-untyped-def]
        try:
            return super().run_python(code, timeout_s, files)
        except BudgetDenied as e:
            pytest.skip(str(e))


@pytest.fixture
def sandbox() -> BudgetedE2B:
    return _SkipOnDeny(template=os.environ.get("JMD_E2B_TEMPLATE") or None)


@pytest.fixture
def parquet_sandbox() -> BudgetedE2B:
    """A template with pandas AND pyarrow (internet is off, so nothing can be pip-installed)."""
    return _SkipOnDeny(template=os.environ.get("JMD_E2B_PARQUET_TEMPLATE") or None)
