"""real_dev: real tabular datasets DISJOINT from the 10 benchmark tasks (real_heldout).

Used to tune and adjudicate leakage precision. Cached under data/real_dev with a manifest
(name, source, ids, shape, content hash). Failures are listed under `exclusions`, never silent.

Usage: python -m benchmarks.real_dev
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn import datasets as skd

from apps.scorer.splits import frame_sha256
from benchmarks.tasks.registry import load_registry

ROOT = Path("data/real_dev")
OPENML = [
    "diabetes",
    "kc1",
    "phoneme",
    "spambase",
    "ilpd",
    "banknote-authentication",
    "qsar-biodeg",
    "wdbc",
    "steel-plates-fault",
    "car",
    "kin8nm",
    "cholesterol",
    "pol",
]
MAX_ROWS = 20_000


def _sk(loader: Callable[..., Any], name: str) -> tuple[pd.DataFrame, str, dict[str, Any]]:
    b = loader(as_frame=True)
    df = b.frame.copy()
    target = b.target.name if hasattr(b.target, "name") and b.target.name else df.columns[-1]
    return df, str(target), {"source": "sklearn", "name": name}


def _openml(name: str) -> tuple[pd.DataFrame, str, dict[str, Any]]:
    b = skd.fetch_openml(name=name, as_frame=True, parser="liac-arff")
    df = b.frame.copy()
    targets = list(b.target_names or [])
    if len(targets) != 1:
        raise ValueError(f"{name}: need exactly one default target, got {targets}")
    d = b.details
    return (
        df,
        targets[0],
        {
            "source": "openml",
            "dataset_id": d.get("id"),
            "version": d.get("version"),
            "licence": d.get("licence", "unknown"),
        },
    )


def _california() -> tuple[pd.DataFrame, str, dict[str, Any]]:
    b = skd.fetch_california_housing(as_frame=True)
    return b.frame.copy(), "MedHouseVal", {"source": "sklearn-download", "name": "california"}


SKLEARN: dict[str, Callable[[], tuple[pd.DataFrame, str, dict[str, Any]]]] = {
    "sk_wine": lambda: _sk(skd.load_wine, "wine"),
    "sk_diabetes_reg": lambda: _sk(skd.load_diabetes, "diabetes"),
    "sk_california": _california,
}


def build(refresh: bool = False) -> dict[str, Any]:
    ROOT.mkdir(parents=True, exist_ok=True)
    heldout = {t.name for t in load_registry()}
    manifest: dict[str, Any] = {"datasets": {}, "exclusions": []}
    jobs: list[tuple[str, Callable[[], tuple[pd.DataFrame, str, dict[str, Any]]]]] = []
    for n in OPENML:
        if n in heldout:
            manifest["exclusions"].append({"name": n, "reason": "collides with real_heldout"})
            continue
        jobs.append((n, lambda n=n: _openml(n)))  # type: ignore[misc]
    jobs += list(SKLEARN.items())
    for name, fn in jobs:
        path = ROOT / f"{name}.parquet"
        try:
            if path.exists() and not refresh:
                df = pd.read_parquet(path)
                meta = json.loads((ROOT / f"{name}.meta.json").read_text())
                target = meta["target"]
            else:
                df, target, meta = fn()
                if len(df) > MAX_ROWS:
                    df = df.sample(n=MAX_ROWS, random_state=0).sort_index().reset_index(drop=True)
                df.columns = [str(c) for c in df.columns]
                for c in df.columns:  # parquet needs plain dtypes
                    if isinstance(df[c].dtype, pd.CategoricalDtype):
                        df[c] = df[c].astype(object)
                meta = {**meta, "target": target}
                df.to_parquet(path, index=False)
                (ROOT / f"{name}.meta.json").write_text(json.dumps(meta, default=str, indent=2))
            manifest["datasets"][name] = {
                **meta,
                "n_rows": len(df),
                "n_cols": df.shape[1],
                "sha256": frame_sha256(df),
            }
        except Exception as exc:
            manifest["exclusions"].append({"name": name, "reason": f"{type(exc).__name__}: {exc}"})
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str))
    return manifest


def load_all() -> dict[str, tuple[pd.DataFrame, str]]:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    out = {}
    for name, meta in manifest["datasets"].items():
        out[name] = (pd.read_parquet(ROOT / f"{name}.parquet"), meta["target"])
    return out


def main() -> int:
    m = build()
    for k, v in m["datasets"].items():
        print(f"{k:28s} {v['source']:16s} {v['n_rows']:>6} x {v['n_cols']}")
    print("exclusions:", m["exclusions"])
    print("count:", len(m["datasets"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
