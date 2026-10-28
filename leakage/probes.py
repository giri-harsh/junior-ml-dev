"""Seeded confirmation probes shared by the temporal, group and proxy detectors.

Probe cost (documented in ADR-007): a probe subsamples to `probe_rows` rows and fits 30-tree
random forests. Temporal/group: 3 repeats x (2 random-CV + 2 other-CV) = 3 x 18 fits per
candidate. Proxy LOCO: 2 repeats x 2 CVs x 3 folds = 12 fits per candidate.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from leakage.scoring import Split, cv_score, random_splits

SplitFn = Callable[[], list[Split]]


@dataclass
class Probe:
    x: np.ndarray
    y: np.ndarray
    cols: list[str]
    task: str
    seed: int

    def idx(self, names: list[str]) -> list[int]:
        return [self.cols.index(n) for n in names]

    def keep(self, drop: list[str]) -> list[int]:
        banned = set(self.idx([d for d in drop if d in self.cols]))
        return [i for i in range(len(self.cols)) if i not in banned]

    def score(self, cols: list[int], splits: list[Split], seed: int) -> float:
        return cv_score(self.x[:, cols], self.y, self.task, splits, seed)


def subsample_indices(n: int, cap: int, seed: int) -> np.ndarray:
    if n <= cap:
        return np.arange(n)
    return np.sort(np.random.default_rng(seed).choice(n, size=cap, replace=False))


def did_stats(
    probe: Probe, drop: list[str], other_splits: list[Split], repeats: int
) -> dict[str, object]:
    """Difference-in-differences of 'what does removing `drop` cost' between CV schemes.

    stat_r = [cv_random(all) - cv_random(without)] - [cv_other(all) - cv_other(without)].
    A shortcut that only works when rows can be matched to near neighbours (same time block,
    same group) helps in random CV but not in time/group-aware CV, so stat is large. An honest
    predictive column helps in both, so stat is near 0.
    """
    full = list(range(len(probe.cols)))
    without = probe.keep(drop)
    stats: list[float] = []
    gains_random: list[float] = []
    gains_other: list[float] = []
    for r in range(repeats):
        seed = probe.seed + r
        rs = random_splits(probe.y, probe.task, seed)
        gr = probe.score(full, rs, seed) - probe.score(without, rs, seed)
        go = probe.score(full, other_splits, seed) - probe.score(without, other_splits, seed)
        if np.isfinite(gr) and np.isfinite(go):
            stats.append(gr - go)
            gains_random.append(gr)
            gains_other.append(go)
    if not stats:
        return {"stats": [], "median": float("nan"), "gain_random": 0.0, "gain_other": 0.0}
    return {
        "stats": [round(s, 4) for s in stats],
        "median": float(np.median(stats)),
        "gain_random": round(float(np.median(gains_random)), 4),
        "gain_other": round(float(np.median(gains_other)), 4),
    }


def stable(stats: list[float], threshold: float) -> bool:
    """Median above threshold and at least two thirds of repeats above half of it."""
    if not stats:
        return False
    need = int(np.ceil(2 * len(stats) / 3))
    return bool(np.median(stats) >= threshold and sum(s >= threshold / 2 for s in stats) >= need)


def loco_drop(probe: Probe, col: str, repeats: int) -> float:
    """Median drop in random 3-fold CV score when `col` is removed."""
    full = list(range(len(probe.cols)))
    without = probe.keep([col])
    drops = []
    for r in range(repeats):
        seed = probe.seed + 100 + r
        sp = random_splits(probe.y, probe.task, seed, k=3)
        d = probe.score(full, sp, seed) - probe.score(without, sp, seed)
        if np.isfinite(d):
            drops.append(d)
    return float(np.median(drops)) if drops else float("nan")
