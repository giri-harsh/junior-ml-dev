"""Offline replay of a recorded real-LLM planner session (no network, no keys)."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.gateway.gateway import Fixtures, Gateway
from tests.unit.synthetic_run import run_synthetic_llm_run

CASSETTE = Path("tests/cassettes/synthetic_planner.jsonl")


@pytest.mark.skipif(not CASSETTE.exists(), reason="cassette not recorded yet")
def test_recorded_session_replays_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("GROQ_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    gw = Gateway(providers=[], mode="replay", fixtures=Fixtures(CASSETTE))
    res, planner = run_synthetic_llm_run(tmp_path, gw)
    assert res["status"] in {"done", "budget_exhausted"} and res["planner"] == "llm"
    assert gw.stats["fixture_hits"] >= 1  # at least one recorded answer was actually used
    assert res["llm_mode"] == "real" and gw.stats["structured_failed"] == 0


def test_empty_gateway_degrades_to_the_scripted_plan(tmp_path: Path) -> None:
    gw = Gateway(providers=[], mode="live")  # no providers at all: every call fails
    res, planner = run_synthetic_llm_run(tmp_path, gw)
    assert res["status"] == "done" and planner.fallbacks >= 1 and res["tokens"] == 0
