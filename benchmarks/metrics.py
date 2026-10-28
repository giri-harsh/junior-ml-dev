"""Benchmark-level scoring: normalized score, pass rule, bootstrap CI. All deterministic."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from apps.scorer.metrics import HIGHER_IS_BETTER

PASS_MARGIN = 0.02
CEILING_SCORE = 0.98  # higher-is-better metrics: linear at/above this -> "not worse than linear"
CEILING_ERR_FRAC = 0.02  # error metrics: linear error <= 2% of target scale
MIN_DENOM_FRAC = 1e-3  # |flaml - dummy| below this fraction of max(|dummy|, 1) => undefined


def normalized_score(agent: float, dummy: float, flaml: float, metric: str) -> float | None:
    """(agent - dummy) / (flaml - dummy) in the metric's better-is-higher direction.

    None when the denominator is too small (or FLAML is not better than dummy); callers must
    exclude those tasks and count them.
    """
    sign = 1.0 if HIGHER_IS_BETTER[metric] else -1.0
    denom = sign * (flaml - dummy)
    if abs(denom) < MIN_DENOM_FRAC * max(abs(dummy), 1.0) or denom <= 0:
        return None
    return float(sign * (agent - dummy) / denom)


def passes(agent: float, linear: float, metric: str, scale: float | None = None) -> bool:
    """Pass = agent >= linear x 1.02 (relative), with the ceiling clause from ADR-005.

    `scale` is the target's spread (std) and is required for error metrics.
    """
    if HIGHER_IS_BETTER[metric]:
        if linear >= CEILING_SCORE:
            return agent >= linear
        return agent >= linear * (1 + PASS_MARGIN)
    if scale is None:
        raise ValueError("scale (target std) required for error metrics")
    if linear <= CEILING_ERR_FRAC * scale:
        return agent <= linear
    return agent <= linear * (1 - PASS_MARGIN)


def bootstrap_ci(
    values: Sequence[float],
    n_resamples: int = 10_000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float, float]:
    """Percentile bootstrap of the mean over tasks: (mean, lo, hi). Resampling unit = task."""
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        raise ValueError("no values")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, arr.size, size=(n_resamples, arr.size))
    means = arr[idx].mean(axis=1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return float(arr.mean()), float(lo), float(hi)


def paired_bootstrap_ci(
    a: Sequence[float], b: Sequence[float], n_resamples: int = 10_000, seed: int = 0
) -> tuple[float, float, float]:
    """CI of mean(a - b) with tasks resampled jointly (for ablations, S26)."""
    if len(a) != len(b):
        raise ValueError("paired samples must have equal length")
    return bootstrap_ci(np.asarray(a) - np.asarray(b), n_resamples, seed=seed)
