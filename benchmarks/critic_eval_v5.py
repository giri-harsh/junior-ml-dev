"""LLM critic v2 vs the rule-based reviewer on the v5 runs (both arms). <= 30 requests, cached.

For every finished v5 run the critic gets a symbolic summary (no data, no rule verdict) and we
compare its verdict with the stored rule-based verdict. Usage: python -m benchmarks.critic_eval
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from benchmarks.results_writer import Conditions, write_result
from benchmarks.tasks.registry import load_registry_v5
from harness.agent.critic import LLMCriticV2, load_family_gaps, run_summary_v2
from harness.agent.store import RunStore
from harness.gateway.live import build_live_gateway
from leakage.evaluate import wilson

MAX_REQUESTS = 30
ARMS = {"scripted": "s", "llm": "l"}


def main() -> int:
    gw = build_live_gateway(Path("tests/cassettes/critic_v5.jsonl"))
    gw.max_requests = MAX_REQUESTS  # enforced per attempt, repairs and retries included
    critic = LLMCriticV2(gw)
    gaps = load_family_gaps()
    rows: list[dict[str, Any]] = []
    for arm, letter in ARMS.items():
        store = RunStore(Path(f"data/agent_bench_v5_{arm}") / "runs.db")
        for spec in load_registry_v5():
            rid = f"bench-v5{letter}-{spec.name}"[:64].replace(".", "_")
            cps = store.checkpoints(rid)
            if not cps:
                continue
            state = cps[-1][1]
            review = state.get("review") or {}
            rule = review.get("verdict")
            used = gw.stats["calls"] - gw.stats["cache_hits"] - gw.stats["fixture_hits"]
            if used >= MAX_REQUESTS:
                break
            v = critic.review_v2(
                run_summary_v2(store.config(rid), state, review.get("checks") or {}, gaps)
            )
            rows.append({"arm": arm, "task": spec.name, "rule": rule,
                         "critic": v.verdict if v else None,
                         "concerns": (v.concerns if v else [])[:3]})  # fmt: skip
    valid = [r for r in rows if r["critic"] and r["rule"]]
    agree = sum(r["critic"] == r["rule"] for r in valid)
    cm: dict[str, int] = {}
    for r in valid:
        key = f"rule={r['rule']}|critic={r['critic']}"
        cm[key] = cm.get(key, 0) + 1
    res = {
        "n_runs": len(rows), "n_valid": len(valid), "agree": agree,
        "agreement_rate": agree / len(valid) if valid else None,
        "agreement_wilson95": wilson(agree, len(valid)), "confusion": cm,
        "requests": gw.stats["calls"] - gw.stats["cache_hits"] - gw.stats["fixture_hits"],
        "rows": rows,
    }  # fmt: skip
    notes = (
        "REAL LLM critic (advisory) vs rule-based reviewer on v5 runs; "
        "critic v2 sees the rule check values but not the verdict"
    )
    write_result("critic_v5", res, Conditions(llm="real", sandbox="none", n=len(rows), notes=notes))
    print({k: res[k] for k in ("n_valid", "agree", "agreement_rate", "confusion", "requests")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
