"""Leakage v3: near-deterministic targets (linear combination / small separator) and the
adaptive budget. All data synthetic; Brazilian_houses/ailerons (burned v4) are NOT used here."""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from leakage.detectors import detect, detect_with_status
from leakage.models import DetectionMeta, FindingType, Severity


def _frame(n: int = 2000, k: int = 8, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(rng.normal(size=(n, k)), columns=[f"f{i}" for i in range(k)])


def _combo(findings: list) -> list:  # type: ignore[type-arg]
    return [f for f in findings if f.type is FindingType.LINEAR_COMBINATION]


def test_regression_target_that_is_a_linear_sum_is_flagged_with_its_columns() -> None:
    df = _frame()
    df["total"] = (
        2.0 * df.f1 - 1.5 * df.f4 + 0.8 * df.f6 + np.random.default_rng(1).normal(0, 0.01, len(df))
    )
    (f,) = _combo(detect(df, "total", only=["linear_combo"]))
    assert set(f.columns) == {"f1", "f4", "f6"} and f.severity is not Severity.LOW
    assert f.evidence["holdout_r2"] >= 0.999


def test_noisy_or_nonlinear_regression_targets_are_not_flagged() -> None:
    df = _frame()
    rng = np.random.default_rng(2)
    noisy = df.copy()
    noisy["t"] = noisy.f1 + noisy.f2 + rng.normal(0, 0.5, len(df))  # R^2 ~ 0.8
    assert not _combo(detect(noisy, "t", only=["linear_combo"]))
    nl = df.copy()
    nl["t"] = nl.f1 * nl.f2 + rng.normal(0, 0.3, len(df))
    assert not _combo(detect(nl, "t", only=["linear_combo"]))


def test_a_separator_from_two_or_three_columns_is_flagged_but_one_column_is_left_to_target_leakage() -> (
    None
):
    df = _frame(3000)
    df["y"] = ((df.f0 + 2 * df.f3 - df.f5) > 0).astype(int)
    (f,) = _combo(detect(df, "y", only=["linear_combo"]))
    assert set(f.columns) == {"f0", "f3", "f5"} and f.evidence["holdout_balanced_accuracy"] >= 0.996
    single = _frame(3000)
    single["y"] = (single.f2 > 0).astype(int)
    assert not _combo(detect(single, "y", only=["linear_combo"]))  # reported by target_leakage


def test_xor_rule_on_two_columns_is_found_by_the_tree_branch() -> None:
    df = _frame(3000)
    df["y"] = ((df.f1 > 0) ^ (df.f2 > 0)).astype(int)
    (f,) = _combo(detect(df, "y", only=["linear_combo"]))
    assert set(f.columns) == {"f1", "f2"}


def test_weakly_predictable_classification_is_not_flagged() -> None:
    df = _frame(3000)
    rng = np.random.default_rng(3)
    df["y"] = ((df.f0 + df.f1 + rng.normal(0, 1.5, len(df))) > 0).astype(int)
    assert not _combo(detect(df, "y", only=["linear_combo"]))


def test_small_samples_do_not_make_evidence_claims() -> None:
    df = _frame(300)
    df["y"] = ((df.f0 + df.f1) > 0).astype(int)
    assert not _combo(detect(df, "y", only=["linear_combo"]))  # holdout < 600 rows


def test_wide_and_long_frames_are_bounded_and_say_so() -> None:
    rng = np.random.default_rng(4)
    n, k = 30_000, 300
    df = pd.DataFrame(rng.normal(size=(n, k)), columns=[f"c{i}" for i in range(k)])
    df["y"] = (df.c7 + 0.5 * rng.normal(size=n) > 0).astype(int)
    t0 = time.monotonic()
    findings, partial = detect_with_status(df, "y", DetectionMeta(time_budget_s=60))
    assert time.monotonic() - t0 < 60
    assert any("columns reduced" in p for p in partial)  # 120 most target-associated kept
    assert any(set(f.columns) & {"c7"} for f in findings)  # the informative column survived


def test_exhausted_budget_returns_partial_not_an_exception() -> None:
    df = _frame(1500)
    df["y"] = (df.f0 > 0).astype(int)
    findings, partial = detect_with_status(df, "y", DetectionMeta(time_budget_s=1e-9))
    assert (
        isinstance(findings, list)
        and partial
        and all("skipped" in p or "stopped" in p for p in partial)
    )
