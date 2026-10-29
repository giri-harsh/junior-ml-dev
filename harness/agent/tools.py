"""Tool adapters: bind symbolic step args to the task, call the server services, reduce state.

The adapters call the same service functions the MCP servers expose (in-process; the stdio path
is covered by per-server smoke tests). Planners never supply paths, targets or run ids.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from harness.agent.models import RunConfig, StepRecord
from harness.policies.code_policy import check_code
from harness.review.checks import (
    CheckResult,
    check_baseline_margin,
    check_leakage_resolved,
    check_metric_matches_task,
    check_train_val_gap,
)
from leakage.models import Finding, FindingType, Severity
from mcp_servers.data_tools import service as dt
from mcp_servers.experiments import service as ex

DROPPABLE = {
    FindingType.TARGET_LEAKAGE,
    FindingType.POST_OUTCOME,
    FindingType.HIGH_CARDINALITY_PROXY,
    FindingType.ID_LEAK,
    FindingType.ID_LIKE,
}


@dataclass
class ToolCtx:
    cfg: RunConfig
    state: dict[str, Any]
    records: list[StepRecord] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)  # injected: approvals, token, run_root


Tool = Callable[[ToolCtx, dict[str, Any]], dict[str, Any]]
Reducer = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], None]  # state, args, result


def _spec(ctx: ToolCtx) -> dict[str, Any]:
    t = ctx.cfg.task
    return {
        "data_path": t.data_path, "target": t.target, "task_type": t.task_type,
        "metric": t.metric, "seed": t.seed, "drop_columns": list(ctx.state.get("dropped", [])),
    }  # fmt: skip


# --- data-tools -----------------------------------------------------------------------------
def profile_dataset(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    t = ctx.cfg.task
    res = dt.profile_dataset(dt.ProfileRequest(path=t.data_path, target=t.target, run_id=t.name))
    p = res.profile
    return {
        "n_rows": p.n_rows, "n_cols": p.n_cols, "duplicate_rows": p.duplicate_rows,
        "constant_columns": p.constant_columns, "suspected_id": p.suspected_id,
        "columns": [
            {"name": c.name, "missing_frac": c.missing_frac, "semantic_type": c.semantic_type}
            for c in p.columns[:60]
        ],
        "target": p.target.model_dump(mode="json") if p.target else None,
    }  # fmt: skip


def detect_leakage(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    t = ctx.cfg.task
    res = dt.detect_leakage(
        dt.LeakageRequest(path=t.data_path, target=t.target, run_id=t.name, time_budget_s=60)
    )
    return {
        "findings": [f.model_dump(mode="json") for f in res.findings],
        "counts": res.counts,
        "thresholds_sha256": res.thresholds_sha256,
    }


def decide_leakage(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    """Drop columns implicated in medium/high proxy/ID findings; record what stays unresolved."""
    findings = [Finding.model_validate(f) for f in ctx.state.get("findings", [])]
    dropped: list[str] = []
    for f in findings:
        if f.severity in {Severity.MEDIUM, Severity.HIGH} and f.type in DROPPABLE:
            dropped += [c for c in f.columns if c not in dropped and c != ctx.cfg.task.target]
    unresolved = [
        f"{f.type.value}:{','.join(f.columns)}" for f in findings
        if f.severity in {Severity.MEDIUM, Severity.HIGH} and not set(f.columns) <= set(dropped)
    ]  # fmt: skip
    return {"dropped": dropped, "unresolved": unresolved}


# --- experiments ----------------------------------------------------------------------------
def train_model(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    family = args["family"]
    budget = ctx.cfg.budget.flaml_budget_s if family == "flaml" else 20.0
    req = ex.TrainRequest(
        **_spec(ctx), run_id=ctx.cfg.run_id, family=family,
        params=args.get("params", {}), time_budget_s=max(1.0, budget),
    )  # fmt: skip
    return ex.train_model(req).model_dump(mode="json", exclude={"features"})


def tune_model(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    req = ex.TuneRequest(
        **_spec(ctx), run_id=ctx.cfg.run_id, family=args["family"],
        n_trials=max(1, ctx.cfg.budget.tune_trials), time_budget_s=30,
    )  # fmt: skip
    return ex.tune_model(req).model_dump(mode="json", exclude={"features"})


def compare_models(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    # No normalisation here: benchmark references are test-set scores, validation scores are not
    # on the same split (ADR-016). Normalisation happens in the benchmark driver on test scores.
    res = ex.compare_models(ex.CompareRequest(run_id=ctx.cfg.run_id))
    return res.model_dump(mode="json")


def refit_full(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    rec = ex.refit_full(ex.RefitRequest(run_id=ctx.cfg.run_id, model_id=args["model_id"]))
    return rec.model_dump(mode="json", exclude={"features"})


def predict(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    path = ctx.cfg.task.test_features_path
    if not path:
        raise ex.ExperimentError("no test features configured")
    res = ex.predict(
        ex.PredictRequest(run_id=ctx.cfg.run_id, model_id=args["model_id"], features_path=path)
    )
    return res.model_dump(mode="json")


# --- sandbox-exec ---------------------------------------------------------------------------
def check_code_policy(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    res = check_code(str(args.get("code", "")))
    return {"allowed": res.allowed, "violations": [str(v) for v in res.violations][:10]}


# --- reviewer (deterministic checks only) ---------------------------------------------------
COMPLEXITY = {"dummy": 0, "linear": 1, "rf": 2, "hgb": 3, "flaml": 4}
TIE_REL = 0.005  # fixed a priori: validation scores within 0.5% of the best are a tie


def simplicity_order(board: list[str], models: dict[str, dict[str, Any]]) -> list[str]:
    """Validation score only; models within TIE_REL of the best are ordered simplest first."""
    if not board:
        return board
    best = models[board[0]]["val_score"]
    tied = [m for m in board if abs(models[m]["val_score"] - best) <= TIE_REL * abs(best)]
    tied.sort(key=lambda m: (COMPLEXITY.get(models[m]["family"], 9), board.index(m)))
    return tied + [m for m in board if m not in tied]


def review(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    st, t = ctx.state, ctx.cfg.task
    models: dict[str, dict[str, Any]] = st.get("models", {})
    board = simplicity_order([r["model_id"] for r in st.get("leaderboard", [])], models)
    higher = t.metric not in {"rmse", "mae"}
    by_family = {m["family"]: m for m in models.values() if m["fit_on"] == "train_split"}
    dummy = by_family.get("dummy", {}).get("val_score")
    linear = by_family.get("linear", {}).get("val_score")
    chosen, gap_note = (board[0] if board else None), "no models"
    for mid in board:  # first model whose train/val gap is acceptable
        m = models[mid]
        if check_train_val_gap(m["train_score"], m["val_score"], 0.15 if higher else 1e9).passed:
            chosen = mid
            break
    checks: dict[str, CheckResult] = {
        "metric_matches_task": check_metric_matches_task(t.metric, t.task_type)
    }
    if chosen is not None:
        m = models[chosen]
        gap_note = f"chosen={chosen}"
        checks["train_val_gap"] = check_train_val_gap(
            m["train_score"], m["val_score"], 0.15 if higher else 1e9
        )
        if dummy is not None and linear is not None:
            scale = None if higher else float(dummy)
            ref = dummy if m["family"] == "linear" else linear  # linear cannot beat itself
            checks["baseline_margin"] = check_baseline_margin(
                m["val_score"], ref, dummy, t.metric, scale
            )
    findings = [Finding.model_validate(f) for f in st.get("findings", [])]
    checks["leakage_resolved"] = check_leakage_resolved(findings, set(st.get("dropped", [])))
    verdict = "APPROVE" if all(c.passed for c in checks.values()) else "REQUEST_CHANGES"
    return {
        "verdict": verdict, "chosen": chosen, "note": gap_note,
        "checks": {k: c.model_dump() for k, c in checks.items()},
    }  # fmt: skip


# --- reducers -------------------------------------------------------------------------------
def _r_profile(st: dict[str, Any], args: dict[str, Any], res: dict[str, Any]) -> None:
    st["profile"] = res


def _r_leak(st: dict[str, Any], args: dict[str, Any], res: dict[str, Any]) -> None:
    st["findings"] = res["findings"]
    st["leakage_counts"] = res["counts"]


def _r_decide(st: dict[str, Any], args: dict[str, Any], res: dict[str, Any]) -> None:
    st["dropped"] = res["dropped"]
    st["unresolved"] = res["unresolved"]


def _r_model(st: dict[str, Any], args: dict[str, Any], res: dict[str, Any]) -> None:
    st.setdefault("models", {})[res["model_id"]] = {
        k: res[k] for k in ("family", "val_score", "train_score", "fit_on", "fit_s", "params")
    }


def _r_compare(st: dict[str, Any], args: dict[str, Any], res: dict[str, Any]) -> None:
    st["leaderboard"] = res["leaderboard"]
    st["best"] = res["best_model_id"]


def _r_review(st: dict[str, Any], args: dict[str, Any], res: dict[str, Any]) -> None:
    st["review"] = res
    st["chosen"] = res["chosen"]


def _r_refit(st: dict[str, Any], args: dict[str, Any], res: dict[str, Any]) -> None:
    st["final_model_id"] = res["model_id"]
    _r_model(st, args, res)


def _r_predict(st: dict[str, Any], args: dict[str, Any], res: dict[str, Any]) -> None:
    st["predictions_path"] = res["out_path"]


def _r_nothing(st: dict[str, Any], args: dict[str, Any], res: dict[str, Any]) -> None:
    return None


REGISTRY: dict[str, tuple[Tool, Reducer]] = {
    "profile_dataset": (profile_dataset, _r_profile),
    "detect_leakage": (detect_leakage, _r_leak),
    "decide_leakage": (decide_leakage, _r_decide),
    "train_model": (train_model, _r_model),
    "tune_model": (tune_model, _r_model),
    "compare_models": (compare_models, _r_compare),
    "review": (review, _r_review),
    "refit_full": (refit_full, _r_refit),
    "predict": (predict, _r_predict),
    "check_code_policy": (check_code_policy, _r_nothing),
}
