from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from harness.review.checks import (
    check_cv_stability,
    check_leakage_resolved,
    check_metric_matches_task,
    check_pipeline_ast,
    check_seeds,
    check_split_integrity,
    check_train_val_gap,
    review,
)
from leakage.models import Finding, FindingType, Severity

GOOD = """
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
scaler = StandardScaler()
pipe = Pipeline([("sc", scaler), ("m", LogisticRegression(random_state=0))])
cv = StratifiedKFold(5, shuffle=True, random_state=0)
"""

LEAKY = {
    "scaler on full X": "from sklearn.preprocessing import StandardScaler\n"
    "sc = StandardScaler()\nX = sc.fit_transform(X)\n",
    "inline fit_transform": "from sklearn.preprocessing import StandardScaler\nX = StandardScaler().fit_transform(X)\n",
    "target encode before split": "from sklearn.preprocessing import TargetEncoder\n"
    "te = TargetEncoder()\nX = te.fit_transform(X, y)\n",
    "imputer fit outside": "from sklearn.impute import SimpleImputer\nimp = SimpleImputer()\nimp.fit(X)\n",
}


def test_good_pipeline_passes() -> None:
    assert check_pipeline_ast(GOOD).passed and check_seeds(GOOD).passed


@pytest.mark.parametrize("name", list(LEAKY))
def test_each_leaky_pattern_is_caught(name: str) -> None:
    assert not check_pipeline_ast(LEAKY[name]).passed


def test_mutation_injecting_leakage_flips_the_check() -> None:
    assert check_pipeline_ast(GOOD).passed
    mutated = GOOD + "\nscaler2 = StandardScaler()\nXs = scaler2.fit_transform(X)\n"
    assert not check_pipeline_ast(mutated).passed


def test_missing_seeds_are_reported_with_lines() -> None:
    code = "from sklearn.ensemble import RandomForestClassifier\nm = RandomForestClassifier()\n"
    r = check_seeds(code)
    assert not r.passed and "RandomForestClassifier" in r.detail
    assert check_seeds(code + "import numpy as np\nnp.random.seed(0)\n").passed


def test_syntax_error_fails_closed() -> None:
    assert not check_pipeline_ast("def f(:").passed and not check_seeds("def f(:").passed


def test_overlapping_folds_are_caught_and_clean_folds_pass() -> None:
    n = 10
    clean = [(np.arange(0, 8), np.arange(8, 10)), (np.arange(2, 10), np.arange(0, 2))]
    assert check_split_integrity(clean, n).passed
    leaky = [(np.arange(0, 8), np.arange(6, 10))]
    assert not check_split_integrity(leaky, n).passed
    reused = [(np.arange(0, 6), np.arange(6, 8)), (np.arange(0, 6), np.arange(6, 8))]
    assert not check_split_integrity(reused, n).passed


def test_duplicate_rows_across_folds_are_caught() -> None:
    hashes = pd.Series([1, 2, 3, 1, 4])
    folds = [(np.array([0, 1, 2]), np.array([3, 4]))]
    r = check_split_integrity(folds, 5, row_hash=hashes)
    assert not r.passed and "identical rows" in r.detail


def test_group_and_time_violations() -> None:
    folds = [(np.array([0, 1, 2]), np.array([3, 4]))]
    assert not check_split_integrity(folds, 5, groups=np.array([1, 2, 3, 1, 5])).passed
    assert not check_split_integrity(folds, 5, time=np.array([5, 6, 7, 1, 2])).passed
    assert check_split_integrity(folds, 5, time=np.array([1, 2, 3, 4, 5])).passed


def test_gap_stability_metric_and_leakage_checks() -> None:
    assert check_train_val_gap(0.9, 0.85).passed and not check_train_val_gap(1.0, 0.7).passed
    assert (
        check_cv_stability([0.8, 0.81, 0.79]).passed
        and not check_cv_stability([0.9, 0.4, 0.7]).passed
    )
    assert check_metric_matches_task("rmse", "regression").passed
    assert not check_metric_matches_task("roc_auc", "regression").passed
    f = Finding(
        type=FindingType.TARGET_LEAKAGE,
        severity=Severity.HIGH,
        columns=["leak"],
        evidence={},
        confidence=0.9,
    )
    assert not check_leakage_resolved([f], set()).passed
    assert check_leakage_resolved([f], {"leak"}).passed


def test_review_verdict_requires_every_check() -> None:
    ok = review(
        GOOD, agent=0.85, linear=0.80, dummy=0.5, metric="roc_auc", train_score=0.9, val_score=0.85,
        fold_scores=[0.84, 0.85, 0.86], metric_task_ok=True, task_type="binary",
    )  # fmt: skip
    assert ok.verdict == "APPROVE"
    weak = review(GOOD, agent=0.80, linear=0.80, dummy=0.5, metric="roc_auc")
    assert weak.verdict == "REQUEST_CHANGES" and not weak.checks["baseline_margin"].passed
    leaky = review(LEAKY["scaler on full X"], agent=0.9, linear=0.8, dummy=0.5, metric="roc_auc")
    assert leaky.verdict == "REQUEST_CHANGES" and not leaky.checks["pipeline_ast"].passed
