"""Critic calibration on DEV runs only (no v4/v5 data). <= 40 real-LLM requests (20 per version).

Cases = the 5 dev runs of the last S22 dev session (all rule-APPROVE) plus controlled mutations of
those states that make the deterministic reviewer fail (leakage unchecked, unresolved leakage,
overfit gap, no lift over the dummy) or merely look worse without failing a rule (budget used,
failed step). Rule verdicts come from the real `review()` on the mutated state.

Reports, for critic v1 (run 5) and v2 (family-aware, severity-tagged): agreement with the rules and
the catch rate on rule-flagged cases. Also writes harness/agent/family_gaps.json from the 5 base
runs. Usage: python -m benchmarks.critic_calibration
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

from benchmarks.results_writer import Conditions, write_result
from harness.agent.critic import (
    GAPS_PATH,
    LLMCritic,
    LLMCriticV2,
    gap_ratio,
    run_summary,
    run_summary_v2,
)
from harness.agent.store import RunStore
from harness.agent.tools import ToolCtx, review
from harness.gateway.limits import UsageLedger
from harness.gateway.live import USAGE_PATH, build_live_gateway
from leakage.evaluate import wilson

HIGHER_TASKS = ("wdbc", "kc1", "sk_wine")
PER_VERSION_CAP = 20


def base_states() -> dict[str, tuple[Any, dict[str, Any]]]:
    store = RunStore("data/agent_dev/runs.db")
    out = {}
    for r in store.list_runs():
        name = r["run_id"].split("-cv-")[-1]
        out[name] = (store.config(r["run_id"]), store.checkpoints(r["run_id"])[-1][1])
    return out


def family_gaps(bases: dict[str, tuple[Any, dict[str, Any]]]) -> dict[str, Any]:
    vals: dict[str, list[float]] = {}
    for _, st in bases.values():
        dummy = next(m["val_score"] for m in st["models"].values() if m["family"] == "dummy")
        for m in st["models"].values():
            if m["family"] != "dummy" and m.get("scored", True):
                vals.setdefault(m["family"], []).append(
                    gap_ratio(m["train_score"], m["val_score"], dummy)
                )
    return {
        f: {"n": len(v), "range": [round(min(v), 3), round(max(v), 3)],
            "source": "dev runs (5 real_dev tasks), S22 llm2-cv session"}
        for f, v in vals.items()
    }  # fmt: skip


def mutations() -> list[tuple[str, tuple[str, ...], Any]]:
    def leak_unchecked(st: dict[str, Any]) -> None:
        st["failures"]["detect_leakage"] = "GuardError: time budget exceeded"

    def unresolved(st: dict[str, Any]) -> None:
        st["findings"].append({"type": "group_leakage", "severity": "medium", "columns": ["c1"],
                               "evidence": {}, "confidence": 0.8})  # fmt: skip
        st["unresolved"] = ["group_leakage:c1"]

    def overfit(st: dict[str, Any]) -> None:
        for m in st["models"].values():
            if m["family"] != "dummy":
                m["train_score"] = m["val_score"] + 0.25

    def no_lift(st: dict[str, Any]) -> None:
        dummy = next(m["val_score"] for m in st["models"].values() if m["family"] == "dummy")
        for m in st["models"].values():
            if m["family"] != "dummy":
                m["val_score"] = dummy + 0.0001
                m["train_score"] = dummy + 0.0001

    def budget(st: dict[str, Any]) -> None:
        st["budget_exhausted"] = {"steps": 5, "wall_s": 1.0, "tokens": 0}

    def failed_step(st: dict[str, Any]) -> None:
        st["failures"]["train_model:rf"] = "ExperimentError: example failure"

    return [
        ("leakage_unchecked", HIGHER_TASKS, leak_unchecked),
        ("unresolved_leakage", HIGHER_TASKS, unresolved),
        ("overfit_gap", HIGHER_TASKS, overfit),
        ("no_lift", HIGHER_TASKS[:2], no_lift),
        ("budget_used", ("kin8nm", "sk_wine"), budget),
        ("failed_step", ("wdbc", "sk_diabetes_reg"), failed_step),
    ]


def build_cases(bases: dict[str, tuple[Any, dict[str, Any]]]) -> list[dict[str, Any]]:
    cases = []
    for name, (cfg, st) in bases.items():
        cases.append({"id": f"{name}|base", "cfg": cfg, "state": st})
    for label, tasks, fn in mutations():
        for name in tasks:
            cfg, st = bases[name]
            st2 = copy.deepcopy(st)
            fn(st2)
            cases.append({"id": f"{name}|{label}", "cfg": cfg, "state": st2})
    for c in cases:
        c["rule"] = review(ToolCtx(c["cfg"], c["state"]), {})
    return cases


def score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [r for r in rows if r["critic"]]
    agree = sum(r["critic"] == r["rule"] for r in valid)
    flagged = [r for r in valid if r["rule"] == "REQUEST_CHANGES"]
    ok = [r for r in valid if r["rule"] == "APPROVE"]
    return {
        "n": len(rows), "n_valid": len(valid), "agree": agree,
        "agreement": agree / len(valid) if valid else None,
        "agreement_wilson95": wilson(agree, len(valid)),
        "rule_flagged": len(flagged),
        "caught": sum(r["critic"] == "REQUEST_CHANGES" for r in flagged),
        "rule_approved": len(ok),
        "overflagged": sum(r["critic"] == "REQUEST_CHANGES" for r in ok),
    }  # fmt: skip


def main() -> int:
    bases = base_states()
    gaps = family_gaps(bases)
    GAPS_PATH.write_text(json.dumps(gaps, indent=1, sort_keys=True), encoding="utf-8")
    cases = build_cases(bases)[:PER_VERSION_CAP]
    out: dict[str, Any] = {"family_gaps": gaps, "n_cases": len(cases)}
    for version in ("v1", "v2"):
        gw = build_live_gateway(Path(f"tests/cassettes/critic_cal_{version}.jsonl"))
        gw.max_requests = PER_VERSION_CAP
        before = UsageLedger(USAGE_PATH).used("gemini") + UsageLedger(USAGE_PATH).used("groq")
        rows = []
        for c in cases:
            rule = c["rule"]["verdict"]
            if version == "v1":
                v = LLMCritic(gw).review(run_summary(c["cfg"], c["state"]))
                verdict = v.verdict if v else None
                concerns = (v.concerns if v else [])[:3]
            else:
                summ = run_summary_v2(c["cfg"], c["state"], c["rule"]["checks"], gaps)
                v2 = LLMCriticV2(gw).review_v2(summ)
                verdict = v2.verdict if v2 else None
                concerns = [f"{x.severity}: {x.text}" for x in (v2.concerns if v2 else [])][:3]
            rows.append({"case": c["id"], "rule": rule, "critic": verdict, "concerns": concerns})
        out[version] = {
            **score(rows), "rows": rows,
            "requests": UsageLedger(USAGE_PATH).used("gemini")
            + UsageLedger(USAGE_PATH).used("groq")
            - before,
        }  # fmt: skip
        print(
            version,
            {
                k: out[version][k]
                for k in (
                    "n_valid",
                    "agree",
                    "agreement",
                    "caught",
                    "rule_flagged",
                    "overflagged",
                    "rule_approved",
                    "requests",
                )
            },
            flush=True,
        )
    notes = "DEV-only critic calibration; real LLM; mutated dev states; critic v2 sees rule results"
    write_result(
        "critic_calibration", out, Conditions(llm="real", sandbox="none", n=len(cases), notes=notes)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
