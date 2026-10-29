"""Record the planner cassette used by the offline replay test (live calls; a handful of requests).

Usage: python scripts/record_cassette.py   (needs GROQ_API_KEY / GEMINI_API_KEY via env or .env)
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
from tests.unit.synthetic_run import run_synthetic_llm_run  # noqa: E402

CASSETTE = Path("tests/cassettes/synthetic_planner.jsonl")

if __name__ == "__main__":
    from harness.gateway.live import build_live_gateway

    gw = build_live_gateway(CASSETTE)
    res, planner = run_synthetic_llm_run(Path(tempfile.mkdtemp()), gw)
    print(res["status"], planner.decisions, gw.stats)
