"""Fetch benchmark datasets: OpenML -> sklearn built-in -> synthetic. Records licence per dataset.

Usage: python -m benchmarks.fetch --all | --task NAME [--synthetic]
Raw files land in data/tasks/_raw/<name>.parquet; splits are written by `--all` too.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from sklearn.datasets import fetch_openml, make_classification, make_regression

from apps.scorer.splits import write_split
from benchmarks.tasks.registry import (
    TaskSpec,
    get_task,
    load_registry,
    load_registry_v3,
    load_registry_v4,
)

DATA_ROOT = Path("data/tasks")
SCORER_ROOT = Path("scorer_data")
RAW = DATA_ROOT / "_raw"


def _openml(spec: TaskSpec) -> tuple[pd.DataFrame, dict[str, object]]:
    b = fetch_openml(name=spec.name, as_frame=True, parser="liac-arff")
    df = b.frame.copy()
    if spec.target not in df.columns:
        raise KeyError(f"{spec.name}: target {spec.target!r} not in {list(df.columns)}")
    d = b.details
    meta = {
        "origin": "openml",
        "dataset_id": d.get("id"),
        "version": d.get("version"),
        "licence": d.get("licence", "unknown"),
    }
    return df, meta


def synthetic(spec: TaskSpec, n: int = 2000) -> tuple[pd.DataFrame, dict[str, object]]:
    seed = sum(map(ord, spec.name))
    if spec.task_type == "regression":
        x, y = make_regression(n, 10, n_informative=6, noise=10.0, random_state=seed)
    else:
        classes = 3 if spec.task_type == "multiclass" else 2
        weights = [0.9, 0.1] if spec.imbalanced and classes == 2 else None
        x, y = make_classification(
            n, 10, n_informative=6, n_classes=classes, weights=weights, random_state=seed
        )
    df = pd.DataFrame(x, columns=[f"f{i}" for i in range(x.shape[1])])
    df[spec.target] = y if spec.task_type == "regression" else y.astype(str)
    return df, {"origin": "synthetic", "dataset_id": None, "licence": "CC0 (generated)"}


def fetch_one(spec: TaskSpec, force_synthetic: bool = False) -> dict[str, object]:
    if force_synthetic:
        df, meta = synthetic(spec)
    else:
        try:
            df, meta = _openml(spec)
        except Exception as exc:  # network, missing name, schema drift: fall back, never block
            print(
                f"[{spec.name}] openml failed ({type(exc).__name__}: {exc}); synthetic",
                file=sys.stderr,
            )
            df, meta = synthetic(spec)
            meta["fallback_reason"] = f"{type(exc).__name__}"
    RAW.mkdir(parents=True, exist_ok=True)
    df.to_parquet(RAW / f"{spec.name}.parquet", index=False)
    manifest = write_split(df, spec, DATA_ROOT, SCORER_ROOT)
    (DATA_ROOT / spec.name / "source.json").write_text(json.dumps(meta, indent=2, default=str))
    return {**meta, **manifest}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--all", action="store_true")
    p.add_argument("--task")
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--v3", action="store_true", help="fetch the v3 partition")
    p.add_argument("--v4", action="store_true", help="fetch the v4 partition")
    a = p.parse_args(argv)
    specs = (
        load_registry_v4()
        if a.v4
        else load_registry_v3()
        if a.v3
        else load_registry()
        if a.all
        else [get_task(a.task)]
        if a.task
        else []
    )
    if not specs:
        p.error("need --all or --task")
    for s in specs:
        info = fetch_one(s, a.synthetic)
        print(
            f"{s.name:36s} {info['origin']:10s} n_train={info['n_train']} n_test={info['n_test']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
