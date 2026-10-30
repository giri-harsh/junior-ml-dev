"""Fresh planted critic evaluation v2 (run 9): critic v3 on `benchmarks/critic_v2/set_v2.json`.

The set (53 symbolic run summaries, 23 with a planted issue; see docs/ws/D.md) and its sha256 are
committed before any critic call. Reports recall on planted issues and the false-alarm rate on
clean runs with Wilson CIs, per-type recall, error statuses and requests used, plus a comparison
field against run 7 (a DIFFERENT set, so the two are not paired).

Runs ONCE: refuses if the result file exists. `--complete` re-runs the SAME prompt only to fill
items that got no output because a provider failed (the cassette replays everything that
succeeded); its cap is MAX_REQUESTS minus what the first pass spent. `--check` verifies the hash
and prints the plan without any LLM call.

Budget: reserves the request cap on the shared ledger (`scripts/budget.py`) before the run and
commits the actual usage afterwards. The gateway chain is groq then gemini (as in run 7), so both
kinds are reserved and committed from the usage-ledger difference.

    python -m benchmarks.critic_v2.eval
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from benchmarks.results_writer import RESULTS_DIR, Conditions, write_result
from leakage.evaluate import wilson

HERE = Path(__file__).resolve().parent
SET = HERE / "set_v2.json"
# `benchmarks/results/critic_v4.json` already holds the OLD v5-era critic run (rendered into
# docs), so the guard/result of this evaluation lives next to the set instead.
RESULT_NAME = "critic_v2_eval"
RESULT_DIR = HERE
CASSETTE = Path("tests/cassettes/critic_v2.jsonl")
MAX_REQUESTS = 60
PACE_S = 6.0
PROVIDERS = ("groq", "gemini")
RUN7_RESULT = RESULTS_DIR / "critic_v6.json"
RUN7_FALLBACK = {"recall": "10/15", "false_alarms": "1/19", "set": "benchmarks/critic_set_v6.json"}


def load_set(path: Path = SET) -> list[dict[str, Any]]:
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
    base = [r for r in planted if r["planted"] == "rule_fail_baseline_margin"]
    return {
        "planted_n": len(planted), "recall": hit, "recall_wilson95": wilson(hit, len(planted)),
        "clean_n": len(clean), "false_alarms": fa, "false_alarm_wilson95": wilson(fa, len(clean)),
        "recall_by_type": {k: f"{a}/{b}" for k, (a, b) in sorted(by_type.items())},
        # the run-7 flaw: numeric dissent accepted on baseline-margin items. Here every such item
        # has cv <= linear, so ANY dissent on them is wrong; counted separately.
        "baseline_margin_dissent": sum(bool(r["dissent"]) for r in base),
        "no_output": sum(1 for r in rows if r["critic"] is None),
    }  # fmt: skip


def vs_run7(res: dict[str, Any]) -> dict[str, Any]:
    prior: dict[str, Any] = dict(RUN7_FALLBACK)
    if RUN7_RESULT.exists():
        r = json.loads(RUN7_RESULT.read_text(encoding="utf-8"))["results"]
        prior = {
            "set": "benchmarks/critic_set_v6.json",
            "recall": f"{r['recall']}/{r['planted_n']}",
            "recall_wilson95": r["recall_wilson95"],
            "false_alarms": f"{r['false_alarms']}/{r['clean_n']}",
            "false_alarm_wilson95": r["false_alarm_wilson95"],
        }
    return {
        "run7": prior,
        "run9": {
            "set": "benchmarks/critic_v2/set_v2.json",
            "recall": f"{res['recall']}/{res['planted_n']}",
            "false_alarms": f"{res['false_alarms']}/{res['clean_n']}",
        },
        "note": "DIFFERENT set, not paired: run 7's baseline-margin items were defensible "
                "numerically (set-design flaw); run 9's are not, so recall is not comparable "
                "item for item and differences are not attributable to the critic alone.",
    }  # fmt: skip


def run_items(
    items: list[dict[str, Any]],
    review: Callable[[dict[str, Any]], Any],
    calls: Callable[[], int],
    pace_s: float = PACE_S,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """One review per item; pause after every UNCACHED request (free-tier burst limits)."""
    rows: list[dict[str, Any]] = []
    for it in items:
        before = calls()
        v = review(it["summary"])
        if calls() > before:
            sleep(pace_s)  # the free Gemini tier rate-limits bursts; do not burn the cap on 429s
        rows.append({
            "id": it["id"], "planted": it["planted"],
            "rule_failed": sorted(k for k, ok in it["summary"]["rule_checks"].items() if not ok),
            "critic": v.verdict if v else None,
            "defaulted_to_rules": v.defaulted_to_rules if v else [],
            "dissent": [d.check for d in v.dissent] if v else [],
            "concerns": [f"{c.severity}: {c.text}" for c in (v.concerns if v else [])][:3],
        })  # fmt: skip
    return rows


# --- shared budget ledger (scripts/budget.py) ---------------------------------------------------
def _budget(*args: str) -> subprocess.CompletedProcess[str]:
    root = HERE.parents[1]
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "budget.py"), *args],
        capture_output=True, text=True, check=False, cwd=root,
    )  # fmt: skip


def reserve(n: int, kinds: tuple[str, ...] = PROVIDERS) -> None:
    """Reserve `n` requests per provider kind; a denial rolls back and aborts the run."""
    done: list[str] = []
    for k in kinds:
        if _budget("reserve", k, str(n)).returncode != 0:
            for d in done:
                _budget("commit", d, "0", str(n))  # release what was reserved
            raise SystemExit(f"budget denied: {k} {n}; nothing was called")
        done.append(k)


def commit(n: int, used: dict[str, int]) -> None:
    for k, u in used.items():
        _budget("commit", k, str(u), str(n))


def build_gateway() -> Any:
    from harness.gateway.live import build_live_gateway

    return build_live_gateway(CASSETTE)


def make_critic(gw: Any) -> Any:
    from harness.agent.critic import LLMCriticV3

    return LLMCriticV3(gw)


def _usage() -> dict[str, int]:
    """Requests recorded today per provider in the gateway's own usage ledger."""
    from harness.gateway.limits import UsageLedger
    from harness.gateway.live import USAGE_PATH

    ledger = UsageLedger(USAGE_PATH)
    return {k: ledger.used(k) for k in PROVIDERS}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    complete, check = "--complete" in args, "--check" in args
    items = load_set()
    if check:
        n_pl = sum(bool(i["planted"]) for i in items)
        print({"items": len(items), "planted": n_pl, "clean": len(items) - n_pl, "hash": "ok"})
        return 0

    prior = RESULT_DIR / f"{RESULT_NAME}.json"
    spent = 0
    if prior.exists():
        first = json.loads(prior.read_text(encoding="utf-8"))["results"]
        if not complete or not first["no_output"]:
            raise SystemExit(f"{prior.name} exists: the fresh set is evaluated once")
        # cumulative uncached requests over all passes so far (cache/fixture hits never count)
        spent = int(first["requests_used"])
    cap = MAX_REQUESTS - spent
    if cap <= 0:
        raise SystemExit("request cap spent")

    reserve(cap)
    gw: Any = None
    rows: list[dict[str, Any]] = []
    before: dict[str, int] = {}
    try:  # the reservation is ALWAYS settled, also when building the gateway fails
        before = _usage()
        gw = build_gateway()
        gw.max_requests = cap
        rows = run_items(items, make_critic(gw).review_v3, lambda: gw.stats["calls"])
    finally:
        commit(cap, {k: v - before.get(k, v) for k, v in _usage().items()})
    this_pass = int(gw.stats["calls"])  # `calls` already excludes cache and fixture hits
    res = {
        **score(rows),
        "set_sha256": SET.with_suffix(".sha256").read_text(encoding="utf-8").strip(),
        "forced_concurrence": sum(bool(r["defaulted_to_rules"]) for r in rows),
        "requests_used": spent + this_pass,  # cumulative over passes; never above MAX_REQUESTS
        "requests_first_pass": spent if spent else this_pass,
        "requests_this_pass": this_pass,
        "max_requests": MAX_REQUESTS,
        "gateway_stats": gw.stats,
        "error_statuses": gw.error_statuses,
        "rows": rows,
    }
    res["vs_run7"] = vs_run7(res)
    notes = "FRESH planted set v2 (unambiguous rule failures), critic v3, real LLM"
    write_result(
        RESULT_NAME,
        res,
        Conditions(llm="real", sandbox="none", n=len(rows), notes=notes),
        out_dir=RESULT_DIR,
    )
    print({k: res[k] for k in res if k not in {"rows", "gateway_stats"}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
