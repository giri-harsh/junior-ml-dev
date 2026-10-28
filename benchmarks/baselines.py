"""Dummy / linear / FLAML baselines, scored through the scorer service code path."""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from apps.scorer.service import create_app, run_token
from apps.scorer.splits import ROW_ID
from benchmarks.tasks.registry import TaskSpec

SEED = 0
DATA_ROOT = Path("data/tasks")
SCORER_ROOT = Path("scorer_data")
_SECRET = "baseline-local-secret"  # in-process only; the scorer app is built in this process

FLAML_METRIC = {
    "roc_auc": "roc_auc",
    "pr_auc": "ap",
    "f1_macro": "macro_f1",
    "rmse": "rmse",
    "mae": "mae",
}


def load_task(spec: TaskSpec) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """Agent-visible train (X, y) and test features (from the scorer store, features only)."""
    train = pd.read_parquet(DATA_ROOT / spec.name / "train.parquet")
    test = pd.read_parquet(SCORER_ROOT / spec.name / "test_features.parquet")
    y = train[spec.target]
    x = train.drop(columns=[spec.target, ROW_ID])
    return x, y, test


def _cat_cols(x: pd.DataFrame) -> list[str]:
    return [c for c in x.columns if not pd.api.types.is_numeric_dtype(x[c])]


def _positive_label(y: pd.Series) -> str:
    return str(sorted(y.astype(str).unique())[-1])  # same convention as the scorer


def _predict_frame(
    spec: TaskSpec, model: Any, y_train: pd.Series, x_test: pd.DataFrame, ids: pd.Series
) -> pd.DataFrame:
    if spec.task_type == "regression":
        pred = model.predict(x_test)
    elif spec.metric in {"roc_auc", "pr_auc"}:
        classes = [str(c) for c in model.classes_]
        pred = model.predict_proba(x_test)[:, classes.index(_positive_label(y_train))]
    else:
        pred = model.predict(x_test)
    return pd.DataFrame({ROW_ID: ids.to_numpy(), "pred": np.asarray(pred)})


def _make_linear(spec: TaskSpec, x: pd.DataFrame) -> Pipeline:
    cats = _cat_cols(x)
    nums = [c for c in x.columns if c not in cats]
    num_pipe = Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())])
    cat_pipe = Pipeline(
        [
            ("imp", SimpleImputer(strategy="most_frequent")),
            ("oh", OneHotEncoder(handle_unknown="ignore", min_frequency=5)),
        ]
    )
    pre = ColumnTransformer([("num", num_pipe, nums), ("cat", cat_pipe, cats)])
    est = Ridge(alpha=1.0) if spec.task_type == "regression" else LogisticRegression(max_iter=2000)
    return Pipeline([("pre", pre), ("est", est)])


def _stringify(x: pd.DataFrame) -> pd.DataFrame:
    x = x.copy()
    for c in _cat_cols(x):
        x[c] = x[c].astype(object).map(lambda v: None if pd.isna(v) else str(v))
    return x


def _flaml_frames(x: pd.DataFrame, x_test: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    xs, ts = _stringify(x), _stringify(x_test)
    for c in _cat_cols(x):
        dtype = pd.CategoricalDtype(sorted(xs[c].dropna().unique()))
        xs[c] = xs[c].astype(dtype)
        ts[c] = ts[c].astype(dtype)
    return xs, ts


def fit_predict(
    kind: str, spec: TaskSpec, time_budget: int = 30, n_jobs: int = 4
) -> tuple[pd.DataFrame, dict[str, Any]]:
    x, y, test = load_task(spec)
    x_test = test.drop(columns=[ROW_ID])
    ids = test[ROW_ID]
    info: dict[str, Any] = {}
    y_fit = y if spec.task_type == "regression" else y.astype(str)
    model: Any
    if kind == "dummy":
        if spec.task_type == "regression":
            model = DummyRegressor(strategy="mean").fit(x, y)
        else:
            strat = "prior" if spec.metric in {"roc_auc", "pr_auc"} else "most_frequent"
            model = DummyClassifier(strategy=strat).fit(x, y_fit)
    elif kind == "linear":
        xs, x_test = _stringify(x), _stringify(x_test)
        model = _make_linear(spec, xs).fit(xs, y_fit)
    elif kind == "flaml":
        from flaml import AutoML  # type: ignore[attr-defined]

        xs, x_test = _flaml_frames(x, x_test)
        model = AutoML()  # type: ignore[no-untyped-call]
        model.fit(
            xs,
            y_fit,
            task="regression" if spec.task_type == "regression" else "classification",
            metric=FLAML_METRIC[spec.metric],
            time_budget=time_budget,
            estimator_list=["lgbm", "xgboost", "rf", "extra_tree"],
            seed=SEED,
            n_jobs=n_jobs,
            verbose=0,
            eval_method="cv",
            n_splits=3,
        )
        info = {"best_estimator": model.best_estimator, "time_budget_s": time_budget}
    else:
        raise ValueError(kind)
    return _predict_frame(spec, model, y, x_test, ids), info


def score_via_scorer(spec: TaskSpec, preds: pd.DataFrame, run_id: str) -> float:
    os.environ["SCORER_SECRET"] = _SECRET
    client = TestClient(create_app(SCORER_ROOT))
    buf = io.BytesIO(preds.to_csv(index=False).encode())
    r = client.post(
        "/v1/score-predictions",
        data={"task": spec.name, "run_id": run_id},
        files={"predictions": ("p.csv", buf)},
        headers={"Authorization": f"Bearer {run_token(_SECRET, run_id)}"},
    )
    if r.status_code != 200:
        raise RuntimeError(f"scorer rejected {spec.name}: {r.status_code} {r.text}")
    return float(r.json()["score"])
