"""Agent benchmark on the 10 registry tasks: scored through the scorer service, eval-once.

Protocol (ADR-016): the agent freezes (hash over planner config, budgets, code policy, agent and
experiments code, leakage thresholds); the hash is claimed in the eval ledger BEFORE any task runs;
a hash is evaluated once. A crash mid-run resumes only the unfinished tasks from the partial file
and is logged in the ledger; finished tasks are never rerun. The working tree must be clean and
HEAD must carry the `agent-frozen` tag.

THE PLANNER IS SCRIPTED (no LLM). Results are labelled as such everywhere.

Usage: python -m benchmarks.agent_benchmark --final [--resume]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from benchmarks.metrics import bootstrap_ci, normalized_score, paired_bootstrap_ci, passes
from benchmarks.results_writer import RESULTS_DIR, Conditions, write_result
from benchmarks.tasks.registry import TaskSpec, load_registry, load_registry_v3, load_registry_v4
from leakage import ledger
from leakage.evaluate import wilson

FREEZE_FILES = [
    "harness/agent/models.py", "harness/agent/planners.py", "harness/agent/runner.py",
    "harness/agent/tools.py", "harness/agent/deploy_tools.py", "harness/agent/report.py",
    "harness/policies/code_policy.py", "mcp_servers/experiments/service.py",
    "mcp_servers/data_tools/service.py", "leakage/thresholds.frozen.sha256",
    "leakage/detectors.py", "datastory/roles.py",
    "harness/gateway/gateway.py", "harness/gateway/limits.py", "harness/gateway/live.py",
    "harness/gateway/providers.py", "harness/gateway/models.py", "harness/policies/untrusted.py",
    "benchmarks/tasks/registry_v3.yaml", "benchmarks/tasks/registry_v4.yaml",
]  # fmt: skip
RESULT_NAME = "agent_v1"
FLAML_BUDGET_S = 30.0
FROZEN_TAG = "agent-frozen"


def freeze_hash(budget: dict[str, Any], planner_fp: dict[str, Any], root: Path = Path(".")) -> str:
    h = hashlib.sha256()
    h.update(json.dumps({"budget": budget, "planner": planner_fp}, sort_keys=True).encode())
    for rel in FREEZE_FILES:
        data = (root / rel).read_bytes().replace(b"\r\n", b"\n")  # line-ending independent
        h.update(rel.encode() + hashlib.sha256(data).digest())
    return h.hexdigest()


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def assert_frozen_checkout(tag: str = FROZEN_TAG) -> str:
    if _git("status", "--porcelain"):
        raise SystemExit("refusing to evaluate: working tree is not clean")
    head = _git("rev-parse", "HEAD")
    if _git("rev-parse", f"{tag}^{{commit}}") != head:
        raise SystemExit(f"refusing to evaluate: HEAD is not tagged {tag}")
    return head


def aggregate(per_task: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in per_task.values() if r["agent_normalized"] is not None]
    out: dict[str, Any] = {
        "n_tasks": len(per_task), "n_defined": len(ok),
        "excluded": sorted(k for k, r in per_task.items() if r["agent_normalized"] is None),
    }  # fmt: skip
    if ok:
        a = [r["agent_normalized"] for r in ok]
        lin = [r["linear_normalized"] for r in ok]
        out["agent_normalized_mean_ci95"] = bootstrap_ci(a, seed=0)
        out["linear_normalized_mean_ci95"] = bootstrap_ci(lin, seed=0)
        out["agent_minus_linear_paired_ci95"] = paired_bootstrap_ci(a, lin, seed=0)
        out["agent_minus_flaml_paired_ci95"] = paired_bootstrap_ci(a, [1.0] * len(a), seed=0)
    k = sum(1 for r in per_task.values() if r["passes_vs_linear"])
    out["pass_vs_linear"] = {"k": k, "n": len(per_task), "wilson95": wilson(k, len(per_task))}
    return out


def run_benchmark(
    specs: list[TaskSpec],
    run_one: Callable[[TaskSpec], dict[str, Any]],
    refs: dict[str, dict[str, Any]],
    *,
    digest: str,
    ledger_path: Path,
    out_dir: Path,
    resume: bool = False,
    meta: dict[str, Any] | None = None,
    result_name: str = RESULT_NAME,
    prior: dict[str, Any] | None = None,
    label: str = "",
    planner: str = "scripted",
    llm: str = "none",
) -> Path:
    key = f"agent:{digest}"
    partial = out_dir / f"{result_name}.partial.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    if resume and ledger.is_spent(key, ledger_path):
        ledger.mark_infra_retry(
            key, f"resume after crash at {len(_load(partial))} tasks done", ledger_path
        )
    else:
        ledger.claim(key, f"{result_name}.json", [s.name for s in specs], ledger_path)  # BEFORE run
        partial.write_text("{}", encoding="utf-8")
    done = _load(partial)
    for spec in specs:
        if spec.name in done:
            continue  # finished tasks are never rerun
        done[spec.name] = run_one(spec)
        partial.write_text(json.dumps(done, indent=1, sort_keys=True), encoding="utf-8")
    per: dict[str, dict[str, Any]] = {}
    for spec in specs:
        r = done[spec.name]
        ref = refs[spec.name]
        norm = normalized_score(r["agent"], ref["dummy"], ref["flaml"], spec.metric)
        per[spec.name] = {
            **r, "dummy": ref["dummy"], "linear": ref["linear"], "flaml": ref["flaml"],
            "agent_normalized": norm, "linear_normalized": ref["linear_normalized"],
            "passes_vs_linear": passes(r["agent"], ref["linear"], spec.metric, r.get("scale")),
        }  # fmt: skip
    who = (
        "SCRIPTED planner, no LLM (not an LLM-agent result)"
        if planner == "scripted"
        else f"LLM planner (real cloud LLM: {llm})"
    )
    notes = (
        f"{who}; scorer-service test scores; "
        f"freeze hash {digest}; agent FLAML budget {FLAML_BUDGET_S}s inside its search, baseline "
        f"FLAML 30s (baselines_v0.json); references are code-written results, not re-run here. "
        f"{label} {(meta or {}).get('extra', '')}"
    )
    agg = aggregate(per)
    if prior:  # paired difference vs an earlier evaluation, over tasks defined in both
        pairs = [
            (r["agent_normalized"], prior[k]["agent_normalized"])
            for k, r in per.items()
            if k in prior and r["agent_normalized"] is not None
            and prior[k]["agent_normalized"] is not None
        ]  # fmt: skip
        if pairs:
            a, b = zip(*pairs, strict=True)
            agg["paired_vs_prior_ci95"] = paired_bootstrap_ci(list(a), list(b), seed=0)
            agg["paired_vs_prior_n"] = len(pairs)
    path = write_result(
        result_name,
        {"per_task": per, "aggregate": agg, "freeze_hash": digest,
         "planner": planner, "llm": llm, "meta": meta or {}},
        Conditions(
            llm="real" if llm == "real" else "none", sandbox="none", n=len(per), notes=notes
        ),
        out_dir=out_dir,
    )  # fmt: skip
    ledger.mark(key, "evaluated", ledger_path)
    return path


def _load(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else {}


# --- the real thing ------------------------------------------------------------------------
def real_run_one(
    spec: TaskSpec,
    work: Path,
    version: str = "",
    planner_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    from benchmarks.baselines import DATA_ROOT, SCORER_ROOT, score_via_scorer
    from harness.agent.models import RunBudget, RunConfig, RunTask
    from harness.agent.planners import ScriptedPlanner
    from harness.agent.runner import AgentRunner
    from harness.agent.store import RunStore

    tdir = DATA_ROOT / spec.name
    feats = tdir / "test_features.parquet"
    shutil.copyfile(SCORER_ROOT / spec.name / "test_features.parquet", feats)  # features only
    cfg = RunConfig(
        run_id=f"bench-{version + '-' if version else ''}{spec.name}"[:64].replace(".", "_"),
        task=RunTask(
            name=spec.name, data_path=str(tdir / "train.parquet"), target=spec.target,
            task_type=spec.task_type, metric=spec.metric, test_features_path=str(feats),
        ),
        budget=RunBudget(flaml_budget_s=FLAML_BUDGET_S), mode="benchmark",
        planner="llm" if planner_factory else "scripted",
        llm_mode="real" if planner_factory else "none",
    )  # fmt: skip
    t0 = time.perf_counter()
    planner = planner_factory() if planner_factory else ScriptedPlanner()
    res = AgentRunner(RunStore(work / "runs.db"), planner, run_root=work / "runs").run(cfg)
    if not res.get("predictions_path"):
        raise RuntimeError(f"{spec.name}: agent produced no predictions ({res['status']})")
    preds = pd.read_csv(res["predictions_path"])
    if spec.task_type == "multiclass":
        preds["pred"] = preds["pred"].astype(str)
    score = score_via_scorer(spec, preds, run_id=f"agent-{spec.name}")
    y = pd.read_parquet(tdir / "train.parquet")[spec.target]
    scale = float(y.std()) if spec.task_type == "regression" else None
    return {
        "agent": score, "status": res["status"], "family": res["chosen_family"],
        "n_steps": res["n_steps"], "latency_s": res["latency_s"],
        "wall_s": round(time.perf_counter() - t0, 1), "tokens": res["tokens"],
        "cost_usd": res["cost_usd"], "dropped": res["dropped"], "reviewer": res["review"],
        "failures": res["failures"], "scale": scale,
        "leakage_checked": "detect_leakage" not in res["failures"],
        **(llm_stats(planner) if planner_factory else {}),
    }  # fmt: skip


def llm_stats(planner: Any) -> dict[str, Any]:
    gw = planner.gateway
    s = gw.stats
    return {
        "llm_requests": s["calls"] - s["cache_hits"] - s["fixture_hits"],
        "llm_cached": s["cache_hits"] + s["fixture_hits"],
        "llm_structured": s["structured"],
        "llm_first_try_valid": s["structured_first_try_valid"],
        "llm_repairs": s["repairs"],
        "llm_fallbacks": planner.fallbacks,
        "llm_decisions": planner.decisions,
        "llm_tokens": gw.budget.used_tokens,
        "llm_providers": sorted({getattr(p, "name", "?") for p in gw.providers}),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true", required=True)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--version", choices=["v1", "v2", "v3", "v4"], default="v1")
    ap.add_argument("--planner", choices=["scripted", "llm"], default="scripted")
    args = ap.parse_args(argv)
    v2, v3 = args.version == "v2", args.version in ("v3", "v4")  # v3 = a fresh partition
    use_llm = args.planner == "llm"
    if use_llm and not v3:
        raise SystemExit("the LLM planner is only evaluated on fresh partitions (v3, v4)")
    suffix = f"_{args.planner}" if v3 else ""
    name = f"agent_{args.version}{suffix}" if v3 else "agent_v2" if v2 else RESULT_NAME
    tag = f"agent-frozen-{args.version}" if v3 else "agent-frozen-v2" if v2 else FROZEN_TAG
    from harness.agent.models import RunBudget
    from harness.agent.planners import LLMPlanner, ScriptedPlanner

    head = assert_frozen_checkout(tag)
    budget = RunBudget(flaml_budget_s=FLAML_BUDGET_S).model_dump()
    factory: Callable[[], Any] | None = None
    if use_llm:
        from harness.gateway.live import (
            GEMINI_MODEL,
            GROQ_FALLBACK,
            GROQ_PRIMARY,
            build_live_gateway,
        )

        cassette = Path(f"tests/cassettes/{args.version}_llm.jsonl")
        llm_ver = 2 if args.version == "v4" else 1  # v3 ran planner v1; v4 runs the S22 planner v2
        fp = LLMPlanner(build_live_gateway(cassette), version=llm_ver).config_fingerprint()
        fp["providers"] = ["groq", "gemini"]
        fp["models"] = [GROQ_PRIMARY, GROQ_FALLBACK, GEMINI_MODEL]

        def factory() -> Any:
            return LLMPlanner(build_live_gateway(cassette), version=llm_ver)

    else:
        fp = ScriptedPlanner().config_fingerprint()
    if v3:
        fp["partition"] = args.version
    digest = freeze_hash(budget, fp)
    base_name = f"baselines_{args.version}" if v3 else "baselines_v0"
    base = json.loads((RESULTS_DIR / f"{base_name}.json").read_text(encoding="utf-8"))
    refs = {k: v for k, v in base["results"]["per_task"].items()}
    specs = (
        (load_registry_v4() if args.version == "v4" else load_registry_v3())
        if v3
        else load_registry()
    )
    work = Path(f"data/agent_bench_{args.version}{suffix}" if v2 or v3 else "data/agent_bench")
    work.mkdir(parents=True, exist_ok=True)
    prior = None
    label = ""
    if v2:
        v1 = json.loads((RESULTS_DIR / "agent_v1.json").read_text(encoding="utf-8"))
        prior = v1["results"]["per_task"]
        label = "v2 - post-hoc, fixes informed by v1 failures."
    if use_llm:  # paired LLM-minus-scripted on the same partition
        sp = RESULTS_DIR / f"agent_{args.version}_scripted.json"
        if sp.exists():
            prior = json.loads(sp.read_text(encoding="utf-8"))["results"]["per_task"]
    if v3:
        label = f"{args.version} unseen partition, {args.planner} planner."
    run_tag = f"{args.version}{args.planner[0]}" if v3 else "v2" if v2 else ""
    if use_llm:
        from harness.gateway.limits import UsageLedger
        from harness.gateway.live import USAGE_PATH

        used = UsageLedger(USAGE_PATH)
        left = 120 - max(used.used("groq"), used.used("gemini"))
        if left < 30 and not args.resume:
            raise SystemExit(
                f"refusing to start: only {left} requests left today on the best provider"
            )
    path = run_benchmark(
        specs, lambda s: real_run_one(s, work, run_tag, factory),
        refs, digest=digest, ledger_path=ledger.LEDGER_PATH, out_dir=RESULTS_DIR,
        resume=args.resume, meta={"git_sha": head}, result_name=name, prior=prior, label=label,
        planner=args.planner, llm="real" if use_llm else "none",
    )  # fmt: skip
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
