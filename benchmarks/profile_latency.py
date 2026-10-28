"""Measure profile + quality time on a seeded 100k x 50 synthetic frame (PRD S4 acceptance <= 10 s).

Usage: python -m benchmarks.profile_latency [--repeats 3]
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import pandas as pd

from benchmarks.results_writer import Conditions, write_result
from datastory.profile import profile_frame
from datastory.quality import quality_report

ROWS, COLS = 100_000, 50


def make_frame(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data: dict[str, object] = {}
    for i in range(COLS):
        kind = i % 5
        if kind in (0, 1):
            data[f"num_{i}"] = rng.normal(size=ROWS)
        elif kind == 2:
            data[f"int_{i}"] = rng.integers(0, 1000, ROWS)
        elif kind == 3:
            data[f"cat_{i}"] = rng.choice([f"v{j}" for j in range(20)], ROWS)
        else:
            data[f"flag_{i}"] = rng.integers(0, 2, ROWS)
    df = pd.DataFrame(data)
    df["target"] = rng.integers(0, 2, ROWS)
    df.loc[rng.random(ROWS) < 0.05, "num_0"] = np.nan
    return df


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repeats", type=int, default=3)
    a = p.parse_args(argv)
    df = make_frame()
    times = []
    for _ in range(a.repeats):
        t0 = time.perf_counter()
        profile_frame(df, "target")
        quality_report(df)
        times.append(time.perf_counter() - t0)
    res = {
        "rows": ROWS,
        "cols": COLS + 1,
        "seconds_each_run": [round(t, 2) for t in times],
        "seconds_median": round(float(np.median(times)), 2),
        "budget_seconds": 10,
        "within_budget": bool(np.median(times) <= 10),
    }
    path = write_result(
        "profile_latency_v0",
        res,
        Conditions(
            llm="none", sandbox="none", n=a.repeats, notes="synthetic frame, reference machine"
        ),
        command="python -m benchmarks.profile_latency " + " ".join(argv or sys.argv[1:]),
    )
    print(res, path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
