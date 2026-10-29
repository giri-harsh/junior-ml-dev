"""deploy server core: package a model into a self-contained bundle and stage a local deployment.

`package_model` is safe (writes files under DEPLOY_DIR). `deploy_local` is risky and requires a
single-use approval token bound to (deploy, run_id, model_id); the service consumes it itself, so
a caller that skipped the harness guard still cannot deploy. "Deploy" here means: verify the
bundle's predict service answers on a bundled example, then write `deployed.json` with the exact
docker compose command. Docker is not available on this machine, so containers are never started
(NOT RUN, see KNOWN_GAPS).
"""

from __future__ import annotations

import hashlib
import importlib.metadata as md
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from harness.security.approvals import ApprovalError, ApprovalStore
from mcp_servers.data_tools.service import GuardError, load_frame
from mcp_servers.experiments import service as ex

SLUG = r"^[A-Za-z0-9_\-]{1,80}$"


class DeployError(ValueError):
    """Message is safe to show to the caller."""


def deploy_root() -> Path:
    return Path(os.environ.get("DEPLOY_DIR", "data/deploy"))


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PackageRequest(_Base):
    run_id: str = Field(pattern=SLUG)
    model_id: str = Field(pattern=SLUG)


class PackageResult(_Base):
    bundle_dir: str
    files: list[str]
    model_sha256: str


class DeployRequest(_Base):
    run_id: str = Field(pattern=SLUG)
    model_id: str = Field(pattern=SLUG)
    approval_token: str = Field(min_length=10, max_length=2000)


class DeployResult(_Base):
    status: str
    bundle_dir: str
    smoke_ok: bool
    command: str
    containers_started: bool


APP_TEMPLATE = '''"""Generated predict service. Run: uvicorn app:app --host 0.0.0.0 --port 8000"""
import json
from pathlib import Path

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

HERE = Path(__file__).parent
REC = json.loads((HERE / "model_record.json").read_text(encoding="utf-8"))
MODEL = joblib.load(HERE / "model.joblib")
app = FastAPI(title="junior-ml-dev predict service")


class Rows(BaseModel):
    rows: list[dict]


@app.get("/health")
def health():
    return {"status": "ok", "model_id": REC["model_id"], "metric": REC["metric"]}


@app.post("/predict")
def predict(body: Rows):
    if not body.rows or len(body.rows) > 10000:
        raise HTTPException(422, "send between 1 and 10000 rows")
    df = pd.DataFrame(body.rows)
    missing = [c for c in REC["features"] if c not in df.columns]
    if missing:
        raise HTTPException(422, f"missing feature columns: {missing[:5]}")
    df = df[REC["features"]].copy()
    for c in REC["cat_features"]:
        df[c] = df[c].astype(object).map(lambda v: None if pd.isna(v) else str(v))
    if REC["task_type"] == "regression" or REC["metric"] == "f1_macro":
        pred = MODEL.predict(df)
    else:
        classes = [str(c) for c in MODEL.classes_]
        pred = MODEL.predict_proba(df)[:, classes.index(str(REC["positive_label"]))]
    return {"predictions": [float(p) if not isinstance(p, str) else p for p in pred.tolist()]}
'''

DOCKERFILE = """FROM python:3.11-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
USER nobody
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
"""

COMPOSE = """services:
  predict:
    build: .
    ports:
      - "127.0.0.1:8000:8000"
    read_only: true
    restart: unless-stopped
"""


def _pin(names: list[str]) -> str:
    lines = []
    for n in names:
        try:
            lines.append(f"{n}=={md.version(n)}")
        except md.PackageNotFoundError:  # not installed here; leave unpinned
            lines.append(n)
    return "\n".join(lines) + "\n"


def _card(rec: ex.ModelRecord) -> str:
    return (
        f"# Model card: {rec.model_id}\n\n"
        f"- Family: {rec.family}; task {rec.task_type}; metric {rec.metric}\n"
        f"- Validation score (seeded holdout of the training file): {rec.val_score:.4f}\n"
        f"- Trained on {rec.n_train} rows; fit on: {rec.fit_on}; seed {rec.seed}\n"
        f"- Features: {len(rec.features)}; dropped columns: {len(rec.dropped)}\n"
        "- Limits: holdout score is optimistic versus a truly unseen test set; not validated for "
        "distribution shift; the bundle unpickles a trusted model file, never load others.\n"
    )


def package_model(req: PackageRequest) -> PackageResult:
    try:
        rec = ex.load_record(req.run_id, req.model_id)
        src = ex.model_path(req.run_id, req.model_id)
    except ex.ExperimentError as exc:
        raise DeployError(str(exc)) from None
    if rec.family == "flaml":
        raise DeployError("FLAML models are not bundled (needs repo classes); use an sklearn model")
    out = deploy_root() / req.run_id / req.model_id
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, out / "model.joblib")
    (out / "model_record.json").write_text(rec.model_dump_json(indent=2), encoding="utf-8")
    (out / "app.py").write_text(APP_TEMPLATE, encoding="utf-8")
    (out / "Dockerfile").write_text(DOCKERFILE, encoding="utf-8")
    (out / "docker-compose.yml").write_text(COMPOSE, encoding="utf-8")
    (out / "requirements.txt").write_text(
        _pin(["scikit-learn", "pandas", "numpy", "joblib", "fastapi", "uvicorn", "pydantic"]),
        encoding="utf-8",
    )
    (out / "model_card.md").write_text(_card(rec), encoding="utf-8")
    try:
        df, _ = load_frame(rec.data_path, 5, 0)
        sample = (
            df[rec.features].head(3).astype(object).where(df[rec.features].head(3).notna(), None)
        )
        example = {"rows": json.loads(sample.to_json(orient="records"))}
    except (GuardError, KeyError, OSError):
        example = {"rows": []}
    (out / "example_request.json").write_text(json.dumps(example, indent=1), encoding="utf-8")
    sha = hashlib.sha256((out / "model.joblib").read_bytes()).hexdigest()
    (out / "manifest.json").write_text(
        json.dumps({"model_id": rec.model_id, "model_sha256": sha}, indent=1), encoding="utf-8"
    )
    return PackageResult(
        bundle_dir=str(out), files=sorted(p.name for p in out.iterdir()), model_sha256=sha
    )


def _smoke(bundle: Path) -> bool:
    """Import the generated app from the bundle and call /predict on the bundled example."""
    from fastapi.testclient import TestClient

    example = json.loads((bundle / "example_request.json").read_text(encoding="utf-8"))
    if not example["rows"]:
        return False
    spec = importlib.util.spec_from_file_location(f"bundle_app_{bundle.name}", bundle / "app.py")
    if spec is None or spec.loader is None:
        return False
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
        client = TestClient(mod.app)
        health = client.get("/health").status_code == 200
        r = client.post("/predict", json=example)
        n = len(r.json().get("predictions", [])) if r.status_code == 200 else -1
        return bool(health and n == len(example["rows"]))
    finally:
        sys.modules.pop(spec.name, None)


def deploy_local(req: DeployRequest, approvals: ApprovalStore | None) -> DeployResult:
    if approvals is None:
        raise DeployError("approvals are not configured; deploy refused")
    bundle = deploy_root() / req.run_id / req.model_id
    if not (bundle / "manifest.json").exists():
        raise DeployError("package the model before deploying")
    payload: dict[str, Any] = {"model_id": req.model_id}
    try:
        approvals.consume(req.approval_token, "deploy", req.run_id, payload)
    except ApprovalError as exc:
        raise DeployError(f"approval refused: {exc}") from None
    ok = _smoke(bundle)
    cmd = f"docker compose -f {bundle / 'docker-compose.yml'} up -d --build"
    (bundle / "deployed.json").write_text(
        json.dumps(
            {"status": "staged", "smoke_ok": ok, "command": cmd, "containers_started": False}
        ),
        encoding="utf-8",
    )
    return DeployResult(
        status="staged", bundle_dir=str(bundle), smoke_ok=ok, command=cmd, containers_started=False
    )


def example_frame(bundle: Path) -> pd.DataFrame:
    return pd.DataFrame(json.loads((bundle / "example_request.json").read_text("utf-8"))["rows"])
