"""Live cloud calls. Marked `llm`; skipped without keys; counts against the daily caps."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.gateway.envload import load_llm_keys
from harness.gateway.live import build_live_gateway
from tests.unit.synthetic_run import run_synthetic_llm_run

pytestmark = pytest.mark.llm


def test_live_planner_completes_a_run(tmp_path: Path) -> None:
    if not load_llm_keys():
        pytest.skip("no GROQ_API_KEY / GEMINI_API_KEY")
    gw = build_live_gateway(Path("tests/cassettes/synthetic_planner.jsonl"))  # cache first
    res, planner = run_synthetic_llm_run(tmp_path, gw)
    assert res["status"] in {"done", "budget_exhausted"}
    assert gw.stats["structured_failed"] == 0 or planner.fallbacks >= 1
