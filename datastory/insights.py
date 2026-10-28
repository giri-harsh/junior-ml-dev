# mypy: disable-error-code="arg-type,assignment,operator,dict-item,index,call-overload,misc"
"""Typed insights; `facts` holds the only numbers a caption may use (see verify.py)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from datastory.roles import infer_roles
from leakage.evaluate import wilson
from leakage.scoring import encode_target, infer_task

SAMPLE_CAP = 20_000
MIN_SUPPORT = 30
TYPE_WEIGHT = {
    "target_balance": 0.9,
    "target_association": 1.0,
    "segment": 0.95,
    "correlation": 0.7,
    "skew": 0.5,
    "missing_pattern": 0.6,
    "outlier": 0.4,
    "id_column": 0.5,
}


class Insight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    columns: list[str]
    importance: float = Field(ge=0, le=1)
    facts: dict[str, float]
    sample: dict[str, int]


def _ins(
    kind: str, columns: list[str], strength: float, facts: dict[str, float], sample: dict[str, int]
) -> Insight:
    return Insight(
        id=f"{kind}:{','.join(columns)}",
        type=kind,
        columns=columns,
        importance=round(float(np.clip(strength, 0, 1)) * TYPE_WEIGHT[kind], 4),
        facts={k: round(float(v), 4) for k, v in facts.items()},
        sample=sample,
    )


def mine_insights(df: pd.DataFrame, target: str | None = None, seed: int = 0) -> list[Insight]:
    n_full = len(df)
    if n_full > SAMPLE_CAP:
        df = df.sample(n=SAMPLE_CAP, random_state=seed).reset_index(drop=True)
    meta = {"n_full": n_full, "n_sample": len(df)}
    out: list[Insight] = []
    roles = infer_roles(df, target or "\0")
    nums = [
        c
        for c in df.columns
        if c != target
        and c not in roles.id_like
        and pd.api.types.is_numeric_dtype(df[c])
        and not pd.api.types.is_bool_dtype(df[c])
        and df[c].nunique() > 2
    ]
    task = infer_task(df[target].dropna()) if target else None

    if target and task and task != "regression":
        bal = df[target].astype(str).value_counts(normalize=True)
        if len(bal) >= 2:
            ratio = float(bal.iloc[0] / bal.iloc[-1])
            out.append(
                _ins(
                    "target_balance",
                    [target],
                    min(1.0, np.log10(ratio) / 2),
                    {
                        "majority_pct": 100 * bal.iloc[0],
                        "minority_pct": 100 * bal.iloc[-1],
                        "imbalance_ratio": ratio,
                        "n_classes": len(bal),
                    },
                    meta,
                )
            )
    for c in nums:
        s = df[c].dropna()
        if len(s) < 20:
            continue
        sk = float(s.skew())
        if abs(sk) >= 1:
            out.append(
                _ins(
                    "skew",
                    [c],
                    min(1.0, abs(sk) / 5),
                    {"skew": sk, "mean": s.mean(), "median": s.median()},
                    meta,
                )
            )
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        if iqr > 0:
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            frac = float(((s < lo) | (s > hi)).mean())
            if frac >= 0.02:
                out.append(
                    _ins(
                        "outlier",
                        [c],
                        min(1.0, frac * 5),
                        {"outlier_pct": 100 * frac, "lower_fence": lo, "upper_fence": hi},
                        meta,
                    )
                )
    for c in df.columns:
        m = float(df[c].isna().mean())
        if m >= 0.05:
            out.append(_ins("missing_pattern", [str(c)], m * 2, {"missing_pct": 100 * m}, meta))
    for c in roles.id_like:
        out.append(
            _ins("id_column", [c], 0.8, {"unique_pct": 100 * df[c].nunique() / len(df)}, meta)
        )
    if len(nums) >= 2:
        corr = df[nums].corr(method="spearman").abs()
        pairs = []
        for i, a in enumerate(nums):
            for b in nums[i + 1 :]:
                v = corr.loc[a, b]
                if np.isfinite(v) and v >= 0.6:
                    pairs.append((float(v), a, b))
        for v, a, b in sorted(pairs, reverse=True)[:3]:
            signed = float(df[a].corr(df[b], method="spearman"))
            out.append(_ins("correlation", [a, b], v, {"spearman_rho": signed, "n": len(df)}, meta))
    if target and task:
        y = encode_target(df[target], task)
        keep = ~pd.isna(df[target]).to_numpy()
        scored = []
        for c in nums:
            x = pd.to_numeric(df[c], errors="coerce").to_numpy()[keep]
            ok = np.isfinite(x)
            if ok.sum() > 20 and np.nanstd(x[ok]) > 0:
                rho = pd.Series(x[ok]).corr(pd.Series(y[keep][ok].astype(float)), method="spearman")
                if np.isfinite(rho):
                    scored.append((abs(float(rho)), float(rho), c))
        for a, rho, c in sorted(scored, reverse=True)[:3]:
            if a >= 0.1:
                out.append(
                    _ins(
                        "target_association",
                        [c, target],
                        a,
                        {"spearman_rho": rho, "n": int(ok.sum())},
                        meta,
                    )
                )
        if task == "binary":
            pos = (df[target].astype(str) == sorted(df[target].astype(str).unique())[-1]).astype(
                int
            )
            overall = float(pos.mean())
            best: tuple[float, str, str, dict[str, float]] | None = None
            for c in df.columns:
                if c == target or c in roles.id_like or pd.api.types.is_numeric_dtype(df[c]):
                    continue
                if df[c].nunique() > 50:
                    continue
                g = pos.groupby(df[c].astype(str)).agg(["sum", "count"])
                for cat, row in g.iterrows():
                    cnt, k = int(row["count"]), int(row["sum"])
                    if cnt < MIN_SUPPORT or overall == 0:
                        continue
                    rate = k / cnt
                    lo, hi = wilson(k, cnt)
                    lift = rate / overall
                    if (lo > overall or hi < overall) and abs(np.log(lift)) > 0.2:
                        score = abs(np.log(lift))
                        if best is None or score > best[0]:
                            best = (
                                score,
                                c,
                                str(cat),
                                {
                                    "rate_pct": 100 * rate,
                                    "overall_pct": 100 * overall,
                                    "lift": lift,
                                    "n": cnt,
                                    "ci_level_pct": 95,
                                    "ci_low_pct": 100 * lo,
                                    "ci_high_pct": 100 * hi,
                                },
                            )
            if best:
                out.append(_ins("segment", [best[1]], min(1.0, best[0]), best[3], meta))
    return sorted(out, key=lambda i: (-i.importance, i.id))


def facts_of(insight: Insight) -> dict[str, Any]:
    return dict(insight.facts)
