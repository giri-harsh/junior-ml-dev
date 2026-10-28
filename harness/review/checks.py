"""Deterministic reviewer checks (PRD S17). Code decides; an LLM reviewer may only add to this.

Heuristic limits are explicit: the AST check sees only literal sklearn-style patterns in one file.
"""

from __future__ import annotations

import ast
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from benchmarks.metrics import passes
from leakage.models import Finding, Severity

TRANSFORMERS = {
    "StandardScaler", "MinMaxScaler", "RobustScaler", "OneHotEncoder", "OrdinalEncoder",
    "TargetEncoder", "SimpleImputer", "KNNImputer", "PCA", "SelectKBest", "PolynomialFeatures",
    "QuantileTransformer", "PowerTransformer",
}  # fmt: skip
PIPELINES = {"Pipeline", "make_pipeline", "ColumnTransformer", "make_column_transformer"}
SEEDED = {
    "RandomForestClassifier", "RandomForestRegressor", "LogisticRegression", "KFold",
    "StratifiedKFold", "GroupKFold", "train_test_split", "XGBClassifier", "LGBMClassifier",
    "GradientBoostingClassifier", "ExtraTreesClassifier",
}  # fmt: skip
Verdict = Literal["APPROVE", "REQUEST_CHANGES"]


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    detail: str


class ReviewVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    checks: dict[str, CheckResult]


def _name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def check_pipeline_ast(code: str) -> CheckResult:
    """Transformers must be fitted only inside a Pipeline/ColumnTransformer, never on full data."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return CheckResult(passed=False, detail=f"syntax error line {exc.lineno}")
    transformer_vars: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            cls = _name(node.value.func)
            if cls in TRANSFORMERS:
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        transformer_vars[t.id] = cls
    inside_pipeline: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _name(node.func) in PIPELINES:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and sub.id in transformer_vars:
                    inside_pipeline.add(sub.id)
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            is_fit = node.func.attr in {"fit", "fit_transform"}
            if is_fit:
                base = node.func.value
                if isinstance(base, ast.Name) and base.id in transformer_vars:
                    if base.id not in inside_pipeline:
                        problems.append(
                            f"{transformer_vars[base.id]} '{base.id}' fitted outside a pipeline "
                            f"(line {node.lineno})"
                        )
                elif isinstance(base, ast.Call) and _name(base.func) in TRANSFORMERS:
                    problems.append(
                        f"{_name(base.func)}().{node.func.attr} on raw data (line {node.lineno})"
                    )
    return CheckResult(
        passed=not problems, detail="; ".join(problems) or "no out-of-pipeline fits found"
    )


def check_seeds(code: str) -> CheckResult:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return CheckResult(passed=False, detail="syntax error")
    missing = []
    seeded_globally = "random.seed" in code or "np.random.seed" in code
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _name(node.func) in SEEDED:
            kws = {k.arg for k in node.keywords}
            if "random_state" not in kws and "seed" not in kws and not seeded_globally:
                missing.append(f"{_name(node.func)} (line {node.lineno})")
    return CheckResult(
        passed=not missing, detail="missing seed: " + ", ".join(missing) if missing else "seeds set"
    )


def check_split_integrity(
    folds: list[tuple[np.ndarray, np.ndarray]],
    n_rows: int,
    row_hash: pd.Series | None = None,
    groups: np.ndarray | None = None,
    time: np.ndarray | None = None,
) -> CheckResult:
    """Validation indices must be disjoint from train; duplicates, groups and time respected."""
    problems = []
    seen_val: set[int] = set()
    for i, (tr, va) in enumerate(folds):
        if set(tr) & set(va):
            problems.append(f"fold {i}: train and validation share rows")
        if seen_val & set(va):
            problems.append(f"fold {i}: validation rows reused across folds")
        seen_val |= set(va)
        if max(list(tr) + list(va), default=-1) >= n_rows:
            problems.append(f"fold {i}: index out of range")
        if row_hash is not None and set(row_hash.iloc[tr]) & set(row_hash.iloc[va]):
            problems.append(f"fold {i}: identical rows on both sides")
        if groups is not None and set(groups[tr]) & set(groups[va]):
            problems.append(f"fold {i}: a group appears in train and validation")
        if time is not None and len(tr) and len(va) and time[tr].max() > time[va].min():
            problems.append(f"fold {i}: training data is later than validation data")
    return CheckResult(passed=not problems, detail="; ".join(problems) or "folds are clean")


def check_baseline_margin(
    agent: float, linear: float, dummy: float, metric: str, scale: float | None = None
) -> CheckResult:
    ok = passes(agent, linear, metric, scale) and passes(agent, dummy, metric, scale)
    return CheckResult(passed=ok, detail=f"agent={agent:.4f} linear={linear:.4f} dummy={dummy:.4f}")


def check_train_val_gap(train: float, val: float, max_gap: float = 0.15) -> CheckResult:
    gap = abs(train - val)
    return CheckResult(passed=gap <= max_gap, detail=f"gap={gap:.4f} (limit {max_gap})")


def check_cv_stability(fold_scores: list[float], max_cv_ratio: float = 0.25) -> CheckResult:
    mean = float(np.mean(fold_scores))
    ratio = float(np.std(fold_scores) / abs(mean)) if mean else float("inf")
    return CheckResult(passed=ratio <= max_cv_ratio, detail=f"std/mean={ratio:.3f}")


def check_leakage_resolved(findings: list[Finding], resolved_columns: set[str]) -> CheckResult:
    open_ = [
        f for f in findings
        if f.severity in {Severity.MEDIUM, Severity.HIGH} and not set(f.columns) <= resolved_columns
    ]  # fmt: skip
    return CheckResult(
        passed=not open_,
        detail="; ".join(f"{f.type.value}:{','.join(f.columns)}" for f in open_) or "none open",
    )


def check_metric_matches_task(metric: str, task_type: str) -> CheckResult:
    ok = (task_type == "regression") == (metric in {"rmse", "mae"})
    return CheckResult(passed=ok, detail=f"metric={metric} task={task_type}")


def review(code: str, **evidence: Any) -> ReviewVerdict:
    """Run every check for which evidence was provided. Any failure => REQUEST_CHANGES."""
    checks: dict[str, CheckResult] = {
        "pipeline_ast": check_pipeline_ast(code),
        "seeds_set": check_seeds(code),
    }
    if "folds" in evidence:
        checks["split_integrity"] = check_split_integrity(
            evidence["folds"], evidence["n_rows"], evidence.get("row_hash"),
            evidence.get("groups"), evidence.get("time"),
        )  # fmt: skip
    if {"agent", "linear", "dummy", "metric"} <= evidence.keys():
        checks["baseline_margin"] = check_baseline_margin(
            evidence["agent"],
            evidence["linear"],
            evidence["dummy"],
            evidence["metric"],
            evidence.get("scale"),
        )
    if {"train_score", "val_score"} <= evidence.keys():
        checks["train_val_gap"] = check_train_val_gap(
            evidence["train_score"], evidence["val_score"]
        )
    if "fold_scores" in evidence:
        checks["cv_stability"] = check_cv_stability(evidence["fold_scores"])
    if "findings" in evidence:
        checks["leakage_resolved"] = check_leakage_resolved(
            evidence["findings"], set(evidence.get("resolved_columns", ()))
        )
    if {"metric", "task_type"} <= evidence.keys():
        checks["metric_matches_task"] = check_metric_matches_task(
            evidence["metric"], evidence["task_type"]
        )
    ok = all(c.passed for c in checks.values())
    return ReviewVerdict(verdict="APPROVE" if ok else "REQUEST_CHANGES", checks=checks)
