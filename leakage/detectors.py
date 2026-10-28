"""Deterministic leakage and data-quality detectors.

Every detector has the signature `detect_x(ctx) -> list[Finding]` and uses only the frame, the
target name and `DetectionMeta` (seeded). No labels files, no dataset-name special cases.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from datastory.roles import ID_NAME, Roles, infer_roles
from leakage.config import load_thresholds
from leakage.models import Budget, DetectionMeta, Finding, FindingType, Severity
from leakage.scoring import (
    cv_score,
    direct_gini,
    encode_features,
    encode_target,
    group_splits,
    infer_task,
    random_splits,
    single_feature_gini,
    time_splits,
)


@dataclass
class Context:
    df: pd.DataFrame
    target: str
    meta: DetectionMeta
    task: str
    y: np.ndarray
    roles: Roles
    thr: dict[str, Any]
    budget: Budget

    @property
    def features(self) -> list[str]:
        return [c for c in self.df.columns if c != self.target]


def make_context(
    df: pd.DataFrame,
    target: str,
    meta: DetectionMeta | None = None,
    thresholds: dict[str, Any] | None = None,
) -> Context:
    meta = meta or DetectionMeta()
    if target not in df.columns:
        raise KeyError(f"target {target!r} not in columns")
    df = df.dropna(subset=[target]).reset_index(drop=True)
    if len(df) > meta.max_cv_rows:
        df = df.sample(n=meta.max_cv_rows, random_state=meta.seed).reset_index(drop=True)
    task = meta.task_type or infer_task(df[target])
    return Context(
        df=df,
        target=target,
        meta=meta,
        task=task,
        y=encode_target(df[target], task),
        roles=infer_roles(df, target),
        thr=thresholds or load_thresholds(),
        budget=Budget(meta.time_budget_s),
    )


def _severity(value: float, lo: float, hi: float) -> Severity:
    return Severity.HIGH if value >= hi else Severity.MEDIUM


def _confidence(value: float, lo: float, hi: float) -> float:
    span = max(hi - lo, 1e-9)
    return float(np.clip(0.5 + 0.5 * (value - lo) / span, 0.5, 1.0))


# --- target leakage / post-outcome / high-cardinality proxy ---------------------------------
def detect_target_leakage(ctx: Context) -> list[Finding]:
    t = ctx.thr["target_leakage"]
    po = ctx.thr["post_outcome"]
    hc = ctx.thr["high_cardinality_proxy"]
    skip = set(ctx.roles.id_like) | set(ctx.roles.time_like)
    hints = [h.lower() for h in po["hints"]]
    out: list[Finding] = []
    n = len(ctx.df)
    for col in ctx.features:
        if col in skip or ctx.df[col].nunique(dropna=True) < 2:
            continue
        ctx.budget.check()
        g = single_feature_gini(ctx.df[col], ctx.y, ctx.task, ctx.meta.seed, t["max_depth"])
        tokens = re.split(r"[^a-z0-9]+", col.lower())
        hint = next((h for h in hints if any(h in tok for tok in tokens)), None)
        categorical = not pd.api.types.is_numeric_dtype(ctx.df[col])
        high_card = categorical and ctx.df[col].nunique() / n >= hc["min_unique_ratio"]
        ev: dict[str, Any] = {"single_feature_gini": round(g, 4), "metric": "gini"}
        if hint is not None and g >= po["min_gini"]:
            ev["name_hint"] = hint
            out.append(
                Finding(
                    type=FindingType.POST_OUTCOME,
                    severity=_severity(g, po["min_gini"], t["high_gini"]),
                    columns=[col],
                    evidence=ev,
                    confidence=_confidence(g, po["min_gini"], t["high_gini"]),
                )
            )
        elif g >= t["min_gini"]:
            ftype = FindingType.HIGH_CARDINALITY_PROXY if high_card else FindingType.TARGET_LEAKAGE
            out.append(
                Finding(
                    type=ftype,
                    severity=_severity(g, t["min_gini"], t["high_gini"]),
                    columns=[col],
                    evidence=ev,
                    confidence=_confidence(g, t["min_gini"], t["high_gini"]),
                )
            )
    return out


# --- duplicates -----------------------------------------------------------------------------
def _row_keys(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    work = df[cols].copy()
    for c in cols:
        if pd.api.types.is_float_dtype(work[c]):
            work[c] = work[c].round(6)
    return pd.util.hash_pandas_object(work.astype(str), index=False)


def detect_duplicates(ctx: Context) -> list[Finding]:
    t = ctx.thr["duplicate_rows"]
    cols = [c for c in ctx.df.columns if c not in ctx.roles.id_like]
    if not cols or len(ctx.df) < 2:
        return []
    keys = _row_keys(ctx.df, cols)
    dup_mask = keys.duplicated(keep="first")
    frac = float(dup_mask.mean())
    if frac < t["min_fraction"]:
        return []
    groups = ctx.df.assign(_k=keys).groupby("_k")[ctx.target].nunique()
    consistent = float((groups[groups.index.isin(keys[dup_mask])] == 1).mean())
    return [
        Finding(
            type=FindingType.DUPLICATE_ROWS,
            severity=_severity(frac, t["min_fraction"], t["high_fraction"]),
            columns=[],
            evidence={
                "duplicate_rows": int(dup_mask.sum()),
                "fraction": round(frac, 4),
                "label_consistent_fraction": round(consistent, 4),
            },
            confidence=_confidence(frac, t["min_fraction"], t["high_fraction"]),
        )
    ]


def detect_contamination(ctx: Context) -> list[Finding]:
    hold = ctx.meta.holdout
    t = ctx.thr["train_test_contamination"]
    if hold is None or hold.empty:
        return []
    cols = [c for c in ctx.df.columns if c in hold.columns and c not in ctx.roles.id_like]
    train_keys = set(_row_keys(ctx.df, cols))
    hold_keys = _row_keys(hold, cols)
    frac = float(hold_keys.isin(train_keys).mean())
    if frac < t["min_fraction"]:
        return []
    return [
        Finding(
            type=FindingType.TRAIN_TEST_CONTAMINATION,
            severity=Severity.HIGH if frac >= 0.1 else Severity.MEDIUM,
            columns=[],
            evidence={"holdout_rows_in_train_fraction": round(frac, 4), "n_holdout": len(hold)},
            confidence=_confidence(frac, t["min_fraction"], 0.1),
        )
    ]


# --- temporal and group gaps ----------------------------------------------------------------
def _gap_finding(
    ftype: FindingType, col: str, random_s: float, other_s: float, t: dict[str, Any], key: str
) -> Finding | None:
    gap = random_s - other_s
    if not np.isfinite(gap) or gap < t["min_gap"]:
        return None
    return Finding(
        type=ftype,
        severity=_severity(gap, t["min_gap"], t["high_gap"]),
        columns=[col],
        evidence={
            "random_cv": round(random_s, 4),
            key: round(other_s, 4),
            "gap": round(gap, 4),
            "metric": "auc (classification) or r2 (regression)",
        },
        confidence=_confidence(gap, t["min_gap"], t["high_gap"]),
    )


def detect_temporal(ctx: Context) -> list[Finding]:
    t = ctx.thr["temporal_leakage"]
    out: list[Finding] = []
    cols = ctx.roles.time_like[: t["max_candidates"]]
    if not cols:
        return out
    x = encode_features(ctx.df, ctx.features)
    rand = cv_score(
        x, ctx.y, ctx.task, random_splits(ctx.y, ctx.task, ctx.meta.seed), ctx.meta.seed
    )
    for col in cols:
        ctx.budget.check()
        order = encode_features(ctx.df, [col])[:, 0]
        timed = cv_score(x, ctx.y, ctx.task, time_splits(order), ctx.meta.seed)
        f = _gap_finding(FindingType.TEMPORAL_LEAKAGE, col, rand, timed, t, "time_ordered_cv")
        if f:
            out.append(f)
    return out


def _group_constant_columns(df: pd.DataFrame, group: str, skip: set[str]) -> list[str]:
    out = []
    for c in df.columns:
        if c == group or c in skip:
            continue
        per_group = df.groupby(group)[c].nunique(dropna=False)
        if (per_group == 1).mean() >= 0.95:
            out.append(c)
    return out


def detect_group(ctx: Context) -> list[Finding]:
    t = ctx.thr["group_leakage"]
    out: list[Finding] = []
    cols = ctx.roles.group_like[: t["max_candidates"]]
    if not cols:
        return out
    x = encode_features(ctx.df, ctx.features)
    rand = cv_score(
        x, ctx.y, ctx.task, random_splits(ctx.y, ctx.task, ctx.meta.seed), ctx.meta.seed
    )
    for col in cols:
        ctx.budget.check()
        groups = pd.factorize(ctx.df[col].astype(str))[0]
        grouped = cv_score(x, ctx.y, ctx.task, group_splits(groups), ctx.meta.seed)
        f = _gap_finding(FindingType.GROUP_LEAKAGE, col, rand, grouped, t, "group_cv")
        if f:
            const = _group_constant_columns(
                ctx.df[ctx.features], col, set(ctx.roles.time_like) | set(ctx.roles.id_like)
            )
            ev = dict(f.evidence)
            ev["group_constant_columns"] = const
            out.append(f.model_copy(update={"columns": [col, *const][:6], "evidence": ev}))
    return out


# --- id-like columns ------------------------------------------------------------------------
def detect_id_leak(ctx: Context) -> list[Finding]:
    t = ctx.thr["id_leak"]
    out: list[Finding] = []
    for col in ctx.roles.id_like:
        ctx.budget.check()
        g = direct_gini(ctx.df[col], ctx.y, ctx.task)
        if g >= t["min_gini"]:
            out.append(
                Finding(
                    type=FindingType.ID_LEAK,
                    severity=_severity(g, t["min_gini"], t["high_gini"]),
                    columns=[col],
                    evidence={"rank_gini": round(g, 4), "unique_ratio": 1.0},
                    confidence=_confidence(g, t["min_gini"], t["high_gini"]),
                )
            )
        else:
            out.append(
                Finding(
                    type=FindingType.ID_LIKE,
                    severity=Severity.LOW,
                    columns=[col],
                    evidence={"rank_gini": round(g, 4), "advice": "exclude from features"},
                    confidence=0.6 if ID_NAME.search(col) else 0.5,
                )
            )
    return out


# --- quality / safety -----------------------------------------------------------------------
def detect_unit_mismatch(ctx: Context) -> list[Finding]:
    t = ctx.thr["unit_mismatch"]
    out: list[Finding] = []
    skip = set(ctx.roles.id_like) | set(ctx.roles.time_like)
    for col in ctx.features:
        s = ctx.df[col]
        if col in skip or not pd.api.types.is_numeric_dtype(s) or s.nunique() < 20:
            continue
        v = s.to_numpy(dtype=float)
        v = v[np.isfinite(v)]
        med = np.median(v)
        mad = np.median(np.abs(v - med))
        if mad == 0:
            continue
        frac = float((np.abs(v - med) / (1.4826 * mad) > t["robust_z"]).mean())
        if frac >= t["min_fraction"]:
            out.append(
                Finding(
                    type=FindingType.UNIT_MISMATCH,
                    severity=Severity.MEDIUM,
                    columns=[col],
                    evidence={
                        "fraction_beyond_robust_z": round(frac, 4),
                        "robust_z": t["robust_z"],
                    },
                    confidence=_confidence(frac, t["min_fraction"], 0.5),
                )
            )
    return out


def detect_suspicious_names(ctx: Context) -> list[Finding]:
    t = ctx.thr["suspicious_column_name"]
    pats = [re.compile(p, re.IGNORECASE) for p in t["patterns"]]
    out: list[Finding] = []
    for col in ctx.df.columns:
        name = str(col)
        hit = next((p.pattern for p in pats if p.search(name)), None)
        if hit or len(name) > t["max_length"]:
            out.append(
                Finding(
                    type=FindingType.SUSPICIOUS_COLUMN_NAME,
                    severity=Severity.HIGH,
                    columns=[name],
                    evidence={"pattern": hit or "length", "length": len(name)},
                    confidence=0.9 if hit else 0.6,
                )
            )
    return out


DETECTORS: dict[str, Callable[[Context], list[Finding]]] = {
    "target_leakage": detect_target_leakage,
    "duplicates": detect_duplicates,
    "contamination": detect_contamination,
    "temporal": detect_temporal,
    "group": detect_group,
    "id": detect_id_leak,
    "unit_mismatch": detect_unit_mismatch,
    "suspicious_names": detect_suspicious_names,
}


def detect(
    df: pd.DataFrame,
    target: str,
    meta: DetectionMeta | None = None,
    thresholds: dict[str, Any] | None = None,
    only: list[str] | None = None,
) -> list[Finding]:
    """Run all (or `only`) detectors. Output order is deterministic."""
    ctx = make_context(df, target, meta, thresholds)
    findings: list[Finding] = []
    for name, fn in DETECTORS.items():
        if only is None or name in only:
            findings.extend(fn(ctx))
    return findings
