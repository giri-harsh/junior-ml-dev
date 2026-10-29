from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from mcp_servers.experiments import service as s


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("DATA_TOOLS_ROOTS", str(root))
    monkeypatch.setenv("EXPERIMENTS_DIR", str(tmp_path / "exp"))
    assert s.experiments_root() == tmp_path / "exp"  # the env binding really took effect
    return root


def _clf(root: Path, n: int = 400, name: str = "c.csv") -> str:
    rng = np.random.default_rng(1)
    a, b = rng.normal(size=n), rng.normal(size=n)
    y = (a + 0.5 * b + rng.normal(scale=0.5, size=n) > 0).astype(int)
    df = pd.DataFrame({"a": a, "b": b, "cat": rng.choice(["u", "v", "w"], n), "y": y})
    df.loc[::17, "a"] = np.nan
    p = root / name
    df.to_csv(p, index=False)
    return str(p)


def _req(path: str, **kw: object) -> s.TrainRequest:
    base: dict[str, object] = {
        "data_path": path, "target": "y", "task_type": "binary", "metric": "roc_auc",
        "run_id": "r1", "family": "hgb",
    }  # fmt: skip
    base.update(kw)
    return s.TrainRequest.model_validate(base)


def test_train_beats_dummy_and_is_deterministic(env: Path) -> None:
    p = _clf(env)
    hgb = s.train_model(_req(p))
    dummy = s.train_model(_req(p, family="dummy"))
    assert hgb.val_score > 0.8 and dummy.val_score == pytest.approx(0.5)
    assert s.train_model(_req(p)).val_score == hgb.val_score
    assert hgb.model_id == s.train_model(_req(p)).model_id


@pytest.mark.parametrize("family", ["linear", "rf", "hgb"])
def test_each_family_trains_predicts_and_evaluates(env: Path, family: str) -> None:
    p = _clf(env)
    rec = s.train_model(_req(p, family=family))
    ev = s.evaluate_model(
        s.EvalRequest(run_id="r1", model_id=rec.model_id, data_path=p, target="y")
    )
    assert ev.score > 0.75
    feats = env / "f.csv"
    pd.read_csv(p).drop(columns=["y"]).assign(row_id=lambda d: np.arange(len(d)) + 100).to_csv(
        feats, index=False
    )
    out = s.predict(s.PredictRequest(run_id="r1", model_id=rec.model_id, features_path=str(feats)))
    got = pd.read_csv(out.out_path)
    assert list(got.columns) == ["row_id", "pred"] and got.row_id.iloc[0] == 100
    assert got.pred.between(0, 1).all()


def test_regression_and_multiclass(env: Path) -> None:
    rng = np.random.default_rng(2)
    n = 300
    x = rng.normal(size=(n, 3))
    df = pd.DataFrame(x, columns=["a", "b", "c"])
    df["r"] = 2 * x[:, 0] + rng.normal(scale=0.1, size=n)
    df["m"] = np.where(x[:, 0] > 0.4, "hi", np.where(x[:, 0] < -0.4, "lo", "mid"))
    p = env / "m.csv"
    df.to_csv(p, index=False)
    reg = s.train_model(
        _req(str(p), target="r", task_type="regression", metric="rmse", family="rf")
    )
    base = s.train_model(
        _req(str(p), target="r", task_type="regression", metric="rmse", family="dummy")
    )
    assert reg.val_score < base.val_score / 3
    mc = s.train_model(
        _req(str(p), target="m", task_type="multiclass", metric="f1_macro", family="linear",
             drop_columns=["r"])
    )  # fmt: skip
    assert mc.val_score > 0.6 and "r" in mc.dropped


def test_tune_improves_or_matches_default_search_and_tracks(env: Path) -> None:
    p = _clf(env)
    rec = s.tune_model(
        s.TuneRequest(
            data_path=p, target="y", task_type="binary", metric="roc_auc", run_id="r1",
            family="hgb", n_trials=3, time_budget_s=30,
        )
    )  # fmt: skip
    assert rec.val_score > 0.8
    lines = (env.parent / "exp" / "r1" / "tracking.jsonl").read_text("utf-8").splitlines()
    assert sum('"event": "trial"' in ln for ln in lines) == 3


def test_refit_full_and_compare_with_normalisation(env: Path) -> None:
    p = _clf(env)
    best = s.train_model(_req(p))
    s.train_model(_req(p, family="dummy"))
    full = s.refit_full(s.RefitRequest(run_id="r1", model_id=best.model_id))
    assert full.fit_on == "full" and full.n_train == 400
    res = s.compare_models(s.CompareRequest(run_id="r1", dummy=0.5, flaml=0.95))
    assert res.best_model_id == best.model_id
    assert all(r.fit_on == "train_split" for r in res.leaderboard)
    assert res.leaderboard[0].normalized is not None and res.leaderboard[0].normalized > 0.5
    assert s.compare_models(s.CompareRequest(run_id="empty")).best_model_id is None


def test_error_metric_leaderboard_sorts_lowest_first(env: Path) -> None:
    rng = np.random.default_rng(3)
    df = pd.DataFrame({"a": rng.normal(size=200)})
    df["r"] = 3 * df.a
    p = env / "r.csv"
    df.to_csv(p, index=False)
    for fam in ("dummy", "linear"):
        s.train_model(_req(str(p), target="r", task_type="regression", metric="rmse", family=fam))
    res = s.compare_models(s.CompareRequest(run_id="r1"))
    assert [r.family for r in res.leaderboard] == ["linear", "dummy"]


@pytest.mark.parametrize(
    ("mutate", "msg"),
    [
        (lambda d: d.assign(y=1), "fewer than 2 classes"),
        (lambda d: d.head(10), "too few labelled rows"),
        (
            lambda d: d.assign(y=np.where(d.index % 3 == 0, "z", d.y.astype(str))),
            "exactly 2 classes",
        ),
    ],
)
def test_bad_data_is_rejected_with_clear_errors(env: Path, mutate: object, msg: str) -> None:
    df = mutate(pd.read_csv(_clf(env)))  # type: ignore[operator]
    p = env / "bad.csv"
    df.to_csv(p, index=False)
    with pytest.raises(s.ExperimentError, match=msg):
        s.train_model(_req(str(p)))


def test_all_missing_column_is_dropped_and_missing_target_rows_ignored(env: Path) -> None:
    df = pd.read_csv(_clf(env)).assign(empty=np.nan)
    df.loc[:5, "y"] = np.nan
    p = env / "m.csv"
    df.to_csv(p, index=False)
    rec = s.train_model(_req(str(p)))
    assert "empty" in rec.dropped and "empty" not in rec.features


def test_guards(env: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.csv"
    pd.DataFrame({"y": [0, 1] * 20, "a": range(40)}).to_csv(outside, index=False)
    with pytest.raises(s.ExperimentError, match="outside allowed roots"):
        s.train_model(_req(str(outside)))
    with pytest.raises(ValidationError):
        _req("x", run_id="../evil")
    with pytest.raises(ValidationError):
        _req("x", time_budget_s=10_000)
    with pytest.raises(ValidationError):
        s.TuneRequest(
            data_path="x", target="y", task_type="binary", metric="roc_auc", run_id="r",
            family="hgb", n_trials=1000,
        )  # fmt: skip
    p = _clf(env)
    with pytest.raises(s.ExperimentError, match="unknown model id"):
        s.evaluate_model(s.EvalRequest(run_id="r1", model_id="nope", data_path=p, target="y"))
    with pytest.raises(ValidationError):
        s.EvalRequest(run_id="r1", model_id="../../etc", data_path=p, target="y")


def test_evaluate_requires_the_training_features(env: Path) -> None:
    p = _clf(env)
    rec = s.train_model(_req(p))
    thin = env / "thin.csv"
    pd.read_csv(p)[["y", "a"]].to_csv(thin, index=False)
    with pytest.raises(s.ExperimentError, match="lacks"):
        s.evaluate_model(
            s.EvalRequest(run_id="r1", model_id=rec.model_id, data_path=str(thin), target="y")
        )


def test_flaml_family_smoke(env: Path) -> None:
    rec = s.train_model(_req(_clf(env, n=300), family="flaml", time_budget_s=3))
    assert rec.val_score > 0.7 and "best_estimator" in rec.params
    ev = s.evaluate_model(
        s.EvalRequest(run_id="r1", model_id=rec.model_id, data_path=rec.data_path, target="y")
    )
    assert ev.score > 0.7


def test_flaml_is_refit_on_all_rows_with_the_selected_configuration(env: Path) -> None:
    rec = s.train_model(_req(_clf(env, n=300), family="flaml", time_budget_s=3))
    assert rec.n_train < 300  # selected on the train split
    full = s.refit_full(s.RefitRequest(run_id="r1", model_id=rec.model_id))
    assert full.fit_on == "full" and full.n_train == 300 and full.model_id.endswith("-full")
    assert full.params["best_estimator"] == rec.params["best_estimator"]
    ev = s.evaluate_model(
        s.EvalRequest(run_id="r1", model_id=full.model_id, data_path=rec.data_path, target="y")
    )
    assert ev.score > 0.7


def test_cv_selection_scores_all_rows_and_reports_a_standard_error(env: Path) -> None:
    p = _clf(env)
    rec = s.train_model(_req(p, family="hgb", selection="cv"))
    assert rec.selection == "cv" and rec.fit_on == "full" and rec.n_train == 400 and rec.n_val == 0
    assert rec.cv_k == 5 and rec.cv_se is not None and rec.cv_se > 0 and rec.scored
    assert rec.val_score > 0.8
    again = s.refit_full(s.RefitRequest(run_id="r1", model_id=rec.model_id))
    assert again.model_id == rec.model_id  # nothing to refit
    board = s.compare_models(s.CompareRequest(run_id="r1"))
    assert [r.model_id for r in board.leaderboard] == [rec.model_id]


def test_cv_fold_count_rules() -> None:
    import pandas as pd

    spec = s.DataSpec(data_path="x", target="y", task_type="binary", metric="roc_auc")
    y = pd.Series([0] * 30 + [1] * 3)
    k, _ = s.cv_folds(spec, y, 33)
    assert k == 3  # the rarest class has 3 rows: fewer folds, still stratified
    k, _ = s.cv_folds(spec, pd.Series([0, 1] * 20), 60_000)
    assert k == 3  # large training sets use 3 folds
    reg = s.DataSpec(data_path="x", target="y", task_type="regression", metric="rmse")
    assert s.cv_folds(reg, pd.Series(range(100)), 100)[0] == 5


def test_cv_flaml_and_error_metric(env: Path) -> None:
    rng = np.random.default_rng(5)
    df = pd.DataFrame({"a": rng.normal(size=300)})
    df["r"] = 2 * df.a + rng.normal(scale=0.2, size=300)
    p = env / "cvr.csv"
    df.to_csv(p, index=False)
    rec = s.train_model(
        _req(str(p), target="r", task_type="regression", metric="rmse", family="flaml",
             selection="cv", time_budget_s=3)
    )  # fmt: skip
    assert rec.fit_on == "full" and rec.val_score < 1.0 and rec.params["best_estimator"]


def test_permutation_importance_finds_the_informative_feature(env: Path) -> None:
    rng = np.random.default_rng(7)
    n = 600
    df = pd.DataFrame(
        {"signal": rng.normal(size=n), "noise1": rng.normal(size=n), "noise2": rng.normal(size=n)}
    )
    df["y"] = (df.signal + rng.normal(scale=0.3, size=n) > 0).astype(int)
    p = env / "imp.csv"
    df.to_csv(p, index=False)
    rec = s.train_model(_req(str(p), family="rf", selection="cv"))
    res = s.explain_model(s.ExplainRequest(run_id="r1", model_id=rec.model_id, top_k=3))
    assert res.top[0].feature == "signal" and res.top[0].mean_drop > 0.1
    assert {i.feature for i in res.top[1:]} <= {"noise1", "noise2"}
    assert all(i.mean_drop < res.top[0].mean_drop for i in res.top[1:])
    assert res.n_eval == 150


def test_flaml_accepts_feature_names_with_special_characters(env: Path) -> None:
    rng = np.random.default_rng(9)
    df = pd.DataFrame(
        {
            "fLength:": rng.normal(size=300),
            'a"b{c}': rng.normal(size=300),
            "cat:x": rng.choice(["u", "v"], 300),
        }
    )
    df["y"] = (df["fLength:"] > 0).astype(int)
    p = env / "names.csv"
    df.to_csv(p, index=False)
    rec = s.train_model(_req(str(p), family="flaml", time_budget_s=3, selection="cv"))
    assert rec.val_score > 0.8 and "fLength:" in rec.features
    ev = s.evaluate_model(
        s.EvalRequest(run_id="r1", model_id=rec.model_id, data_path=str(p), target="y")
    )
    assert ev.score > 0.8
