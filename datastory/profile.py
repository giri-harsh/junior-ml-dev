"""Deterministic dataset profile. No randomness; sampling happens before this module."""

from __future__ import annotations

import numpy as np
import pandas as pd

from datastory.models import ColumnProfile, DatasetProfile, SampleInfo, TargetProfile
from datastory.roles import infer_roles
from leakage.scoring import direct_gini, encode_target, infer_task

NEAR_CONSTANT = 0.99
HIGH_MISSING = 0.30
HIGH_CARD_RATIO = 0.5
TEXT_MIN_LEN = 30


def _semantic_type(s: pd.Series, n: int) -> str:
    nunique = s.nunique(dropna=True)
    if nunique <= 1:
        return "constant"
    if pd.api.types.is_bool_dtype(s) or (nunique == 2 and not pd.api.types.is_float_dtype(s)):
        return "boolean" if pd.api.types.is_bool_dtype(s) else "categorical"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    if pd.api.types.is_numeric_dtype(s):
        return "numeric"
    avg_len = s.dropna().astype(str).str.len().mean() if s.notna().any() else 0
    if avg_len >= TEXT_MIN_LEN and nunique / max(n, 1) > 0.5:
        return "text"
    return "categorical"


def _eta(cat: pd.Series, y: np.ndarray) -> float:
    """Correlation ratio of a categorical column against a numeric target."""
    df = pd.DataFrame({"c": cat.astype(str).to_numpy(), "y": y})
    total = float(((df["y"] - df["y"].mean()) ** 2).sum())
    if total == 0:
        return 0.0
    g = df.groupby("c")["y"].agg(["mean", "count"])
    between = float((g["count"] * (g["mean"] - df["y"].mean()) ** 2).sum())
    return float(np.sqrt(between / total))


def _cramers_v(cat: pd.Series, y: np.ndarray) -> float:
    table = pd.crosstab(cat.astype(str).to_numpy(), y).to_numpy().astype(float)
    n = table.sum()
    if n == 0 or min(table.shape) < 2:
        return 0.0
    expected = table.sum(1, keepdims=True) * table.sum(0, keepdims=True) / n
    chi2 = float(((table - expected) ** 2 / np.where(expected == 0, 1, expected)).sum())
    return float(np.sqrt(chi2 / (n * (min(table.shape) - 1))))


def _association(s: pd.Series, y: np.ndarray, task: str) -> tuple[float | None, str | None]:
    if s.nunique(dropna=True) < 2:
        return None, None
    if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
        return round(direct_gini(s, y, task), 4), "abs_spearman" if task == "regression" else "gini"
    if task == "regression":
        return round(_eta(s, y), 4), "eta"
    return round(_cramers_v(s, y), 4), "cramers_v"


def _target_profile(df: pd.DataFrame, target: str, task: str) -> TargetProfile:
    y = df[target]
    prof = TargetProfile(name=target, task_type=task, missing_frac=round(float(y.isna().mean()), 4))
    if task == "regression":
        prof.skew = round(float(pd.to_numeric(y, errors="coerce").skew()), 4)  # type: ignore[arg-type]
    else:
        bal = y.astype(str).value_counts(normalize=True).sort_index()
        prof.n_classes = int(len(bal))
        prof.class_balance = {str(k): round(float(v), 4) for k, v in bal.items()}
        prof.majority_fraction = round(float(bal.max()), 4)
        prof.imbalance_ratio = round(float(bal.max() / bal.min()), 2)
    return prof


def profile_frame(
    df: pd.DataFrame,
    target: str | None = None,
    sample: SampleInfo | None = None,
    task: str | None = None,
) -> DatasetProfile:
    n = len(df)
    roles = infer_roles(df, target or "\0")
    y_enc = None
    task_type = None
    tprof = None
    if target is not None:
        if target not in df.columns:
            raise KeyError(f"target {target!r} not in columns")
        task_type = task or infer_task(df[target].dropna())
        tprof = _target_profile(df, target, task_type)
        keep = df[target].notna().to_numpy()
        y_enc = encode_target(df[target], task_type)
    cols: list[ColumnProfile] = []
    for c in df.columns:
        s = df[c]
        top = s.astype(str).value_counts(normalize=True, dropna=True)
        sem = _semantic_type(s, n)
        if c in roles.id_like:
            sem = "id"
        role_list = [
            r
            for r, members in (
                ("id", roles.id_like),
                ("time", roles.time_like),
                ("group", roles.group_like),
            )
            if c in members
        ]
        stats: dict[str, float] = {}
        if sem == "numeric":
            v = pd.to_numeric(s, errors="coerce")
            stats = {
                "mean": float(v.mean()),
                "std": float(v.std()),
                "min": float(v.min()),
                "max": float(v.max()),
                "skew": float(v.skew()),  # type: ignore[arg-type]
            }
            stats = {k: round(x, 6) for k, x in stats.items() if np.isfinite(x)}
        assoc, method = (None, None)
        if y_enc is not None and c != target and task_type is not None:
            assoc, method = _association(s[keep].reset_index(drop=True), y_enc[keep], task_type)
        cols.append(
            ColumnProfile(
                name=str(c),
                dtype=str(s.dtype),
                semantic_type=sem,
                missing_frac=round(float(s.isna().mean()), 4),
                n_unique=int(s.nunique(dropna=True)),
                near_constant=bool(len(top) and float(top.iloc[0]) >= NEAR_CONSTANT),
                stats=stats,
                top_values={}
                if sem in {"numeric", "id", "text"}
                else {str(k): round(float(v), 4) for k, v in top.head(5).items()},
                target_association=assoc,
                association_method=method,
                roles=role_list,
            )
        )
    return DatasetProfile(
        n_rows=n,
        n_cols=int(df.shape[1]),
        duplicate_rows=int(df.duplicated().sum()),
        target=tprof,
        columns=cols,
        constant_columns=[c.name for c in cols if c.semantic_type == "constant"],
        near_constant_columns=[
            c.name for c in cols if c.near_constant and c.semantic_type != "constant"
        ],
        high_missing_columns=[c.name for c in cols if c.missing_frac >= HIGH_MISSING],
        high_cardinality_columns=[
            c.name
            for c in cols
            if c.semantic_type == "categorical" and c.n_unique / max(n, 1) >= HIGH_CARD_RATIO
        ],
        suspected_id=roles.id_like,
        suspected_time=roles.time_like,
        suspected_group=roles.group_like,
        sample=sample,
    )
