"""Scorer service: the only holder of hidden test labels.

S2 scope: score a predictions CSV (`row_id,pred`) against labels. Predict-in-sandbox and the
one-score-per-run rule arrive in S11. Auth is a per-run HMAC token derived from SCORER_SECRET.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import os
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel

from apps.scorer.metrics import compute
from apps.scorer.splits import ROW_ID
from benchmarks.tasks.registry import TaskSpec, get_task

MAX_BYTES = 20_000_000


class ScoreResponse(BaseModel):
    run_id: str
    task: str
    metric: str
    score: float
    n: int


def run_token(secret: str, run_id: str) -> str:
    return hmac.new(secret.encode(), run_id.encode(), hashlib.sha256).hexdigest()


def score_predictions(spec: TaskSpec, labels: pd.DataFrame, preds: pd.DataFrame) -> float:
    if not {ROW_ID, "pred"} <= set(preds.columns):
        raise ValueError("predictions need columns row_id,pred")
    if preds[ROW_ID].duplicated().any():
        raise ValueError("duplicate row_id in predictions")
    if set(preds[ROW_ID]) != set(labels[ROW_ID]):
        raise ValueError("row_id set does not match the test set")
    merged = labels.merge(preds, on=ROW_ID, how="left")
    if spec.task_type == "regression" or spec.metric in {"roc_auc", "pr_auc"}:
        pred = pd.to_numeric(merged["pred"], errors="coerce")
        if not np.isfinite(pred.to_numpy(dtype=float)).all():
            raise ValueError("predictions must be finite numbers")
    else:
        pred = merged["pred"].astype(str)
    y = merged[spec.target]
    if spec.metric in {"roc_auc", "pr_auc"}:
        classes = sorted(y.astype(str).unique())
        y = (y.astype(str) == classes[-1]).astype(int)  # positive = last class label, sorted
    elif spec.task_type != "regression":
        y = y.astype(str)
    return compute(spec.metric, y, pred)


def create_app(scorer_root: Path | None = None) -> FastAPI:
    root = scorer_root or Path(os.environ.get("SCORER_DATA", "scorer_data"))
    app = FastAPI(title="scorer")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/score-predictions", response_model=ScoreResponse)
    async def score(
        task: str = Form(...),
        run_id: str = Form(...),
        predictions: UploadFile = File(...),
        authorization: str | None = Header(default=None),
    ) -> ScoreResponse:
        secret = os.environ.get("SCORER_SECRET", "")
        expected = run_token(secret, run_id) if secret else None
        supplied = (authorization or "").removeprefix("Bearer ").strip()
        if expected is None or not hmac.compare_digest(supplied, expected):
            raise HTTPException(401, "invalid run token")
        try:
            spec = get_task(task)
        except KeyError:
            raise HTTPException(404, "unknown task") from None
        path = root / spec.name / "test_labels.parquet"
        if not path.exists():
            raise HTTPException(404, "task not prepared")
        raw = await predictions.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise HTTPException(413, "predictions too large")
        try:
            preds = pd.read_csv(io.BytesIO(raw))
            value = score_predictions(spec, pd.read_parquet(path), preds)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return ScoreResponse(
            run_id=run_id, task=spec.name, metric=spec.metric, score=value, n=len(preds)
        )

    return app


app = create_app()
