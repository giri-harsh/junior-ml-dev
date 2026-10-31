"""Image build step: fetch the bundled samples and render the landing page.

    python -m apps.api.demo.prepare --data-dir data/demo/samples --site-dir data/demo/site \
        --metrics docs/METRICS.md

Network access is needed only for the sample fetch (OpenML through scikit-learn). `--skip-fetch`
renders the landing page alone; `--from-dir DIR` copies CSVs named `<key>.csv` instead of fetching
(used by tests and for offline builds). Large binaries are never committed: the CSVs are produced
here, inside the image build.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from apps.api.demo.landing import build_landing
from apps.api.demo.samples import (
    MAX_SAMPLE_BYTES,
    SAMPLES,
    Sample,
    manifest_json,
    sha256_file,
)

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = ROOT / "apps" / "web" / "demo" / "landing.template.html"


def shape_frame(df: pd.DataFrame, s: Sample) -> pd.DataFrame:
    """Rename the target and turn a binary label into 0/1. Pure; unit-tested on tiny frames."""
    df = df.rename(columns=dict(s.rename)).reset_index(drop=True)
    if s.target not in df.columns:
        raise ValueError(f"{s.key}: target column {s.target!r} missing after rename")
    if s.task_type == "binary":
        if s.binary_positive is None:
            raise ValueError(f"{s.key}: binary sample needs binary_positive")
        df[s.target] = (df[s.target].astype(str) == s.binary_positive).astype(int)
    for c in df.columns:
        if isinstance(df[c].dtype, pd.CategoricalDtype):
            df[c] = df[c].astype(str)
    return df


def _fetch(s: Sample, cache: Path) -> pd.DataFrame:
    from sklearn.datasets import fetch_openml

    # liac-arff: the default pandas parser fails on some OpenML files under pandas 3.
    bunch = fetch_openml(
        data_id=s.openml_id, as_frame=True, parser="liac-arff", data_home=str(cache)
    )
    frame: pd.DataFrame = bunch.frame
    return frame


def write_sample(df: pd.DataFrame, s: Sample, data_dir: Path) -> dict[str, Any]:
    out = data_dir / f"{s.key}.csv"
    df.to_csv(out, index=False)
    size = out.stat().st_size
    if size > MAX_SAMPLE_BYTES:
        out.unlink()
        raise ValueError(f"{s.key}: {size} bytes exceeds the {MAX_SAMPLE_BYTES} byte cap")
    return {
        "key": s.key, "rows": int(len(df)), "cols": int(df.shape[1]), "bytes": size,
        "sha256": sha256_file(out), "openml_id": s.openml_id,
    }  # fmt: skip


def prepare_samples(
    data_dir: Path, *, from_dir: Path | None = None, cache: Path | None = None
) -> list[dict[str, Any]]:
    data_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for s in SAMPLES:
        if from_dir is not None:
            src = from_dir / f"{s.key}.csv"
            if not src.is_file():
                continue
            df = pd.read_csv(src)
        else:
            df = _fetch(s, cache or data_dir.parent / "_openml_cache")
        entries.append(write_sample(shape_frame(df, s), s, data_dir))
    (data_dir / "manifest.json").write_text(manifest_json(entries), encoding="utf-8")
    return entries


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("--data-dir", type=Path, default=Path("data/demo/samples"))
    ap.add_argument("--site-dir", type=Path, default=Path("data/demo/site"))
    ap.add_argument("--metrics", type=Path, default=ROOT / "docs" / "METRICS.md")
    ap.add_argument("--from-dir", type=Path, default=None)
    ap.add_argument("--skip-fetch", action="store_true")
    ns = ap.parse_args(argv)
    if not ns.skip_fetch:
        entries = prepare_samples(ns.data_dir, from_dir=ns.from_dir)
        for e in entries:
            print(f"sample {e['key']}: {e['rows']}x{e['cols']} {e['bytes']} bytes")
        if not entries:
            print("no samples prepared", file=sys.stderr)
            return 1
    out = build_landing(ns.metrics, TEMPLATE, ns.site_dir)
    print(f"landing page: {out}")
    shutil.rmtree(ns.data_dir.parent / "_openml_cache", ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
