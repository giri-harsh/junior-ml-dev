"""Deterministic leakage and data-quality detectors (v1: evidence-confirmation layer).

Rules of the road
- Every detector is `detect_x(ctx) -> list[Finding]`; only the frame, target name and seeded
  `DetectionMeta` are used. No labels files, no dataset-name special cases.
- Medium/high severity needs CONFIRMING evidence (a seeded probe or a structural test).
  Name hints and other suspicions alone produce LOW notes.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold

from datastory.roles import ID_NAME, Roles, infer_roles
from leakage.config import load_thresholds
from leakage.models import Budget, DetectionMeta, DetectionTimeout, Finding, FindingType, Severity
from leakage.probes import Probe, did_stats, loco_drop, stable, subsample_indices
from leakage.scoring import (
    direct_gini,
    encode_features,
    encode_target,
    group_splits,
    infer_task,
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
    partial: list[str] = field(default_factory=list)

    @property
    def features(self) -> list[str]:
        return [c for c in self.df.columns if c != self.target]

    def probe(self, rows_cap: int) -> Probe:
        idx = subsample_indices(len(self.df), rows_cap, self.meta.seed)
        sub = self.df.iloc[idx].reset_index(drop=True)
        return Probe(
            x=encode_features(sub, self.features),
            y=self.y[idx],
            cols=self.features,
            task=self.task,
            seed=self.meta.seed,
        )


CELL_CAP = 600_000  # rows x columns the detectors are asked to handle in one go
MAX_COLS = 120
MIN_ROWS = 2000


def _bound_size(df: pd.DataFrame, target: str, seed: int, partial: list[str]) -> pd.DataFrame:
    """Keep detection inside its budget on any size: keep the 120 columns most associated with
    the target (cheap rank correlation on <=2000 rows), then sample rows down to CELL_CAP cells."""
    feats = [c for c in df.columns if c != target]
    if len(feats) > MAX_COLS:
        sub = df.sample(n=min(len(df), 2000), random_state=seed)
        y = encode_target(sub[target], infer_task(sub[target]))
        x = encode_features(sub, feats)
        with np.errstate(all="ignore"):
            corr = np.abs(
                np.nan_to_num(np.array([np.corrcoef(x[:, j], y)[0, 1] for j in range(x.shape[1])]))
            )
        keep = set(np.argsort(-corr, kind="stable")[:MAX_COLS].tolist())
        df = df[[c for j, c in enumerate(feats) if j in keep] + [target]]
        partial.append(f"columns reduced to the {MAX_COLS} most target-associated of {len(feats)}")
    if len(df) * df.shape[1] > CELL_CAP and len(df) > MIN_ROWS:
        n = max(MIN_ROWS, CELL_CAP // df.shape[1])
        df = df.sample(n=n, random_state=seed).reset_index(drop=True)
        partial.append(f"rows sampled to {n} to bound cost")
    return df


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
    partial: list[str] = []
    if len(df) > meta.max_cv_rows:
        df = df.sample(n=meta.max_cv_rows, random_state=meta.seed).reset_index(drop=True)
        partial.append(f"rows sampled to {meta.max_cv_rows}")
    df = _bound_size(df, target, meta.seed, partial)
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
        partial=partial,
    )


def _severity(value: float, hi: float) -> Severity:
    return Severity.HIGH if value >= hi else Severity.MEDIUM


def _confidence(value: float, lo: float, hi: float) -> float:
    span = max(hi - lo, 1e-9)
    return float(np.clip(0.5 + 0.5 * (value - lo) / span, 0.5, 1.0))


def _low(ftype: FindingType, columns: list[str], reason: str, **evidence: Any) -> Finding:
    return Finding(
        type=ftype,
        severity=Severity.LOW,
        columns=columns,
        evidence={"unconfirmed": True, "reason": reason, **evidence},
        confidence=0.5,
    )


# --- target leakage / post-outcome / high-cardinality proxy ---------------------------------
def detect_target_leakage(ctx: Context) -> list[Finding]:
    t = ctx.thr["target_leakage"]
    po = ctx.thr["post_outcome"]
    hc = ctx.thr["high_cardinality_proxy"]
    skip = set(ctx.roles.id_like) | set(ctx.roles.time_like)
    hints = [h.lower() for h in po["hints"]]
    n = len(ctx.df)
    ginis: dict[str, float] = {}
    for col in ctx.features:
        if col in skip or ctx.df[col].nunique(dropna=True) < 2:
            continue
        ctx.budget.check()
        ginis[col] = single_feature_gini(
            ctx.df[col], ctx.y, ctx.task, ctx.meta.seed, t["max_depth"]
        )

    def hint_of(col: str) -> str | None:
        tokens = re.split(r"[^a-z0-9]+", col.lower())
        return next((h for h in hints if any(h in tok for tok in tokens)), None)

    candidates = sorted(ginis, key=lambda c: (-ginis[c], c))[: t["top_k"]]
    probe: Probe | None = None
    out: list[Finding] = []
    for col in candidates:
        g = ginis[col]
        hint = hint_of(col)
        floor = po["min_gini"] if hint else t["min_gini"]
        if g < floor:
            continue
        ctx.budget.check()
        others = sorted((v for c, v in ginis.items() if c != col), reverse=True)
        second = others[0] if others else 0.0
        dominance = g - second
        if probe is None:
            probe = ctx.probe(ctx.thr["probe"]["rows"])
        drop = loco_drop(probe, col, ctx.thr["probe"]["loco_repeats"])
        min_drop = po["min_loco_drop"] if hint else t["min_loco_drop"]
        confirmed = bool(np.isfinite(drop) and drop >= min_drop)
        if not hint:
            confirmed = confirmed and dominance >= t["min_dominance"]
        ev: dict[str, Any] = {
            "single_feature_gini": round(g, 4),
            "second_best_gini": round(second, 4),
            "dominance": round(dominance, 4),
            "loco_drop": None if not np.isfinite(drop) else round(drop, 4),
        }
        if hint:
            ev["name_hint"] = hint
        if not confirmed:
            out.append(
                _low(FindingType.TARGET_LEAKAGE, [col], "single-feature power unconfirmed", **ev)
            )
            continue
        categorical = not pd.api.types.is_numeric_dtype(ctx.df[col])
        high_card = categorical and ctx.df[col].nunique() / n >= hc["min_unique_ratio"]
        if hint:
            ftype = FindingType.POST_OUTCOME
        elif high_card:
            ftype = FindingType.HIGH_CARDINALITY_PROXY
        else:
            ftype = FindingType.TARGET_LEAKAGE
        out.append(
            Finding(
                type=ftype,
                severity=_severity(g, t["high_gini"]),
                columns=[col],
                evidence=ev,
                confidence=_confidence(g, floor, t["high_gini"]),
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


def _hi_res_columns(df: pd.DataFrame, cols: list[str], ratio: float) -> list[str]:
    """Near-continuous columns: chance collisions on them are negligible."""
    n = len(df)
    return [
        c
        for c in cols
        if pd.api.types.is_float_dtype(df[c]) and df[c].nunique(dropna=True) / n >= ratio
    ]


def detect_duplicates(ctx: Context) -> list[Finding]:
    t = ctx.thr["duplicate_rows"]
    cols = [c for c in ctx.features if c not in ctx.roles.id_like]
    if not cols or len(ctx.df) < 2:
        return []
    keys = _row_keys(ctx.df, cols)
    dup_mask = keys.duplicated(keep="first")
    frac = float(dup_mask.mean())
    if frac < t["min_fraction"]:
        return []
    per_key = ctx.df.assign(_k=keys).groupby("_k")[ctx.target].nunique()
    dup_keys = set(keys[dup_mask])
    conflicting = float((per_key[per_key.index.isin(dup_keys)] > 1).mean())
    hi_res = _hi_res_columns(ctx.df, cols, t["hi_res_ratio"])
    ev = {
        "duplicate_rows": int(dup_mask.sum()),
        "fraction": round(frac, 4),
        "conflicting_label_fraction": round(conflicting, 4),
        "high_resolution_columns_matched": len(hi_res),
    }
    if len(hi_res) < t["min_hi_res_cols"]:
        return [
            _low(
                FindingType.DUPLICATE_ROWS,
                [],
                "repeats are plausible chance collisions on low-resolution columns",
                **ev,
            )
        ]
    return [
        Finding(
            type=FindingType.DUPLICATE_ROWS,
            severity=_severity(frac, t["high_fraction"]),
            columns=[],
            evidence=ev,
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
    frac = float(_row_keys(hold, cols).isin(train_keys).mean())
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


# --- temporal and group: difference-in-differences probes ------------------------------------
def _median(res: dict[str, object]) -> float:
    return float(res["median"])  # type: ignore[arg-type]


def detect_temporal(ctx: Context) -> list[Finding]:
    t = ctx.thr["temporal_leakage"]
    pr = ctx.thr["probe"]
    cols = ctx.roles.time_like[: t["max_candidates"]]
    if not cols:
        return []
    probe = ctx.probe(pr["rows"])
    out: list[Finding] = []
    for col in cols:
        ctx.budget.check()
        order = probe.x[:, probe.cols.index(col)]
        res = did_stats(probe, [col], time_splits(order), pr["repeats"])
        stats = res["stats"]
        assert isinstance(stats, list)
        ev = {
            "did_stats": stats,
            "median": round(_median(res), 4) if stats else None,
            "gain_random_cv": res["gain_random"],
            "gain_time_cv": res["gain_other"],
        }
        if stable(stats, t["min_gap"]):
            med = _median(res)
            out.append(
                Finding(
                    type=FindingType.TEMPORAL_LEAKAGE,
                    severity=_severity(med, t["high_gap"]),
                    columns=[col],
                    evidence=ev,
                    confidence=_confidence(med, t["min_gap"], t["high_gap"]),
                )
            )
        else:
            out.append(_low(FindingType.TEMPORAL_LEAKAGE, [col], "time probe not confirmed", **ev))
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
    pr = ctx.thr["probe"]
    cols = ctx.roles.group_like[: t["max_candidates"]]
    if not cols:
        return []
    probe = ctx.probe(pr["rows"])
    out: list[Finding] = []
    for col in cols:
        ctx.budget.check()
        const = _group_constant_columns(
            ctx.df[ctx.features], col, set(ctx.roles.time_like) | set(ctx.roles.id_like)
        )
        groups = pd.factorize(probe.x[:, probe.cols.index(col)].astype(str))[0]
        res = did_stats(probe, [col, *const], group_splits(groups), pr["repeats"])
        stats = res["stats"]
        assert isinstance(stats, list)
        ev = {
            "did_stats": stats,
            "median": round(_median(res), 4) if stats else None,
            "gain_random_cv": res["gain_random"],
            "gain_group_cv": res["gain_other"],
            "group_constant_columns": const,
            "name_hint": bool(ID_NAME.search(col)),
        }
        if stable(stats, t["min_gap"]):
            med = _median(res)
            out.append(
                Finding(
                    type=FindingType.GROUP_LEAKAGE,
                    severity=_severity(med, t["high_gap"]),
                    columns=[col, *const][:6],
                    evidence=ev,
                    confidence=_confidence(med, t["min_gap"], t["high_gap"]),
                )
            )
        elif ev["name_hint"]:
            out.append(_low(FindingType.GROUP_LEAKAGE, [col], "group probe not confirmed", **ev))
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
                    severity=_severity(g, t["high_gini"]),
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
def _scale_mixture(v: np.ndarray, t: dict[str, Any]) -> dict[str, float] | None:
    """Same quantity at two scales: a heavy cluster whose spread is a power-of-ten multiple.

    Evidence required together: many points beyond the robust spread, a near-symmetric column
    (positive heavy tails alone are not unit errors) and a cluster-spread ratio within
    `ratio_tolerance` decades of 10^k, k >= 1.
    """
    x = v[np.isfinite(v)]
    if x.size < 40:
        return None
    med = float(np.median(x))
    dev = np.abs(x - med)
    mad = float(np.median(dev))
    if mad == 0:
        return None
    beyond = dev / (1.4826 * mad) > t["robust_z"]
    frac = float(beyond.mean())
    if not t["min_fraction"] <= frac <= 0.85:
        return None
    skew = abs(float(pd.Series(x).skew()))  # type: ignore[arg-type]
    if skew > t["max_abs_skew"]:
        return None
    ratio = float(np.median(dev[beyond]) / max(np.median(dev[~beyond]), 1e-12))
    lr = float(np.log10(ratio))
    k = round(lr)
    if k < 1 or abs(lr - k) > t["ratio_tolerance"]:
        return None
    return {"fraction_beyond": frac, "abs_skew": skew, "spread_ratio": ratio, "power_of_ten": k}


def detect_unit_mismatch(ctx: Context) -> list[Finding]:
    t = ctx.thr["unit_mismatch"]
    out: list[Finding] = []
    skip = set(ctx.roles.id_like) | set(ctx.roles.time_like)
    for col in ctx.features:
        s = ctx.df[col]
        if col in skip or not pd.api.types.is_numeric_dtype(s) or s.nunique() < 20:
            continue
        res = _scale_mixture(s.to_numpy(dtype=float), t)
        if res:
            out.append(
                Finding(
                    type=FindingType.UNIT_MISMATCH,
                    severity=Severity.MEDIUM,
                    columns=[col],
                    evidence={k: round(v, 4) for k, v in res.items()},
                    confidence=_confidence(res["fraction_beyond"], t["min_fraction"], 0.5),
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
        if hit:  # explicit instruction-like text: a safety finding, not a leakage heuristic
            out.append(
                Finding(
                    type=FindingType.SUSPICIOUS_COLUMN_NAME,
                    severity=Severity.HIGH,
                    columns=[name],
                    evidence={"pattern": hit, "length": len(name)},
                    confidence=0.9,
                )
            )
        elif len(name) > t["max_length"]:
            out.append(
                _low(
                    FindingType.SUSPICIOUS_COLUMN_NAME,
                    [name],
                    "unusually long name",
                    length=len(name),
                )
            )
    return out


# --- label noise (confident learning) -------------------------------------------------------
def _confident_joint(
    probs: np.ndarray, labels: np.ndarray, n_classes: int
) -> tuple[np.ndarray, np.ndarray]:
    """Northcutt-style confident joint with per-class thresholds, calibrated to class counts."""
    thresholds = np.array(
        [probs[labels == j, j].mean() if (labels == j).any() else 1.0 for j in range(n_classes)]
    )
    joint = np.zeros((n_classes, n_classes))
    suspect = np.full(len(labels), -1)
    for i, (p, y) in enumerate(zip(probs, labels, strict=True)):
        eligible = np.flatnonzero(p >= thresholds)
        if eligible.size:
            j = int(eligible[np.argmax(p[eligible])])
            joint[y, j] += 1
            if j != y:
                suspect[i] = j
    row = joint.sum(1, keepdims=True)
    counts = np.bincount(labels, minlength=n_classes).astype(float)[:, None]
    calibrated = joint / np.where(row == 0, 1, row) * counts
    total = calibrated.sum()
    return (calibrated / total if total else calibrated), suspect


def _is_ordinal_target(y: pd.Series) -> bool:
    """Numeric integer target with >=5 consecutive levels (ratings, quality scores).

    Confident learning assumes nominal classes; neighbouring ordinal levels are legitimately
    confusable, so a 'noise' estimate would just measure ordinality.
    """
    if not pd.api.types.is_numeric_dtype(y):
        return False
    v = pd.to_numeric(y, errors="coerce").dropna()
    if v.empty or not (v == v.round()).all():
        return False
    k = int(v.nunique())
    return k >= 5 and int(v.max() - v.min()) + 1 - k <= 1


def detect_label_noise(ctx: Context) -> list[Finding]:
    t = ctx.thr["label_noise"]
    if ctx.task == "regression":
        return [
            Finding(
                type=FindingType.LABEL_NOISE,
                severity=Severity.LOW,
                columns=[ctx.target],
                evidence={"applicable": False, "reason": "classification only"},
                confidence=1.0,
            )
        ]
    if _is_ordinal_target(ctx.df[ctx.target]):
        return [
            Finding(
                type=FindingType.LABEL_NOISE,
                severity=Severity.LOW,
                columns=[ctx.target],
                evidence={"applicable": False, "reason": "ordinal target; classes are not nominal"},
                confidence=1.0,
            )
        ]
    idx = subsample_indices(len(ctx.df), t["max_rows"], ctx.meta.seed)
    _, y = np.unique(ctx.y[idx].astype(int), return_inverse=True)
    n_classes = int(np.max(y)) + 1
    if n_classes < 2 or int(np.min(np.bincount(y))) < t["folds"]:
        return []
    feats = [c for c in ctx.features if c not in ctx.roles.id_like]
    if not feats:
        return []
    x = encode_features(ctx.df.iloc[idx].reset_index(drop=True), feats)
    probs = np.zeros((len(y), n_classes))
    cv = StratifiedKFold(t["folds"], shuffle=True, random_state=ctx.meta.seed)
    for tr, te in cv.split(x, y):
        ctx.budget.check()
        m = RandomForestClassifier(
            n_estimators=t["trees"],
            min_samples_leaf=t["min_samples_leaf"],
            random_state=ctx.meta.seed,
            n_jobs=4,
        ).fit(x[tr], y[tr])
        probs[np.ix_(te, m.classes_)] = m.predict_proba(x[te])
    joint, suspect = _confident_joint(probs, y, n_classes)
    rate = float(joint.sum() - np.trace(joint))
    flagged = np.flatnonzero(suspect >= 0)
    order = sorted(flagged, key=lambda i: (-(probs[i, suspect[i]] - probs[i, y[i]]), i))
    if rate < t["min_rate"]:
        return []
    return [
        Finding(
            type=FindingType.LABEL_NOISE,
            severity=_severity(rate, t["high_rate"]),
            columns=[ctx.target],
            evidence={
                "estimated_noise_rate": round(rate, 4),
                "n_suspects": int(flagged.size),
                "n_rows_used": int(len(y)),
                "suspect_indices": [int(idx[i]) for i in order[: t["max_suspects"]]],
                "indices_refer_to": "row positions in the frame passed to the detector",
            },
            confidence=_confidence(rate, t["min_rate"], t["high_rate"]),
        )
    ]


# --- near-deterministic target: linear combination / small separator -----------------------------
LC_ROWS = 4000
LC_MAX_TERMS = 5
LC_R2 = 0.999  # holdout R^2 at which a regression target counts as a linear function of <=5 columns
SEP_ACC = 0.998  # holdout balanced accuracy of a tree on <=3 columns (classification)
SEP_TOP = 10


def _numeric_features(ctx: Context) -> list[str]:
    return [
        c
        for c in ctx.features
        if pd.api.types.is_numeric_dtype(ctx.df[c])
        and not pd.api.types.is_bool_dtype(ctx.df[c])
        and ctx.df[c].nunique(dropna=True) > 1
    ]


def _lc_regression(ctx: Context) -> list[Finding]:
    from sklearn.linear_model import OrthogonalMatchingPursuit

    cols = _numeric_features(ctx)
    if not cols or float(np.nanstd(ctx.y)) == 0.0:
        return []
    idx = subsample_indices(len(ctx.df), LC_ROWS, ctx.meta.seed)
    x = encode_features(ctx.df.iloc[idx], cols)
    y = ctx.y[idx].astype(float)
    cut = len(y) // 2
    if cut < 30:
        return []
    mu, sd = x[:cut].mean(0), x[:cut].std(0) + 1e-12
    xs = (x - mu) / sd
    ss_tot = float(((y[cut:] - y[cut:].mean()) ** 2).sum())
    if ss_tot <= 0:
        return []
    for k in range(1, min(LC_MAX_TERMS, len(cols)) + 1):
        ctx.budget.check()
        omp = OrthogonalMatchingPursuit(n_nonzero_coefs=k).fit(xs[:cut], y[:cut])
        resid = y[cut:] - omp.predict(xs[cut:])
        r2 = 1.0 - float((resid**2).sum()) / ss_tot
        if r2 >= LC_R2:
            used = [cols[j] for j in np.flatnonzero(omp.coef_)]
            return [
                Finding(
                    type=FindingType.LINEAR_COMBINATION,
                    severity=_severity(r2, 0.9999),
                    columns=used,
                    evidence={"holdout_r2": round(r2, 6), "n_terms": len(used), "rows": len(y)},
                    confidence=_confidence(r2, LC_R2, 1.0),
                )
            ]
    return []


def _lc_separator(ctx: Context) -> list[Finding]:
    from itertools import combinations

    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import balanced_accuracy_score
    from sklearn.tree import DecisionTreeClassifier

    cols = ctx.features
    if len(cols) < 2 or int(np.max(ctx.y)) < 1:
        return []
    idx = subsample_indices(len(ctx.df), LC_ROWS, ctx.meta.seed)
    x = encode_features(ctx.df.iloc[idx], cols)
    y = ctx.y[idx].astype(int)
    cut = len(y) // 2
    n_hold = len(y) - cut
    if n_hold < 600 or len(np.unique(y[:cut])) < 2:
        return []  # too little holdout evidence for a 99.8% claim
    thr = min(SEP_ACC, 1.0 - 5.0 / n_hold)  # a plane learned from n rows errs ~ d/n: allow 5

    mu, sd = x[:cut].mean(0), x[:cut].std(0) + 1e-12
    xs = (x - mu) / sd

    def acc(js: tuple[int, ...]) -> float:
        """Best of an axis-aligned tree (rules, XOR) and a near-unregularised linear separator."""
        best = 0.0
        tree = DecisionTreeClassifier(max_depth=6, min_samples_leaf=5, random_state=0)
        tree.fit(x[:cut][:, js], y[:cut])
        best = float(balanced_accuracy_score(y[cut:], tree.predict(x[cut:][:, js])))
        if best < thr:
            lin = LogisticRegression(C=1e4, max_iter=2000)
            lin.fit(xs[:cut][:, js], y[:cut])
            best = max(best, float(balanced_accuracy_score(y[cut:], lin.predict(xs[cut:][:, js]))))
        return best

    singles = []
    for j in range(len(cols)):
        ctx.budget.check()
        singles.append((acc((j,)), j))
    singles.sort(reverse=True)
    if singles[0][0] >= thr:
        return []  # one column already separates: the target-leakage detector reports that
    top = [j for _, j in singles[:SEP_TOP]]
    for r in (2, 3):
        best: tuple[float, tuple[int, ...]] | None = None
        for combo in combinations(top, r):
            ctx.budget.check()
            a = acc(combo)
            if best is None or a > best[0]:
                best = (a, combo)
        if best and best[0] >= thr:
            return [
                Finding(
                    type=FindingType.LINEAR_COMBINATION,
                    severity=_severity(best[0], 0.9995),
                    columns=[cols[j] for j in best[1]],
                    evidence={
                        "holdout_balanced_accuracy": round(best[0], 6),
                        "n_columns": r,
                        "best_single_column": round(singles[0][0], 4),
                        "kind": "near-perfect separator from a few columns",
                        "rows": len(y),
                    },
                    confidence=_confidence(best[0], SEP_ACC, 1.0),
                )
            ]
    return []


def detect_linear_combo(ctx: Context) -> list[Finding]:
    """Target (almost) determined by <=5 numeric columns (regression, holdout R^2 >= 0.999) or by
    <=3 columns (classification, holdout balanced accuracy >= 0.998). Bounded: <=4000 rows."""
    return _lc_regression(ctx) if ctx.task == "regression" else _lc_separator(ctx)


DETECTORS: dict[str, Callable[[Context], list[Finding]]] = {
    "target_leakage": detect_target_leakage,
    "duplicates": detect_duplicates,
    "contamination": detect_contamination,
    "temporal": detect_temporal,
    "group": detect_group,
    "id": detect_id_leak,
    "unit_mismatch": detect_unit_mismatch,
    "suspicious_names": detect_suspicious_names,
    "label_noise": detect_label_noise,
    "linear_combo": detect_linear_combo,
}


def detect(
    df: pd.DataFrame,
    target: str,
    meta: DetectionMeta | None = None,
    thresholds: dict[str, Any] | None = None,
    only: list[str] | None = None,
) -> list[Finding]:
    """Run all (or `only`) detectors. Output order is deterministic."""
    return detect_with_status(df, target, meta, thresholds, only)[0]


def detect_with_status(
    df: pd.DataFrame,
    target: str,
    meta: DetectionMeta | None = None,
    thresholds: dict[str, Any] | None = None,
    only: list[str] | None = None,
) -> tuple[list[Finding], list[str]]:
    """Like `detect`, but never raises on time: each detector gets a slice of the remaining budget;
    one that runs out is skipped and listed. Returns (findings, partial-reasons); an empty reason
    list means every detector ran on the full (or only mildly sampled) frame."""
    ctx = make_context(df, target, meta, thresholds)
    names = [n for n in DETECTORS if only is None or n in only]
    end = time.monotonic() + ctx.meta.time_budget_s
    findings: list[Finding] = []
    for i, name in enumerate(names):
        remaining = end - time.monotonic()
        if remaining <= 0.0:
            ctx.partial.append(f"{name}: skipped (time budget)")
            continue
        ctx.budget = Budget(min(remaining, remaining / (len(names) - i) * 2))
        try:
            findings.extend(DETECTORS[name](ctx))
        except DetectionTimeout:
            ctx.partial.append(f"{name}: stopped at its time slice")
    return findings, ctx.partial
