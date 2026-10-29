"""Core of the experiments server: train / tune / evaluate / predict / compare, plus tracking.

MCP-free so it is unit-testable. Guards: data path allowlist (reuses data-tools), run ids and model
ids are slugs, artifacts live only under EXPERIMENTS_DIR, row/time/trial caps. Models are pickled
with joblib and only ever loaded from this directory by id (never by user-supplied path).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.model_selection import KFold, StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

from apps.scorer.metrics import HIGHER_IS_BETTER, compute
from benchmarks.metrics import normalized_score
from mcp_servers.data_tools.service import GuardError, load_frame

log = logging.getLogger("experiments")

ROW_ID = "row_id"
MAX_ROWS = 200_000
MAX_TIME_S = 120.0
MAX_TRIALS = 12
MIN_ROWS = 20
Family = Literal["dummy", "linear", "hgb", "rf", "flaml"]
TaskType = Literal["binary", "multiclass", "regression"]
Metric = Literal["roc_auc", "pr_auc", "f1_macro", "rmse", "mae"]
_SLUG = r"^[A-Za-z0-9_\-]{1,64}$"


class ExperimentError(ValueError):
    """Bad request or unusable data. Message is safe to show to the caller/agent."""


def experiments_root() -> Path:
    return Path(os.environ.get("EXPERIMENTS_DIR", "data/experiments"))


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataSpec(_Base):
    data_path: str = Field(min_length=1, max_length=1024)
    target: str = Field(min_length=1, max_length=256)
    task_type: TaskType
    metric: Metric
    drop_columns: list[str] = Field(default_factory=list, max_length=500)
    seed: int = Field(default=0, ge=0, le=2**31 - 1)
    val_fraction: float = Field(default=0.2, ge=0.05, le=0.5)


Selection = Literal["holdout", "cv"]


class TrainRequest(DataSpec):
    selection: Selection = "holdout"
    run_id: str = Field(pattern=_SLUG)
    family: Family
    params: dict[str, float | int | str] = Field(default_factory=dict)
    time_budget_s: float = Field(default=20.0, gt=0, le=MAX_TIME_S)


class TuneRequest(DataSpec):
    selection: Selection = "holdout"
    run_id: str = Field(pattern=_SLUG)
    family: Literal["hgb", "rf"]
    n_trials: int = Field(default=6, ge=1, le=MAX_TRIALS)
    time_budget_s: float = Field(default=30.0, gt=0, le=MAX_TIME_S)


class ModelRecord(_Base):
    model_id: str
    run_id: str
    family: Family
    params: dict[str, Any]
    task_type: TaskType
    metric: Metric
    target: str
    features: list[str]
    cat_features: list[str] = Field(default_factory=list)
    dropped: list[str]
    positive_label: str | None
    val_score: float
    train_score: float
    n_train: int
    n_val: int
    fit_on: Literal["train_split", "full"]
    selection: Selection = "holdout"
    scored: bool = True  # False for refit copies: val_score belongs to the recipe, not the copy
    cv_k: int | None = None
    cv_se: float | None = None
    fit_s: float
    seed: int
    data_path: str


class EvalRequest(_Base):
    run_id: str = Field(pattern=_SLUG)
    model_id: str = Field(pattern=_SLUG)
    data_path: str
    target: str


class EvalResult(_Base):
    model_id: str
    metric: Metric
    score: float
    n: int


class PredictRequest(_Base):
    run_id: str = Field(pattern=_SLUG)
    model_id: str = Field(pattern=_SLUG)
    features_path: str
    out_name: str = Field(default="predictions.csv", pattern=r"^[A-Za-z0-9_\-]{1,40}\.csv$")


class PredictResult(_Base):
    out_path: str
    n: int


class CompareRequest(_Base):
    run_id: str = Field(pattern=_SLUG)
    dummy: float | None = None
    flaml: float | None = None


class LeaderRow(_Base):
    model_id: str
    family: str
    val_score: float
    fit_on: str
    normalized: float | None


class CompareResult(_Base):
    metric: str | None
    best_model_id: str | None
    leaderboard: list[LeaderRow]


class RefitRequest(_Base):
    run_id: str = Field(pattern=_SLUG)
    model_id: str = Field(pattern=_SLUG)


# --- data -----------------------------------------------------------------------------------
def _prepare(spec: DataSpec) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    try:
        df, _ = load_frame(spec.data_path, MAX_ROWS, spec.seed)
    except GuardError as exc:
        raise ExperimentError(str(exc)) from None
    if spec.target not in df.columns:
        raise ExperimentError("target column not found")
    df = df[df[spec.target].notna()].reset_index(drop=True)
    if len(df) < MIN_ROWS:
        raise ExperimentError(f"too few labelled rows ({len(df)} < {MIN_ROWS})")
    y = df[spec.target]
    if spec.task_type == "regression":
        y = pd.to_numeric(y, errors="coerce")
        if y.isna().any():
            raise ExperimentError("regression target has non-numeric values")
        if y.nunique() < 2:
            raise ExperimentError("target is constant")
    else:
        y = y.astype(str)
        if y.nunique() < 2:
            raise ExperimentError("target has fewer than 2 classes")
        if spec.task_type == "binary" and y.nunique() != 2:
            raise ExperimentError("binary task needs exactly 2 classes")
    drop = {spec.target, ROW_ID, *spec.drop_columns}
    x = df.drop(columns=[c for c in df.columns if c in drop])
    dropped = [c for c in df.columns if c in drop and c != spec.target]
    empty = [c for c in x.columns if x[c].isna().all()]
    x = x.drop(columns=empty)
    if x.shape[1] == 0:
        raise ExperimentError("no usable feature columns")
    return x, y, dropped + empty


def _cat_cols(x: pd.DataFrame) -> list[str]:
    return [c for c in x.columns if not pd.api.types.is_numeric_dtype(x[c])]


def _stringify(x: pd.DataFrame) -> pd.DataFrame:
    x = x.copy()
    for c in _cat_cols(x):
        x[c] = x[c].astype(object).map(lambda v: None if pd.isna(v) else str(v))
    return x


def _positive_label(y: pd.Series) -> str:
    return str(sorted(y.astype(str).unique())[-1])  # same convention as the scorer


def _split(x: pd.DataFrame, y: pd.Series, spec: DataSpec) -> tuple[Any, Any, Any, Any]:
    strat = None
    if spec.task_type != "regression" and y.value_counts().min() >= 2:
        strat = y
    out: tuple[Any, Any, Any, Any] = train_test_split(
        x, y, test_size=spec.val_fraction, random_state=spec.seed, stratify=strat
    )
    return out


# --- models ---------------------------------------------------------------------------------
def _build(family: Family, spec: DataSpec, x: pd.DataFrame, params: dict[str, Any]) -> Any:
    reg = spec.task_type == "regression"
    cats = _cat_cols(x)
    nums = [c for c in x.columns if c not in cats]
    seed = spec.seed
    if family == "dummy":
        if reg:
            return DummyRegressor(strategy="mean")
        strat = "prior" if spec.metric in {"roc_auc", "pr_auc"} else "most_frequent"
        return DummyClassifier(strategy=strat)
    if family == "linear":
        num = Pipeline([("i", SimpleImputer(strategy="median")), ("s", StandardScaler())])
        cat = Pipeline(
            [
                ("i", SimpleImputer(strategy="most_frequent")),
                ("o", OneHotEncoder(handle_unknown="ignore", min_frequency=5)),
            ]
        )
        est: Any = (
            Ridge(alpha=float(params.get("alpha", 1.0)))
            if reg
            else LogisticRegression(max_iter=2000, C=float(params.get("C", 1.0)))
        )
        pre = ColumnTransformer([("num", num, nums), ("cat", cat, cats)])
        return Pipeline([("pre", pre), ("est", est)])
    ordinal = OrdinalEncoder(
        handle_unknown="use_encoded_value", unknown_value=-1, encoded_missing_value=-1
    )
    if family == "hgb":
        kw: dict[str, Any] = {
            "learning_rate": float(params.get("learning_rate", 0.1)),
            "max_leaf_nodes": int(params.get("max_leaf_nodes", 31)),
            "l2_regularization": float(params.get("l2_regularization", 0.0)),
            "max_iter": int(params.get("max_iter", 200)),
            "random_state": seed,
            "early_stopping": True,
        }
        hgb = HistGradientBoostingRegressor(**kw) if reg else HistGradientBoostingClassifier(**kw)
        pre = ColumnTransformer([("num", "passthrough", nums), ("cat", ordinal, cats)])
        return Pipeline([("pre", pre), ("est", hgb)])
    if family == "rf":
        rkw: dict[str, Any] = {
            "n_estimators": int(params.get("n_estimators", 300)),
            "min_samples_leaf": int(params.get("min_samples_leaf", 1)),
            "max_features": params.get("max_features", "sqrt" if not reg else 1.0),
            "n_jobs": 4,
            "random_state": seed,
        }
        rf = RandomForestRegressor(**rkw) if reg else RandomForestClassifier(**rkw)
        pre = ColumnTransformer(
            [
                ("num", SimpleImputer(strategy="median"), nums),
                ("cat", ordinal, cats),
            ]
        )
        return Pipeline([("pre", pre), ("est", rf)])
    raise ExperimentError(f"unsupported family {family!r}")


FLAML_N_JOBS = 4  # fixed so results do not depend on how many cores the machine has
FLAML_ESTIMATORS = ["lgbm", "xgboost", "rf", "extra_tree"]


def _fit_flaml(
    spec: DataSpec,
    x: pd.DataFrame,
    y: pd.Series,
    budget: float,
    start: tuple[str, dict[str, Any]] | None = None,
) -> tuple[Any, dict[str, Any]]:
    from flaml import AutoML  # type: ignore[attr-defined]

    xs = _stringify(x)
    for c in _cat_cols(x):
        xs[c] = xs[c].astype(pd.CategoricalDtype(sorted(xs[c].dropna().unique())))
    flaml_metric = {
        "roc_auc": "roc_auc",
        "pr_auc": "ap",
        "f1_macro": "macro_f1",
        "rmse": "rmse",
        "mae": "mae",
    }[spec.metric]
    automl = AutoML()  # type: ignore[no-untyped-call]
    # `start` = refit mode: evaluate exactly the selected configuration once (max_iter=1) and let
    # FLAML retrain it on every row passed in, instead of searching again.
    search: dict[str, Any] = (
        {"estimator_list": [start[0]], "starting_points": {start[0]: start[1]}, "max_iter": 1}
        if start
        else {"estimator_list": FLAML_ESTIMATORS, "time_budget": max(1, int(budget))}
    )
    automl.fit(
        xs,
        y,
        task="regression" if spec.task_type == "regression" else "classification",
        metric=flaml_metric,
        seed=spec.seed,
        n_jobs=FLAML_N_JOBS,
        verbose=0,
        eval_method="cv",
        n_splits=3,
        **search,
    )
    return _FlamlModel(automl, {c: list(xs[c].cat.categories) for c in _cat_cols(x)}), {
        "best_estimator": automl.best_estimator,
        "best_config": _jsonable(automl.best_config),
    }


def _jsonable(cfg: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.item() if hasattr(v, "item") else v) for k, v in cfg.items()}


class _FlamlModel:
    """Applies the training category sets so predict works on raw frames."""

    def __init__(self, automl: Any, cats: dict[str, list[str]]) -> None:
        self.automl, self.cats = automl, cats
        self.classes_ = getattr(automl, "classes_", None)

    def _prep(self, x: pd.DataFrame) -> pd.DataFrame:
        xs = _stringify(x)
        for c, cats in self.cats.items():
            xs[c] = xs[c].astype(pd.CategoricalDtype(cats))
        return xs

    def predict(self, x: pd.DataFrame) -> Any:
        return self.automl.predict(self._prep(x))

    def predict_proba(self, x: pd.DataFrame) -> Any:
        return self.automl.predict_proba(self._prep(x))


def _prep_for(family: Family, x: pd.DataFrame) -> pd.DataFrame:
    return _stringify(x) if family != "flaml" else x


def _fit(
    family: Family,
    spec: DataSpec,
    x: pd.DataFrame,
    y: pd.Series,
    params: dict[str, Any],
    budget: float,
) -> tuple[Any, dict[str, Any]]:
    if family == "flaml":
        est, cfg = params.get("best_estimator"), params.get("best_config")
        start = (str(est), dict(cfg)) if est and cfg else None
        return _fit_flaml(spec, x, y, budget, start)
    model = _build(family, spec, x, params)
    model.fit(_prep_for(family, x), y)
    return model, {}


def _predict(
    model: Any, family: Family, spec: DataSpec, x: pd.DataFrame, positive: str | None
) -> np.ndarray[Any, Any]:
    xin = _prep_for(family, x)
    if spec.task_type == "regression" or spec.metric == "f1_macro":
        return np.asarray(model.predict(xin))
    classes = [str(c) for c in model.classes_]
    return np.asarray(model.predict_proba(xin)[:, classes.index(str(positive))])


def _score(spec: DataSpec, y_true: pd.Series, pred: Any, positive: str | None) -> float:
    if spec.task_type != "regression" and spec.metric in {"roc_auc", "pr_auc"}:
        return compute(spec.metric, (y_true.astype(str) == positive).astype(int), pred)
    return compute(spec.metric, y_true, pred)


# --- store ----------------------------------------------------------------------------------
def _run_dir(run_id: str) -> Path:
    if not re.fullmatch(_SLUG, run_id):
        raise ExperimentError("invalid run id")
    d = experiments_root() / run_id
    (d / "models").mkdir(parents=True, exist_ok=True)
    return d


def _track(run_id: str, event: dict[str, Any]) -> None:
    with (_run_dir(run_id) / "tracking.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, sort_keys=True, default=str) + "\n")


def _model_id(family: str, req_json: str) -> str:
    return f"{family}-{hashlib.sha256(req_json.encode()).hexdigest()[:10]}"


def _save(rec: ModelRecord, model: Any) -> None:
    d = _run_dir(rec.run_id) / "models"
    joblib.dump(model, d / f"{rec.model_id}.joblib")
    (d / f"{rec.model_id}.json").write_text(rec.model_dump_json(indent=2), encoding="utf-8")
    _track(rec.run_id, {"event": "model_saved", **rec.model_dump(exclude={"features"})})


def load_record(run_id: str, model_id: str) -> ModelRecord:
    p = _run_dir(run_id) / "models" / f"{model_id}.json"
    if not p.exists():
        raise ExperimentError("unknown model id")
    return ModelRecord.model_validate_json(p.read_text(encoding="utf-8"))


def _load_model(run_id: str, model_id: str) -> Any:
    load_record(run_id, model_id)
    return joblib.load(_run_dir(run_id) / "models" / f"{model_id}.joblib")


def model_path(run_id: str, model_id: str) -> Path:
    load_record(run_id, model_id)
    return _run_dir(run_id) / "models" / f"{model_id}.joblib"


# --- tools ----------------------------------------------------------------------------------
def train_model(req: TrainRequest) -> ModelRecord:
    """Holdout: fit on a seeded train split, score on the held-out split. CV: k-fold on all rows,
    final model fit on all rows (`val_score` = mean CV score, `cv_se` its standard error)."""
    if req.selection == "cv":
        return _train_cv(req)
    x, y, dropped = _prepare(req)
    xt, xv, yt, yv = _split(x, y, req)
    positive = _positive_label(y) if req.task_type != "regression" else None
    t0 = time.monotonic()
    model, info = _fit(req.family, req, xt, yt, dict(req.params), req.time_budget_s)
    fit_s = time.monotonic() - t0
    val = _score(req, yv, _predict(model, req.family, req, xv, positive), positive)
    tr = _score(req, yt, _predict(model, req.family, req, xt, positive), positive)
    rec = ModelRecord(
        model_id=_model_id(req.family, req.model_dump_json()),
        run_id=req.run_id, family=req.family, params={**req.params, **info},
        task_type=req.task_type, metric=req.metric, target=req.target,
        features=list(x.columns), cat_features=_cat_cols(x), dropped=dropped,
        positive_label=positive,
        val_score=val, train_score=tr, n_train=len(xt), n_val=len(xv),
        fit_on="train_split", fit_s=round(fit_s, 3), seed=req.seed, data_path=req.data_path,
    )  # fmt: skip
    _save(rec, model)
    log.info("trained", extra={"ctx": {"run_id": req.run_id, "model": rec.model_id, "val": val}})
    return rec


def cv_folds(spec: DataSpec, y: pd.Series, n: int) -> tuple[int, Any]:
    """k = 5 (3 above 50k rows); stratified when every class has >= k rows, else fewer folds."""
    k = 3 if n > 50_000 else 5
    if spec.task_type == "regression":
        return k, KFold(k, shuffle=True, random_state=spec.seed)
    k = max(2, min(k, int(y.value_counts().min())))
    return k, StratifiedKFold(k, shuffle=True, random_state=spec.seed)


def _train_cv(req: TrainRequest) -> ModelRecord:
    x, y, dropped = _prepare(req)
    positive = _positive_label(y) if req.task_type != "regression" else None
    k, folder = cv_folds(req, y, len(x))
    params = dict(req.params)
    t0 = time.monotonic()
    final: Any = None
    if req.family == "flaml":
        # search once on all rows (FLAML cross-validates internally), then re-score exactly the
        # selected configuration under the same k-fold protocol as every other family
        final, info = _fit(req.family, req, x, y, params, req.time_budget_s)
        params = {**params, **info}
    scores = []
    for a, b in folder.split(x, y if req.task_type != "regression" else None):
        m, _ = _fit(req.family, req, x.iloc[a], y.iloc[a], params, 1)
        scores.append(
            _score(req, y.iloc[b], _predict(m, req.family, req, x.iloc[b], positive), positive)
        )
    if final is None:
        final, info = _fit(req.family, req, x, y, params, 1)
    fit_s = time.monotonic() - t0
    mean = float(np.mean(scores))
    se = float(np.std(scores, ddof=1) / np.sqrt(len(scores))) if len(scores) > 1 else 0.0
    train = _score(req, y, _predict(final, req.family, req, x, positive), positive)
    rec = ModelRecord(
        model_id=_model_id(req.family, req.model_dump_json()),
        run_id=req.run_id, family=req.family, params={**params, **info},
        task_type=req.task_type, metric=req.metric, target=req.target,
        features=list(x.columns), cat_features=_cat_cols(x), dropped=dropped,
        positive_label=positive, val_score=mean, train_score=train, n_train=len(x), n_val=0,
        fit_on="full", selection="cv", cv_k=k, cv_se=se, fit_s=round(fit_s, 3), seed=req.seed,
        data_path=req.data_path,
    )  # fmt: skip
    _save(rec, final)
    return rec


def _sample_params(family: str, rng: np.random.Generator) -> dict[str, float | int]:
    if family == "hgb":
        return {
            "learning_rate": float(rng.choice([0.03, 0.05, 0.1, 0.2])),
            "max_leaf_nodes": int(rng.choice([8, 15, 31, 63])),
            "l2_regularization": float(rng.choice([0.0, 0.1, 1.0, 10.0])),
            "max_iter": int(rng.choice([150, 300])),
        }
    return {
        "n_estimators": int(rng.choice([200, 400])),
        "min_samples_leaf": int(rng.choice([1, 2, 5])),
        "max_features": float(rng.choice([0.3, 0.5, 0.8])),
    }


def tune_model(req: TuneRequest) -> ModelRecord:
    """Random search with 3-fold CV on the train split only; best params -> train_model."""
    x, y, _ = _prepare(req)
    xt, _xv, yt, _yv = (x, None, y, None) if req.selection == "cv" else _split(x, y, req)
    positive = _positive_label(y) if req.task_type != "regression" else None
    rng = np.random.default_rng(req.seed)
    deadline = time.monotonic() + req.time_budget_s
    best: tuple[float, dict[str, Any]] | None = None
    sign = 1.0 if HIGHER_IS_BETTER[req.metric] else -1.0
    folder: Any = (
        KFold(3, shuffle=True, random_state=req.seed)
        if req.task_type == "regression"
        else StratifiedKFold(3, shuffle=True, random_state=req.seed)
    )
    n_done = 0
    for _ in range(req.n_trials):
        if n_done and time.monotonic() > deadline:
            break
        params = _sample_params(req.family, rng)
        scores = []
        try:
            for a, b in folder.split(xt, yt if req.task_type != "regression" else None):
                m, _ = _fit(req.family, req, xt.iloc[a], yt.iloc[a], params, 1)
                p = _predict(m, req.family, req, xt.iloc[b], positive)
                scores.append(_score(req, yt.iloc[b], p, positive))
        except ValueError:
            continue  # e.g. a fold missing a class; skip this trial
        n_done += 1
        mean = float(np.mean(scores))
        _track(req.run_id, {"event": "trial", "family": req.family, "params": params, "cv": mean})
        if best is None or sign * mean > sign * best[0]:
            best = (mean, params)
    if best is None:
        raise ExperimentError("no tuning trial completed")
    return train_model(
        TrainRequest(
            **req.model_dump(exclude={"n_trials", "time_budget_s", "family"}),
            family=req.family, params=best[1], time_budget_s=req.time_budget_s,
        )
    )  # fmt: skip


def refit_full(req: RefitRequest) -> ModelRecord:
    """Refit a validated recipe on all labelled rows (no validation score is claimed for it)."""
    rec = load_record(req.run_id, req.model_id)
    if rec.fit_on == "full":
        return rec  # CV-selected models are already fit on every row
    spec = DataSpec(
        data_path=rec.data_path, target=rec.target, task_type=rec.task_type,
        metric=rec.metric, drop_columns=rec.dropped, seed=rec.seed,
    )  # fmt: skip
    x, y, _ = _prepare(spec)
    params = {k: v for k, v in rec.params.items()}
    model, info = _fit(rec.family, spec, x, y, params, 1)
    new = rec.model_copy(
        update={
            "params": {**params, **info},
            "model_id": f"{rec.model_id}-full",
            "fit_on": "full",
            "scored": False,
            "n_train": len(x),
            "n_val": 0,
        }
    )
    _save(new, model)
    return new


class ExplainRequest(_Base):
    run_id: str = Field(pattern=_SLUG)
    model_id: str = Field(pattern=_SLUG)
    n_repeats: int = Field(default=3, ge=1, le=10)
    top_k: int = Field(default=10, ge=1, le=30)
    max_features: int = Field(default=60, ge=1, le=200)


class Importance(_Base):
    feature: str
    mean_drop: float  # score lost (in the metric's better-is-higher direction) when shuffled
    std: float


class ExplainResult(_Base):
    model_id: str
    metric: Metric
    baseline_score: float
    n_eval: int
    top: list[Importance]
    method: str = "permutation importance on a seeded 25% holdout; recipe refit on the other 75%"


def explain_model(req: ExplainRequest) -> ExplainResult:
    """Permutation importance. Honest by construction: the recipe is refit on 75% of the labelled
    rows and every feature is shuffled in the other 25%, so the model never saw those rows."""
    rec = load_record(req.run_id, req.model_id)
    spec = DataSpec(
        data_path=rec.data_path, target=rec.target, task_type=rec.task_type, metric=rec.metric,
        drop_columns=rec.dropped, seed=rec.seed, val_fraction=0.25,
    )  # fmt: skip
    x, y, _ = _prepare(spec)
    xt, xv, yt, yv = _split(x, y, spec)
    positive = rec.positive_label
    model, _ = _fit(rec.family, spec, xt, yt, dict(rec.params), 1)
    base = _score(spec, yv, _predict(model, rec.family, spec, xv, positive), positive)
    sign = 1.0 if HIGHER_IS_BETTER[rec.metric] else -1.0
    rng = np.random.default_rng(rec.seed)
    out: list[Importance] = []
    for col in list(xv.columns)[: req.max_features]:
        drops = []
        for _ in range(req.n_repeats):
            shuffled = xv.copy()
            shuffled[col] = rng.permutation(shuffled[col].to_numpy())
            s = _score(spec, yv, _predict(model, rec.family, spec, shuffled, positive), positive)
            drops.append(sign * (base - s))
        out.append(
            Importance(feature=str(col), mean_drop=float(np.mean(drops)), std=float(np.std(drops)))
        )
    out.sort(key=lambda i: -i.mean_drop)
    return ExplainResult(
        model_id=rec.model_id, metric=rec.metric, baseline_score=base, n_eval=len(xv),
        top=out[: req.top_k],
    )  # fmt: skip


def evaluate_model(req: EvalRequest) -> EvalResult:
    rec = load_record(req.run_id, req.model_id)
    model = _load_model(req.run_id, req.model_id)
    spec = DataSpec(
        data_path=req.data_path, target=req.target, task_type=rec.task_type,
        metric=rec.metric, seed=rec.seed,
    )  # fmt: skip
    x, y, _ = _prepare(spec)
    missing = [c for c in rec.features if c not in x.columns]
    if missing:
        raise ExperimentError(f"evaluation data lacks {len(missing)} feature column(s)")
    pred = _predict(model, rec.family, spec, x[rec.features], rec.positive_label)
    return EvalResult(
        model_id=rec.model_id, metric=rec.metric, n=len(x),
        score=_score(spec, y, pred, rec.positive_label),
    )  # fmt: skip


def predict(req: PredictRequest) -> PredictResult:
    """Predictions in the scorer's CSV format (`row_id`, `pred`); row_id kept when present."""
    rec = load_record(req.run_id, req.model_id)
    model = _load_model(req.run_id, req.model_id)
    try:
        df, _ = load_frame(req.features_path, MAX_ROWS, 0)
    except GuardError as exc:
        raise ExperimentError(str(exc)) from None
    missing = [c for c in rec.features if c not in df.columns]
    if missing:
        raise ExperimentError(f"features file lacks {len(missing)} column(s)")
    spec = DataSpec(
        data_path=req.features_path, target=rec.target, task_type=rec.task_type,
        metric=rec.metric,
    )  # fmt: skip
    pred = _predict(model, rec.family, spec, df[rec.features], rec.positive_label)
    ids = df[ROW_ID].to_numpy() if ROW_ID in df.columns else np.arange(len(df))
    out = _run_dir(req.run_id) / req.out_name
    pd.DataFrame({ROW_ID: ids, "pred": pred}).to_csv(out, index=False)
    return PredictResult(out_path=str(out), n=len(df))


def compare_models(req: CompareRequest) -> CompareResult:
    d = _run_dir(req.run_id) / "models"
    recs = [ModelRecord.model_validate_json(p.read_text("utf-8")) for p in sorted(d.glob("*.json"))]
    if not recs:
        return CompareResult(metric=None, best_model_id=None, leaderboard=[])
    metric = recs[0].metric
    sign = 1.0 if HIGHER_IS_BETTER[metric] else -1.0
    # full refits carry the score of the recipe they were fit from
    scored = [r for r in recs if r.scored]
    scored.sort(key=lambda r: (-sign * r.val_score, r.model_id))
    rows = []
    for r in scored:
        norm = (
            normalized_score(r.val_score, req.dummy, req.flaml, metric)
            if req.dummy is not None and req.flaml is not None
            else None
        )
        rows.append(
            LeaderRow(
                model_id=r.model_id,
                family=r.family,
                val_score=r.val_score,
                fit_on=r.fit_on,
                normalized=norm,
            )
        )
    return CompareResult(
        metric=metric, best_model_id=rows[0].model_id if rows else None, leaderboard=rows
    )
