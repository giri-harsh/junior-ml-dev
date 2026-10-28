"""Column role inference (id / time / group). Pure functions of the frame and column names."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TIME_NAME = re.compile(
    r"(^|[_\W])(time|date|datetime|timestamp|ts|dt|year|month|day|week)($|[_\W])|_at$|_on$",
    re.IGNORECASE,
)
ID_NAME = re.compile(
    r"(^|[_\W])(id|key|uuid|guid|account|customer|user|patient|subject|session|household)"
    r"($|[_\W])|id$",
    re.IGNORECASE,
)
ID_UNIQUE_RATIO = 0.95
MIN_GROUPS = 10
MAX_GROUP_RATIO = 0.5


@dataclass
class Roles:
    id_like: list[str] = field(default_factory=list)
    time_like: list[str] = field(default_factory=list)
    group_like: list[str] = field(default_factory=list)


def is_integer_valued(s: pd.Series) -> bool:
    if pd.api.types.is_integer_dtype(s):
        return True
    if not pd.api.types.is_float_dtype(s):
        return False
    v = s.dropna().to_numpy(dtype=float)
    return bool(v.size) and bool(np.all(np.isfinite(v))) and bool(np.all(v == np.round(v)))


def is_time_like(name: str, s: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(s):
        return True
    return bool(TIME_NAME.search(name)) and pd.api.types.is_numeric_dtype(s)


def infer_roles(df: pd.DataFrame, target: str) -> Roles:
    n = len(df)
    roles = Roles()
    if n == 0:
        return roles
    for col in df.columns:
        if col == target:
            continue
        s = df[col]
        if is_time_like(col, s):
            roles.time_like.append(col)
            continue
        discrete = (not pd.api.types.is_numeric_dtype(s)) or is_integer_valued(s)
        if not discrete:
            continue
        nunique = s.nunique(dropna=True)
        if nunique / n >= ID_UNIQUE_RATIO:
            roles.id_like.append(col)
        elif MIN_GROUPS <= nunique <= n * MAX_GROUP_RATIO:
            roles.group_like.append(col)
    # name hints first, then fewer distinct values (bigger groups) first
    roles.group_like.sort(key=lambda c: (not ID_NAME.search(c), df[c].nunique(), c))
    return roles
