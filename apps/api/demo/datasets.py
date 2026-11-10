"""What the picker, the live page and the report say about each bundled dataset.

Everything here is fixed text written by us; the only data read from disk is the first rows of
the verified sample CSV (plain `csv`, so the light web process never imports pandas). The bytes
that `/datasets/<key>.csv` serves are the very file `samples.sample_path` hands to the pipeline.
"""

from __future__ import annotations

import csv
import functools
from pathlib import Path
from typing import Any

from apps.api.demo.samples import BY_KEY, SAMPLES, load_manifest, sample_path

PREVIEW_ROWS = 5

# raw column -> reader-friendly name. A column not listed falls back to its raw name.
LABELS: dict[str, dict[str, str]] = {
    "diabetes": {
        "preg": "Pregnancies",
        "plas": "Plasma glucose",
        "pres": "Blood pressure",
        "skin": "Skin-fold thickness",
        "insu": "Insulin",
        "mass": "BMI",
        "pedi": "Family history score",
        "age": "Age",
        "diabetes": "Has diabetes",
    },
    "credit-g": {
        "checking_status": "Checking account",
        "duration": "Loan duration (months)",
        "credit_history": "Credit history",
        "purpose": "Loan purpose",
        "credit_amount": "Loan amount",
        "savings_status": "Savings",
        "employment": "Years employed",
        "installment_commitment": "Instalment rate",
        "personal_status": "Personal status",
        "other_parties": "Co-applicants / guarantors",
        "residence_since": "Years at residence",
        "property_magnitude": "Property",
        "age": "Age",
        "other_payment_plans": "Other payment plans",
        "housing": "Housing",
        "existing_credits": "Existing credits",
        "job": "Job",
        "num_dependents": "Dependents",
        "own_telephone": "Has telephone",
        "foreign_worker": "Foreign worker",
        "bad_credit": "Bad credit",
    },
    "wine-quality": {
        "fixed_acidity": "Fixed acidity",
        "volatile_acidity": "Volatile acidity",
        "citric_acid": "Citric acid",
        "residual_sugar": "Residual sugar",
        "chlorides": "Chlorides",
        "free_sulfur_dioxide": "Free sulfur dioxide",
        "total_sulfur_dioxide": "Total sulfur dioxide",
        "density": "Density",
        "pH": "pH",
        "sulphates": "Sulphates",
        "alcohol": "Alcohol",
        "quality": "Quality score",
    },
}

# plain-English card text, and the wording of the result sentence
INFO: dict[str, dict[str, str]] = {
    "diabetes": {
        "name": "Pima diabetes",
        "predicts": "Whether a patient tests positive for diabetes, from 8 clinical measurements.",
        "pair": "one diabetic and one healthy patient",
        "unit": "",
    },
    "credit-g": {
        "name": "German credit risk",
        "predicts": "Whether a loan applicant turns out to be a bad credit risk.",
        "pair": "one applicant who defaulted and one who repaid",
        "unit": "",
    },
    "wine-quality": {
        "name": "Red wine quality",
        "predicts": "The sensory quality score (about 3 to 8) of a red wine, from lab tests.",
        "pair": "",
        "unit": "points of the quality score",
    },
}


def label(sample_key: str, column: str) -> str:
    """Readable name for a column of a bundled sample (raw name when none is defined)."""
    return LABELS.get(sample_key, {}).get(column, column.replace("_", " "))


def openml_url(openml_id: int) -> str:
    return f"https://www.openml.org/d/{int(openml_id)}"


@functools.lru_cache(maxsize=16)
def _preview(path: str, sha: str, n: int) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    del sha  # part of the cache key only: a changed file is re-read
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        head = tuple(next(reader, []))
        rows = []
        for row in reader:
            rows.append(tuple(row))
            if len(rows) >= n:
                break
    return head, tuple(rows)


def catalog(data_dir: Path) -> list[dict[str, Any]]:
    """One entry per sample present on disk: card text, sizes, source, hash and a 5-row preview."""
    have = load_manifest(data_dir)
    out: list[dict[str, Any]] = []
    for s in SAMPLES:
        e = have.get(s.key)
        if e is None:
            continue
        try:
            path = sample_path(data_dir, s.key)
        except (KeyError, ValueError):
            continue  # a tampered or vanished file is not offered
        head, rows = _preview(str(path), e["sha256"], PREVIEW_ROWS)
        info = INFO[s.key]
        out.append(
            {
                "key": s.key, "title": s.title, "name": info["name"], "blurb": s.blurb,
                "predicts": info["predicts"], "target": s.target,
                "target_label": label(s.key, s.target),
                "task_type": s.task_type,
                "task_kind": "regression" if s.task_type == "regression" else "classification",
                "metric": s.metric, "rows": e.get("rows"), "cols": e.get("cols"),
                "bytes": e.get("bytes"), "sha256": e["sha256"], "sha12": e["sha256"][:12],
                "openml_id": s.openml_id, "openml_url": openml_url(s.openml_id),
                "download": f"/datasets/{s.key}.csv",
                "preview": {
                    "columns": [{"raw": c, "label": label(s.key, c)} for c in head],
                    "rows": [list(r) for r in rows],
                },
            }
        )  # fmt: skip
    return out


def download_path(data_dir: Path, key: str) -> Path:
    """The verified bytes of a sample. KeyError for unknown keys, ValueError if tampered."""
    if key not in BY_KEY:
        raise KeyError(key)
    return sample_path(data_dir, key)
