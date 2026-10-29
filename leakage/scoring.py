"""Deterministic scoring helpers: feature encoding, CV splitters and score functions."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import r2_score, roc_auc_score
from sklearn.model_selection import GroupKFold, KFold, StratifiedKFold, TimeSeriesSplit
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor

Split = tuple[np.ndarray, np.ndarray]
SMOOTHING = 10.0


def infer_task(y: pd.Series) -> str:
    if not pd.api.types.is_numeric_dtype(y) or y.nunique(dropna=True) <= 20:
        return "binary" if y.nunique(dropna=True) == 2 else "multiclass"
    return "regression"


def encode_target(y: pd.Series, task: str) -> np.ndarray:
    """Float vector for regression, integer class codes (sorted label order) otherwise."""
    if task == "regression":
        return pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    codes, _ = pd.factorize(y.astype(str), sort=True)
    return codes.astype(int)


def encode_features(df: pd.DataFrame, cols: list[str]) -> np.ndarray:
    """Numeric matrix: numerics median-imputed, everything else ordinal-coded (NaN -> -1)."""
    out = np.empty((len(df), len(cols)), dtype=float)
    for j, c in enumerate(cols):
        s = df[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            out[:, j] = s.astype("int64").to_numpy(dtype=float)
        elif pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            v = s.to_numpy(dtype=float)
            med = np.nanmedian(v) if np.isfinite(v).any() else 0.0
            out[:, j] = np.where(np.isfinite(v), v, med)
        else:
            codes, _ = pd.factorize(s.astype(object).where(s.notna(), None).astype(str), sort=True)
            out[:, j] = codes
    return out


def random_splits(y: np.ndarray, task: str, seed: int, k: int = 5) -> list[Split]:
    if task != "regression":
        _, counts = np.unique(y, return_counts=True)
        if int(np.min(counts)) >= k:
            return list(StratifiedKFold(k, shuffle=True, random_state=seed).split(y, y))
    return list(KFold(k, shuffle=True, random_state=seed).split(y))


def time_splits(order_values: np.ndarray, k: int = 4) -> list[Split]:
    order = np.argsort(order_values, kind="stable")
    return [
        (order[tr], order[te])
        for tr, te in TimeSeriesSplit(n_splits=k).split(np.arange(len(order)))
    ]


def group_splits(groups: np.ndarray, k: int = 5) -> list[Split]:
    n_groups = len(np.unique(groups))
    return list(GroupKFold(n_splits=min(k, n_groups)).split(groups, groups=groups))


def _fold_score(task: str, y_te: np.ndarray, pred: np.ndarray, classes: np.ndarray) -> float | None:
    if task == "regression":
        return float(r2_score(y_te, pred))
    present = np.unique(y_te)
    if len(present) < 2:
        return None
    if task == "binary":
        if 1 not in classes:
            return None
        return float(roc_auc_score(y_te, pred[:, list(classes).index(1)]))
    if len(present) != len(classes) or not np.array_equal(present, classes):
        return None
    return float(roc_auc_score(y_te, pred, multi_class="ovr", labels=classes))


def cv_score(x: np.ndarray, y: np.ndarray, task: str, splits: list[Split], seed: int) -> float:
    """Mean per-fold AUC (classification) or R^2 (regression) of a small random forest."""
    scores: list[float] = []
    for tr, te in splits:
        if task == "regression":
            reg = RandomForestRegressor(n_estimators=40, random_state=seed, n_jobs=4)
            reg.fit(x[tr], y[tr])
            s = _fold_score(task, y[te], reg.predict(x[te]), np.array([]))
        else:
            clf = RandomForestClassifier(n_estimators=40, random_state=seed, n_jobs=4)
            clf.fit(x[tr], y[tr])
            s = _fold_score(task, y[te], clf.predict_proba(x[te]), clf.classes_)
        if s is not None:
            scores.append(s)
    return float(np.mean(scores)) if scores else float("nan")


def _oof_target_encoding(codes: np.ndarray, y: np.ndarray, splits: list[Split]) -> np.ndarray:
    oof = np.zeros(len(y), dtype=float)
    for tr, te in splits:
        prior = float(y[tr].mean())
        df = pd.DataFrame({"c": codes[tr], "y": y[tr]}).groupby("c")["y"].agg(["sum", "count"])
        enc = (df["sum"] + SMOOTHING * prior) / (df["count"] + SMOOTHING)
        oof[te] = pd.Series(codes[te]).map(enc).fillna(prior).to_numpy()
    return oof


def single_feature_gini(
    s: pd.Series, y: np.ndarray, task: str, seed: int, max_depth: int = 3
) -> float:
    """Out-of-fold 'gini' (2*AUC-1, or R^2) using one feature alone; clamped at 0."""
    splits = random_splits(y, task, seed, k=3)
    categorical = not pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s)
    if categorical and task != "multiclass":
        codes, _ = pd.factorize(s.astype(object).where(s.notna(), None).astype(str))
        yy = y.astype(float)
        pred = _oof_target_encoding(codes, yy, splits)
        if task == "regression":
            return max(0.0, float(r2_score(y, pred)))
        return max(0.0, 2 * float(roc_auc_score(y, pred)) - 1)
    x = encode_features(s.to_frame("f"), ["f"])
    if task == "regression":
        oof = np.zeros(len(y))
        for tr, te in splits:
            m = DecisionTreeRegressor(max_depth=max_depth, random_state=seed).fit(x[tr], y[tr])
            oof[te] = m.predict(x[te])
        return max(0.0, float(r2_score(y, oof)))
    n_classes = int(y.max()) + 1
    proba = np.zeros((len(y), n_classes))
    for tr, te in splits:
        m = DecisionTreeClassifier(max_depth=max_depth, random_state=seed).fit(x[tr], y[tr])
        proba[np.ix_(te, m.classes_)] = m.predict_proba(x[te])
    if task == "binary":
        return max(0.0, 2 * float(roc_auc_score(y, proba[:, 1])) - 1)
    return max(0.0, 2 * float(roc_auc_score(y, proba, multi_class="ovr")) - 1)


def direct_gini(s: pd.Series, y: np.ndarray, task: str) -> float:
    """Monotone association of a numeric column with the target, in [0, 1]."""
    if not pd.api.types.is_numeric_dtype(s):
        return 0.0
    v = s.to_numpy(dtype=float)
    ok = np.isfinite(v)
    if ok.sum() < 3 or np.nanstd(v[ok]) == 0:
        return 0.0
    if task == "regression":
        rho = pd.Series(v[ok]).corr(pd.Series(y[ok]), method="spearman")
        return 0.0 if np.isnan(rho) else float(abs(rho))
    if task == "binary":
        return abs(2 * float(roc_auc_score(y[ok], v[ok])) - 1)
    best = 0.0
    for c in np.unique(y[ok]):
        best = max(best, abs(2 * float(roc_auc_score((y[ok] == c).astype(int), v[ok])) - 1))
    return best


def iter_nonconstant(df: pd.DataFrame, cols: list[str]) -> Iterator[str]:
    for c in cols:
        if df[c].nunique(dropna=True) > 1:
            yield c
