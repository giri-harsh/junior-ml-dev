"""The bundled demo samples: small public OpenML tables fetched at image build time.

`SAMPLES` is the manifest (what to fetch and how to run it). `prepare.fetch_all` writes the CSVs
and `manifest.json` (sha256 + size) into the data dir; the running app only ever reads that
directory and refuses a file whose hash no longer matches. Nothing here accepts user input.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MAX_SAMPLE_BYTES = 5 * 1024 * 1024
KEY = re.compile(r"^[a-z][a-z0-9\-]{1,31}$")


@dataclass(frozen=True)
class Sample:
    key: str
    title: str
    openml_id: int
    target: str
    task_type: str  # binary | multiclass | regression
    metric: str
    blurb: str
    rename: tuple[tuple[str, str], ...] = ()  # fetched column -> demo column
    binary_positive: str | None = None  # label that becomes 1 (binary tasks); others become 0


SAMPLES: tuple[Sample, ...] = (
    Sample(
        key="diabetes",
        title="Pima diabetes (OpenML 37)",
        openml_id=37,
        target="diabetes",
        task_type="binary",
        metric="roc_auc",
        blurb="768 patients, 8 numeric measurements, will they test positive for diabetes?",
        rename=(("class", "diabetes"),),
        binary_positive="tested_positive",
    ),
    Sample(
        key="credit-g",
        title="German credit (OpenML 31)",
        openml_id=31,
        target="bad_credit",
        task_type="binary",
        metric="roc_auc",
        blurb="1000 loan applicants, 20 mixed numeric and categorical columns, predict bad credit.",
        rename=(("class", "bad_credit"),),
        binary_positive="bad",
    ),
    Sample(
        key="wine-quality",
        title="Red wine quality (OpenML 40691)",
        openml_id=40691,
        target="quality",
        task_type="regression",
        metric="rmse",
        blurb="1599 wines, 11 physico-chemical measurements, predict the sensory quality score.",
        rename=(("class", "quality"),),
    ),
)
BY_KEY = {s.key: s for s in SAMPLES}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(data_dir: Path) -> dict[str, dict[str, Any]]:
    """Samples actually present on disk, keyed by sample key. Missing manifest -> empty."""
    mf = data_dir / "manifest.json"
    if not mf.is_file():
        return {}
    raw = json.loads(mf.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for entry in raw.get("samples", []):
        key = str(entry.get("key", ""))
        if KEY.match(key) and key in BY_KEY and (data_dir / f"{key}.csv").is_file():
            out[key] = entry
    return out


def sample_path(data_dir: Path, key: str) -> Path:
    """Verified path of a sample CSV. Raises KeyError for an unknown key, ValueError on tamper."""
    entry = load_manifest(data_dir).get(key)
    if entry is None:
        raise KeyError(key)
    path = (data_dir / f"{key}.csv").resolve()
    if path.parent != data_dir.resolve():
        raise ValueError("sample path escapes the data dir")
    if path.stat().st_size > MAX_SAMPLE_BYTES or sha256_file(path) != entry["sha256"]:
        raise ValueError(f"sample {key} does not match its manifest hash")
    return path


def public_info(data_dir: Path) -> list[dict[str, Any]]:
    """What the UI may show about each available sample."""
    have = load_manifest(data_dir)
    out = []
    for s in SAMPLES:
        if s.key in have:
            e = have[s.key]
            out.append(
                {
                    "key": s.key, "title": s.title, "blurb": s.blurb, "target": s.target,
                    "task_type": s.task_type, "metric": s.metric,
                    "rows": e.get("rows"), "cols": e.get("cols"), "bytes": e.get("bytes"),
                }
            )  # fmt: skip
    return out


def manifest_json(entries: list[dict[str, Any]]) -> str:
    return json.dumps({"samples": entries, "spec": [asdict(s) for s in SAMPLES]}, indent=1)
