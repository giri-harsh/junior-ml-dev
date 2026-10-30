"""Fresh planted critic evaluation (run 7): critic v3 on `benchmarks/critic_set_v6.json`.

The set (38 symbolic run summaries, 15 with a planted issue) and its sha256 were committed before
any critic call. Reports recall on planted issues and the false-alarm rate on clean runs with
Wilson CIs, per-type recall, and how often the schema forced a concurrence (defaulted_to_rules).
Runs ONCE (refuses if the result exists). <= 40 requests in total, cached. `--complete` re-runs
the SAME prompt only to fill items that got no output because a provider failed (the cassette
replays everything that already succeeded); its cap is 40 minus what the first pass spent.

    uv run python -m benchmarks.critic_eval_v6
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

from benchmarks.results_writer import RESULTS_DIR, Conditions, write_result
from harness.agent.critic import LLMCriticV3
from harness.gateway.live import build_live_gateway
from leakage.evaluate import wilson

SET = Path("benchmarks/critic_set_v6.json")
MAX_REQUESTS = 40


def load_set(path: Path = SET) -> list[dict[str, Any]]:
    import json

    body = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    want = path.with_suffix(".sha256").read_text(encoding="utf-8").strip()
    if hashlib.sha256(body.encode("utf-8")).hexdigest() != want:
        raise SystemExit("critic set does not match its committed sha256")
    items: list[dict[str, Any]] = json.loads(body)["items"]
    return items


def score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    planted = [r for r in rows if r["planted"] and r["critic"]]
    clean = [r for r in rows if not r["planted"] and r["critic"]]
    hit = sum(r["critic"] == "REQUEST_CHANGES" for r in planted)
    fa = sum(r["critic"] == "REQUEST_CHANGES" for r in clean)
    by_type: dict[str, list[int]] = {}
    for r in planted:
        k = by_type.setdefault(r["planted"], [0, 0])
        k[0] += r["critic"] == "REQUEST_CHANGES"
        k[1] += 1
    return {
        "planted_n": len(planted), "recall": hit, "recall_wilson95": wilson(hit, len(planted)),
        "clean_n": len(clean), "false_alarms": fa, "false_alarm_wilson95": wilson(fa, len(clean)),
        "recall_by_type": {k: f"{a}/{b}" for k, (a, b) in sorted(by_type.items())},
        "no_output": sum(1 for r in rows if r["critic"] is None),
    }  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    import json
    import time

    complete = "--complete" in (sys.argv[1:] if argv is None else argv)
    prior = RESULTS_DIR / "critic_v6.json"
    spent = 0
    if prior.exists():
        first = json.loads(prior.read_text(encoding="utf-8"))["results"]
        if not complete or not first["no_output"]:
            raise SystemExit("critic_v6.json exists: the fresh set is evaluated once")
        gs = first["gateway_stats"]
        spent = gs["calls"] - gs["cache_hits"] - gs["fixture_hits"]
    items = load_set()
    gw = build_live_gateway(Path("tests/cassettes/critic_v6.jsonl"))
    gw.max_requests = MAX_REQUESTS - spent
    critic = LLMCriticV3(gw)
    rows: list[dict[str, Any]] = []
    for it in items:
        before = gw.stats["calls"]
        v = critic.review_v3(it["summary"])
        if gw.stats["calls"] > before:
            time.sleep(6)  # the free Gemini tier rate-limits bursts; do not burn the cap on 429s
        rows.append({
            "id": it["id"], "planted": it["planted"],
            "rule_failed": sorted(k for k, ok in it["summary"]["rule_checks"].items() if not ok),
            "critic": v.verdict if v else None,
            "defaulted_to_rules": v.defaulted_to_rules if v else [],
            "dissent": [d.check for d in v.dissent] if v else [],
            "concerns": [f"{c.severity}: {c.text}" for c in (v.concerns if v else [])][:3],
        })  # fmt: skip
    res = {
        **score(rows),
        "set_sha256": SET.with_suffix(".sha256").read_text(encoding="utf-8").strip(),
        "forced_concurrence": sum(bool(r["defaulted_to_rules"]) for r in rows),
        "gateway_stats": gw.stats,
        "error_statuses": gw.error_statuses,
        "rows": rows,
    }
    notes = "FRESH planted set, critic v3 (schema-enforced answers to failed rule checks), real LLM"
    write_result("critic_v6", res, Conditions(llm="real", sandbox="none", n=len(rows), notes=notes))
    print({k: res[k] for k in res if k not in {"rows", "gateway_stats"}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
