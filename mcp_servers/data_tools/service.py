"""Core of the data-tools server: input guards plus the three tool implementations.

Kept free of MCP imports so it is unit-testable. Guards: path allowlist (scorer_data always
denied), extension allowlist, file-size cap, row cap with seeded sampling, cooperative timeout.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from datastory.models import DatasetProfile, SampleInfo, StoryResult
from datastory.profile import profile_frame
from datastory.story import build_story
from leakage.config import load_thresholds, thresholds_hash
from leakage.detectors import detect_with_status
from leakage.models import DetectionMeta, Finding, Severity
from trajectory.emit import emit
from trajectory.models import EventKind

MAX_FILE_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_ROWS = 50_000
ALLOWED_SUFFIXES = {".csv", ".parquet"}
DENIED_PARTS = {"scorer_data"}
AGENT_VERSION = "data-tools-0.1"

log = logging.getLogger("data_tools")


class GuardError(ValueError):
    """Input rejected by a guard. Message is safe to return to the caller."""


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"level": record.levelname, "msg": record.getMessage()}
        payload.update(getattr(record, "ctx", {}))
        return json.dumps(payload, default=str, sort_keys=True)


def configure_logging() -> None:
    if log.handlers:
        return
    h = logging.StreamHandler(sys.stderr)  # never stdout: stdio transport owns it
    h.setFormatter(_JsonFormatter())
    log.addHandler(h)
    log.setLevel(logging.INFO)
    log.propagate = False


def allowed_roots() -> list[Path]:
    raw = os.environ.get("DATA_TOOLS_ROOTS")
    roots = (
        [Path(p) for p in raw.split(os.pathsep) if p] if raw else [Path("data"), Path("benchmarks")]
    )
    return [r.resolve() for r in roots]


def resolve_path(path: str) -> Path:
    """Resolve to a real file under an allowed root; reject everything else."""
    if "\0" in path:
        raise GuardError("invalid path")
    try:
        real = Path(path).resolve(strict=True)
    except (OSError, RuntimeError):
        raise GuardError("file not found") from None
    if any(part.lower() in DENIED_PARTS for part in real.parts):
        raise GuardError("path is not accessible")
    if not any(real.is_relative_to(root) for root in allowed_roots()):
        raise GuardError("path outside allowed roots")
    if not real.is_file():
        raise GuardError("not a file")
    if real.suffix.lower() not in ALLOWED_SUFFIXES:
        raise GuardError(f"unsupported file type {real.suffix!r}; use csv or parquet")
    if real.stat().st_size > MAX_FILE_BYTES:
        raise GuardError(f"file larger than {MAX_FILE_BYTES // (1024 * 1024)} MB cap")
    return real


def load_frame(path: str, max_rows: int, seed: int) -> tuple[pd.DataFrame, SampleInfo]:
    real = resolve_path(path)
    try:
        df = pd.read_parquet(real) if real.suffix.lower() == ".parquet" else pd.read_csv(real)
    except Exception as exc:
        raise GuardError(f"could not parse file: {type(exc).__name__}") from None
    n_full = len(df)
    sampled = n_full > max_rows
    if sampled:
        df = df.sample(n=max_rows, random_state=seed).sort_index().reset_index(drop=True)
    return df, SampleInfo(n_full=n_full, n_used=len(df), sampled=sampled, seed=seed)


# --- request/response schemas -----------------------------------------------------------------
class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileRequest(_Base):
    path: str = Field(min_length=1, max_length=1024)
    target: str | None = Field(default=None, max_length=256)
    run_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    max_rows: int = Field(default=DEFAULT_MAX_ROWS, ge=100, le=200_000)
    seed: int = Field(default=0, ge=0, le=2**31 - 1)


class LeakageRequest(ProfileRequest):
    target: str = Field(min_length=1, max_length=256)
    time_budget_s: float = Field(default=60.0, gt=0, le=300)


class StoryRequest(LeakageRequest):
    pass


class LeakageResult(_Base):
    run_id: str
    target: str
    task_type: str
    findings: list[Finding]
    counts: dict[str, int]
    thresholds_sha256: str
    sample: SampleInfo
    partial: bool = False  # detection was bounded (sampled or a detector ran out of time)
    partial_reasons: list[str] = Field(default_factory=list)


class ProfileResult(_Base):
    run_id: str
    profile: DatasetProfile


def _run_id(req: ProfileRequest) -> str:
    return req.run_id or uuid.uuid4().hex[:12]


def _event(run_id: str, tool: str, payload: dict[str, Any]) -> None:
    log.info(tool, extra={"ctx": {"run_id": run_id, "tool": tool, **payload}})
    emit(run_id, EventKind.PIPELINE_STEP, {"tool": tool, **payload}, agent_version=AGENT_VERSION)


# --- tools -------------------------------------------------------------------------------------
def profile_dataset(req: ProfileRequest) -> ProfileResult:
    run_id = _run_id(req)
    df, sample = load_frame(req.path, req.max_rows, req.seed)
    if req.target is not None and req.target not in df.columns:
        raise GuardError(f"target {req.target!r} not in columns")
    prof = profile_frame(df, req.target, sample)
    _event(run_id, "profile_dataset", {"rows": sample.n_used, "cols": prof.n_cols})
    return ProfileResult(run_id=run_id, profile=prof)


def detect_leakage(req: LeakageRequest) -> LeakageResult:
    run_id = _run_id(req)
    df, sample = load_frame(req.path, req.max_rows, req.seed)
    if req.target not in df.columns:
        raise GuardError(f"target {req.target!r} not in columns")
    meta = DetectionMeta(seed=req.seed, time_budget_s=req.time_budget_s)
    findings, reasons = detect_with_status(df, req.target, meta, load_thresholds())
    counts = {s.value: sum(f.severity == s for f in findings) for s in Severity}
    from leakage.scoring import infer_task

    task = infer_task(df[req.target].dropna())
    _event(
        run_id, "detect_leakage", {"findings": len(findings), "partial": bool(reasons), **counts}
    )
    return LeakageResult(
        run_id=run_id,
        target=req.target,
        task_type=task,
        findings=findings,
        counts=counts,
        thresholds_sha256=thresholds_hash(),
        sample=sample,
        partial=bool(reasons),
        partial_reasons=reasons,
    )


def data_story(req: StoryRequest) -> StoryResult:
    run_id = _run_id(req)
    leak = detect_leakage(LeakageRequest(**{**req.model_dump(), "run_id": run_id}))
    df, sample = load_frame(req.path, req.max_rows, req.seed)
    prof = profile_frame(df, req.target, sample, task=leak.task_type)
    story = build_story(
        prof,
        leak.findings,
        {"run_id": run_id, "thresholds_sha256": leak.thresholds_sha256, "seed": req.seed},
    )

    # Generate charts (PRD S6) - new additive feature
    from datastory.story import build_charts

    # Create insights list from findings - charts don't need to link back to specific findings
    insights: list[dict[str, object]] = [
        {"type": f.type.value, "importance": float(f.confidence)} for f in leak.findings
    ]
    charts_data = build_charts(df, prof, insights, top_n=12)
    story.charts = charts_data

    n_charts = len(charts_data.get("gallery", [])) + len(charts_data.get("more_charts", []))
    _event(run_id, "data_story", {"markdown_chars": len(story.markdown), "charts": n_charts})
    return story
