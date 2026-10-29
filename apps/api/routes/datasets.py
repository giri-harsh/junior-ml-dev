"""Dataset upload, profile and Quality Scorecard endpoints (PRD S4).

The profile job runs as a FastAPI background task; the arq worker replaces it in the harness
sprint (STUB noted in docs/KNOWN_GAPS.md). Object storage is local; MinIO is a STUB.
"""

from __future__ import annotations

import hashlib
import io
import os
from datetime import date
from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile

from apps.api.store import DATASET_ID, LocalObjectStore, ObjectStore
from datastory.models import DatasetProfile
from datastory.pii import scan_pii
from datastory.profile import profile_frame
from datastory.quality import QualityReport, quality_report
from leakage.detectors import detect
from leakage.models import DetectionMeta
from trajectory.emit import emit
from trajectory.models import EventKind

MAX_BYTES = 50 * 1024 * 1024
ALLOWED = {".csv": "csv", ".parquet": "parquet"}
PARSE_ROW_CAP = 200_000

router = APIRouter(prefix="/v1/datasets", tags=["datasets"])
_store: ObjectStore | None = None


def get_store() -> ObjectStore:
    global _store
    if _store is None:
        if os.environ.get("OBJECT_STORE") == "minio":
            from apps.api.minio_store import MinioObjectStore

            _store = MinioObjectStore()
        else:
            _store = LocalObjectStore()
    return _store


def set_store(store: ObjectStore | None) -> None:
    global _store
    _store = store


def _read_frame(data: bytes, kind: str) -> pd.DataFrame:
    buf = io.BytesIO(data)
    df = pd.read_parquet(buf) if kind == "parquet" else pd.read_csv(buf, nrows=PARSE_ROW_CAP)
    df.columns = [str(c) for c in df.columns]
    return df


def process_dataset(dataset_id: str) -> None:
    """Profile job: parse, scan for PII, cache profile. Updates status in meta.json."""
    store = get_store()
    meta = store.get_json(dataset_id, "meta.json") or {}
    try:
        blob = store.get_blob(dataset_id, "data.bin")
        assert blob is not None
        df = _read_frame(blob, meta["kind"])
        prof = profile_frame(df)
        meta.update(
            status="ready",
            n_rows=len(df),
            n_cols=int(df.shape[1]),
            pii_flags=scan_pii(df),
        )
        store.put_json(dataset_id, "profile.json", prof.model_dump(mode="json"))
        emit(dataset_id, EventKind.PIPELINE_STEP, {"stage": "profile", "rows": len(df)})
    except Exception as exc:
        meta.update(status="failed", error=type(exc).__name__)
    store.put_json(dataset_id, "meta.json", meta)


@router.post("", status_code=202)
async def upload_dataset(
    background: BackgroundTasks, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    name = file.filename or ""
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED:
        raise HTTPException(415, "only .csv and .parquet files are accepted")
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"file larger than {MAX_BYTES // (1024 * 1024)} MB")
    if not data:
        raise HTTPException(422, "empty file")
    digest = hashlib.sha256(data).hexdigest()
    dataset_id = digest[:16]
    store = get_store()
    if not store.exists(dataset_id):
        store.put_blob(dataset_id, "data.bin", data)
        store.put_json(
            dataset_id,
            "meta.json",
            {
                "filename": name.replace("\\", "/").rsplit("/", 1)[-1][:128],
                "kind": ALLOWED[ext],
                "size": len(data),
                "sha256": digest,
                "status": "processing",
            },
        )
        background.add_task(process_dataset, dataset_id)
    return {"dataset_id": dataset_id, "sha256": digest, "size": len(data)}


def _meta(dataset_id: str) -> dict[str, Any]:
    if not DATASET_ID.match(dataset_id):
        raise HTTPException(404, "unknown dataset")
    meta = get_store().get_json(dataset_id, "meta.json")
    if meta is None:
        raise HTTPException(404, "unknown dataset")
    return meta


@router.get("/{dataset_id}/status")
def dataset_status(dataset_id: str) -> dict[str, Any]:
    m = _meta(dataset_id)
    return {k: m.get(k) for k in ("status", "filename", "n_rows", "n_cols", "pii_flags", "error")}


@router.get("/{dataset_id}/profile", response_model=DatasetProfile)
def dataset_profile(dataset_id: str) -> DatasetProfile:
    m = _meta(dataset_id)
    if m.get("status") != "ready":
        raise HTTPException(409, f"dataset status is {m.get('status')}")
    raw = get_store().get_json(dataset_id, "profile.json")
    assert raw is not None
    return DatasetProfile.model_validate(raw)


@router.get("/{dataset_id}/quality", response_model=QualityReport)
def dataset_quality(
    dataset_id: str,
    target: str | None = Query(default=None, max_length=256),
    as_of: date | None = None,
    with_leakage: bool = False,
) -> QualityReport:
    m = _meta(dataset_id)
    if m.get("status") != "ready":
        raise HTTPException(409, f"dataset status is {m.get('status')}")
    store = get_store()
    blob = store.get_blob(dataset_id, "data.bin")
    assert blob is not None
    df = _read_frame(blob, m["kind"])
    findings = None
    if with_leakage:
        if target is None or target not in df.columns:
            raise HTTPException(422, "with_leakage needs a valid target column")
        findings = detect(df, target, DetectionMeta(seed=0))
    return quality_report(df, findings, as_of)
