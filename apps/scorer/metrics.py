"""Deterministic metrics. `HIGHER_IS_BETTER` drives normalisation direction."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import numpy.typing as npt
from sklearn.metrics import average_precision_score, f1_score, roc_auc_score

Arr = npt.ArrayLike


def roc_auc(y_true: Arr, y_pred: Arr) -> float:
    return float(roc_auc_score(y_true, y_pred))


def pr_auc(y_true: Arr, y_pred: Arr) -> float:
    return float(average_precision_score(y_true, y_pred))


def f1_macro(y_true: Arr, y_pred: Arr) -> float:
    return float(f1_score(y_true, y_pred, average="macro"))


def rmse(y_true: Arr, y_pred: Arr) -> float:
    d = np.asarray(y_true, dtype=float) - np.asarray(y_pred, dtype=float)
    return float(np.sqrt(np.mean(d**2)))


def mae(y_true: Arr, y_pred: Arr) -> float:
    d = np.asarray(y_true, dtype=float) - np.asarray(y_pred, dtype=float)
    return float(np.mean(np.abs(d)))


METRICS: dict[str, Callable[[Arr, Arr], float]] = {
    "roc_auc": roc_auc,
    "pr_auc": pr_auc,
    "f1_macro": f1_macro,
    "rmse": rmse,
    "mae": mae,
}
HIGHER_IS_BETTER: dict[str, bool] = {
    "roc_auc": True,
    "pr_auc": True,
    "f1_macro": True,
    "rmse": False,
    "mae": False,
}


def compute(metric: str, y_true: Arr, y_pred: Arr) -> float:
    return METRICS[metric](y_true, y_pred)
