"""PII shape scan. Flags only: values are never stored or returned."""

from __future__ import annotations

import re

import pandas as pd

PATTERNS = {
    "email": re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$"),
    "phone": re.compile(r"^\+?\d[\d\s().-]{8,14}\d$"),
    "ssn_like": re.compile(r"^\d{3}-\d{2}-\d{4}$"),
    "card_like": re.compile(r"^(?:\d[ -]?){13,19}$"),
}
MIN_MATCH_FRACTION = 0.3
SAMPLE = 500


def scan_pii(df: pd.DataFrame) -> dict[str, list[str]]:
    """Return {pii_kind: [column names]} for object columns whose values match a pattern."""
    out: dict[str, list[str]] = {}
    for col in df.columns:
        if not pd.api.types.is_string_dtype(df[col]):
            continue
        vals = df[col].dropna().astype(str).head(SAMPLE)
        if vals.empty:
            continue
        for kind, pat in PATTERNS.items():
            if (
                float(vals.map(lambda v, p=pat: bool(p.match(v.strip()))).mean())
                >= MIN_MATCH_FRACTION
            ):
                out.setdefault(kind, []).append(str(col))
    return out
