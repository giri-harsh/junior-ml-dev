"""Quality Scorecard: 0-100 score, six sub-scores, and deductions that name columns and a fix.

Deterministic. `as_of` makes timeliness reproducible (no wall clock). Leakage findings, when
given, feed the leakage_risk sub-score.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field

from leakage.models import Finding, Severity

CONFIG_PATH = Path(__file__).with_name("config.yaml")


class Deduction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: str
    points: float = Field(ge=0, le=100)  # sub-score points lost (0-100 scale of that dimension)
    columns: list[str]
    detail: str
    fix: str


class QualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float = Field(ge=0, le=100)
    subscores: dict[str, float]
    deductions: list[Deduction]
    n_rows: int
    n_cols: int


def load_config() -> dict[str, Any]:
    loaded = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", name.lower()) if t]


def _initials(value: str) -> str:
    return "".join(w[0] for w in re.split(r"\s+", value.strip()) if w).upper()


def _completeness(df: pd.DataFrame, cfg: dict[str, Any]) -> tuple[float, list[Deduction]]:
    if df.empty:
        return 100.0, []
    miss = df.isna().mean()
    full = cfg["completeness"]["full_penalty_at"]
    loss = float(np.mean(np.minimum(1.0, miss.to_numpy() / full))) * 100
    bad = miss[miss > 0].sort_values(ascending=False)
    deds = []
    if len(bad):
        top = list(bad.index[:10])
        deds.append(
            Deduction(
                dimension="completeness",
                points=round(loss, 2),
                columns=[str(c) for c in top],
                detail=f"{len(bad)} column(s) have missing values; worst {top[0]!r} "
                f"at {100 * float(bad.iloc[0]):.1f}%",
                fix="impute, drop the column, or document why values are absent",
            )
        )
    return 100.0 - loss, deds


def _uniqueness(df: pd.DataFrame) -> tuple[float, list[Deduction]]:
    if len(df) < 2:
        return 100.0, []
    dup = int(df.duplicated().sum())
    frac = dup / len(df)
    if not dup:
        return 100.0, []
    pts = min(100.0, frac * 200)  # 50% duplicates costs the whole dimension
    return 100.0 - pts, [
        Deduction(
            dimension="uniqueness",
            points=round(pts, 2),
            columns=[],
            detail=f"{dup} fully duplicated rows ({100 * frac:.1f}%)",
            fix="drop exact duplicates before splitting",
        )
    ]


def _validity(df: pd.DataFrame, cfg: dict[str, Any]) -> tuple[float, list[Deduction]]:
    v = cfg["validity"]
    non_neg = set(v["non_negative_name_tokens"])
    deds: list[Deduction] = []
    n_cols = max(df.shape[1], 1)
    bad_cols = 0.0
    for col in df.columns:
        s = df[col]
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            vals = s.to_numpy(dtype=float)
            inf = int(np.isinf(vals).sum())
            if inf:
                bad_cols += 1
                deds.append(
                    Deduction(
                        dimension="validity",
                        points=round(100 / n_cols, 2),
                        columns=[str(col)],
                        detail=f"{inf} infinite value(s)",
                        fix="replace with missing and impute",
                    )
                )
            if non_neg & set(_tokens(str(col))):
                neg = int((vals < 0).sum())
                if neg:
                    bad_cols += min(1.0, neg / len(df) * 10 + 0.1)
                    deds.append(
                        Deduction(
                            dimension="validity",
                            points=round(100 / n_cols * min(1.0, neg / len(df) * 10 + 0.1), 2),
                            columns=[str(col)],
                            detail=f"{neg} negative value(s) in a column whose name implies >= 0",
                            fix="check units or sign errors; set invalid values to missing",
                        )
                    )
        elif pd.api.types.is_string_dtype(s):
            nn = s.dropna().astype(str)
            if len(nn) >= 10:
                parsed = pd.to_numeric(nn.str.replace(",", "", regex=False), errors="coerce")
                frac = float(parsed.notna().mean())
                if v["numeric_as_string_min_parseable"] <= frac < 1.0:
                    bad_cols += 0.5
                    deds.append(
                        Deduction(
                            dimension="validity",
                            points=round(50 / n_cols, 2),
                            columns=[str(col)],
                            detail=f"numeric column stored as text; {100 * (1 - frac):.1f}% of "
                            "values do not parse",
                            fix="convert to numeric and inspect the unparsable cells",
                        )
                    )
    loss = min(100.0, bad_cols / n_cols * 100)
    return 100.0 - loss, deds


def _consistency(df: pd.DataFrame, cfg: dict[str, Any]) -> tuple[float, list[Deduction]]:
    deds: list[Deduction] = []
    cats = [c for c in df.columns if pd.api.types.is_string_dtype(df[c])][
        : cfg["consistency"]["max_variant_columns"]
    ]
    flagged = 0
    for col in cats:
        vals = df[col].dropna().astype(str)
        uniq = vals.unique()
        if len(uniq) < 2 or len(uniq) > 500:
            continue
        groups: dict[str, set[str]] = {}
        for u in uniq:
            groups.setdefault(re.sub(r"\s+", " ", u.strip().lower()), set()).add(u)
        variants = [sorted(g) for g in groups.values() if len(g) > 1]
        multi = [u for u in uniq if " " in u.strip()]
        abbrev = {_initials(m): m for m in multi if len(_initials(m)) >= 2}
        for u in uniq:
            if u.isupper() and u in abbrev:
                variants.append(sorted({u, abbrev[u]}))
        if variants:
            flagged += 1
            deds.append(
                Deduction(
                    dimension="consistency",
                    points=0.0,  # filled below once the flagged count is known
                    columns=[str(col)],
                    detail=f"spelling/case variants of one value: {variants[0]}",
                    fix="normalise case/whitespace and map abbreviations to one label",
                )
            )
    n = max(len(cats), 1)
    per = 100.0 / n
    deds = [d.model_copy(update={"points": round(min(100.0, per), 2)}) for d in deds]
    loss = min(100.0, flagged / n * 100)
    return 100.0 - loss, deds


def _timeliness(
    df: pd.DataFrame, cfg: dict[str, Any], as_of: date | None
) -> tuple[float, list[Deduction]]:
    if as_of is None:
        return 100.0, []
    deds: list[Deduction] = []
    loss = 0.0
    ref = pd.Timestamp(as_of)
    for col in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df[col]):
            continue
        s = df[col].dropna()
        if s.empty:
            continue
        future = float((s > ref).mean())
        stale = (ref - s.max()).days > cfg["timeliness"]["stale_after_days"]
        if future > 0 or stale:
            pts = 100.0 if stale else min(100.0, future * 200)
            loss = max(loss, pts)
            deds.append(
                Deduction(
                    dimension="timeliness",
                    points=round(pts, 2),
                    columns=[str(col)],
                    detail="all data older than the staleness window"
                    if stale
                    else f"{100 * future:.1f}% of dates are after {as_of}",
                    fix="refresh the extract or fix date parsing",
                )
            )
    return 100.0 - loss, deds


def _leakage(findings: list[Finding] | None, cfg: dict[str, Any]) -> tuple[float, list[Deduction]]:
    if not findings:
        return 100.0, []
    lr = cfg["leakage_risk"]
    deds, loss = [], 0.0
    for f in findings:
        if f.severity == Severity.LOW:
            continue
        pts = lr["high_points"] if f.severity == Severity.HIGH else lr["medium_points"]
        loss += pts
        deds.append(
            Deduction(
                dimension="leakage_risk",
                points=float(pts),
                columns=f.columns,
                detail=f"{f.severity.value} {f.type.value}",
                fix="review the finding in the leakage report before modelling",
            )
        )
    return max(0.0, 100.0 - loss), deds


def quality_report(
    df: pd.DataFrame, findings: list[Finding] | None = None, as_of: date | None = None
) -> QualityReport:
    cfg = load_config()
    parts = {
        "completeness": _completeness(df, cfg),
        "uniqueness": _uniqueness(df),
        "validity": _validity(df, cfg),
        "consistency": _consistency(df, cfg),
        "timeliness": _timeliness(df, cfg, as_of),
        "leakage_risk": _leakage(findings, cfg),
    }
    w = cfg["weights"]
    assert abs(sum(w.values()) - 1.0) < 1e-9
    sub = {k: round(max(0.0, min(100.0, v[0])), 2) for k, v in parts.items()}
    score = round(sum(w[k] * sub[k] for k in w), 2)
    deds = [d for _, ds in parts.values() for d in ds]
    return QualityReport(
        score=score, subscores=sub, deductions=deds, n_rows=len(df), n_cols=int(df.shape[1])
    )
