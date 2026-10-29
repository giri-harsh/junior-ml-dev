"""LLM critic vs the rule-based reviewer on the v4 runs (both arms). <= 30 requests, cached.

For every finished v4 run the critic gets a symbolic summary (no data, no rule verdict) and we
compare its verdict with the stored rule-based verdict. Usage: python -m benchmarks.critic_eval
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from benchmarks.results_writer import Conditions, write_result
from benchmarks.tasks.registry import load_registry_v4
from harness.agent.critic import LLMCritic, run_summary
from harness.agent.store import RunStore
from harness.gateway.live import build_live_gateway
from leakage.evaluate import wilson

MAX_REQUESTS = 30
ARMS = {"scripted": "s", "llm": "l"}


def main() -> int:
    gw = build_live_gateway(Path("tests/cassettes/critic_v4.jsonl"))
    gw.max_requests = MAX_REQUESTS  # enforced per attempt, repairs and retries included
    critic = LLMCritic(gw)
    rows: list[dict[str, Any]] = []
    for arm, letter in ARMS.items():
        store = RunStore(Path(f"data/agent_bench_v4_{arm}") / "runs.db")
        for spec in load_registry_v4():
            rid = f"bench-v4{letter}-{spec.name}"[:64].replace(".", "_")
            cps = store.checkpoints(rid)
            if not cps:
                continue
            state = cps[-1][1]
            rule = (state.get("review") or {}).get("verdict")
            used = gw.stats["calls"] - gw.stats["cache_hits"] - gw.stats["fixture_hits"]
            if used >= MAX_REQUESTS:
                break
            v = critic.review(run_summary(store.config(rid), state))
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
        "REAL LLM critic (advisory) vs rule-based reviewer on v4 runs; "
        "the critic never sees the rule verdict"
    )
    write_result("critic_v4", res, Conditions(llm="real", sandbox="none", n=len(rows), notes=notes))
    print({k: res[k] for k in ("n_valid", "agree", "agreement_rate", "confusion", "requests")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
