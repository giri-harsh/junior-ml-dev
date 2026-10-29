"""Screen a candidate partition for degenerate tasks using TRAIN-side CV only (no test rows, no
scorer, no FLAML): dummy vs HGB on a <=6000-row sample of the training file, 3-fold CV.

A task is degenerate when |hgb - dummy| < 5 * 1e-3 * max(|dummy|, 1) (five times the margin at
which `normalized_score` becomes undefined) or HGB is not better than dummy. Run BEFORE the freeze.
Usage: python -m benchmarks.screen_partition v5
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from apps.scorer.metrics import HIGHER_IS_BETTER
from benchmarks.results_writer import Conditions, write_result
from benchmarks.tasks.registry import partition

SAMPLE = 6000
MARGIN = 5e-3


def screen(name: str) -> dict[str, Any]:
    from mcp_servers.experiments import service as ex

    out: dict[str, Any] = {}
    for spec in partition(name):
        df = pd.read_parquet(Path("data/tasks") / spec.name / "train.parquet")
        if len(df) > SAMPLE:
            df = df.sample(SAMPLE, random_state=0)
        path = Path("data/screen") / f"{spec.name}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path)
        scores = {}
        for fam in ("dummy", "hgb"):
            req = ex.TrainRequest(
                data_path=str(path), target=spec.target, task_type=spec.task_type,
                metric=spec.metric, run_id=f"screen-{spec.name[:40]}", family=fam,
                selection="cv",
            )  # fmt: skip
            scores[fam] = ex.train_model(req).val_score
        sign = 1.0 if HIGHER_IS_BETTER[spec.metric] else -1.0
        lift = sign * (scores["hgb"] - scores["dummy"])
        ok = lift > 0 and lift >= MARGIN * max(abs(scores["dummy"]), 1.0)
        out[spec.name] = {
            "metric": spec.metric,
            "n_train": len(df),
            **scores,
            "lift": lift,
            "ok": ok,
        }
        print(
            f"{spec.name:28s} dummy={scores['dummy']:.4f} hgb={scores['hgb']:.4f} ok={ok}",
            flush=True,
        )
    return out


def main(argv: list[str] | None = None) -> int:
    name = (argv or sys.argv[1:] or ["v5"])[0]
    os.environ["EXPERIMENTS_DIR"] = tempfile.mkdtemp(prefix="screen-")
    res = screen(name)
    write_result(
        f"screen_{name}", res,
        Conditions(llm="none", sandbox="none", n=len(res), notes="TRAIN-side CV screen only"),
    )  # fmt: skip
    return 0 if all(r["ok"] for r in res.values()) else 3


if __name__ == "__main__":
    sys.exit(main())
