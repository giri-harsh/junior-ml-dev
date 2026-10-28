"""Dev-only tuning view for leakage thresholds. Refuses to touch the eval partition.

Usage: python -m benchmarks.tune_leakage [--verbose]
Prints per-type recall and twin false alarms on `dev` (variants 0-2). Edit leakage/thresholds.yaml
by hand between runs (max 3 iterations per bug type), then freeze.
"""

from __future__ import annotations

import argparse
import json
import sys

from leakage.evaluate import run_partition

PARTITION = "dev"  # hard-coded on purpose: there is no flag to select eval


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--verbose", action="store_true")
    a = p.parse_args(argv)
    res = run_partition(PARTITION)
    s = res["summary"]
    for bt, v in s["by_bug_type"].items():
        print(f"{bt:16s} recall {v['hits']}/{v['n']} column_hit={v['column_hit_rate']}")
    print(f"twin false alarms: {s['twin_false_alarm_n']}/{s['n_variants']}")
    if a.verbose:
        for r in res["rows"]:
            print(
                json.dumps(
                    {k: r[k] for k in ("variant_id", "hit", "bugged_families", "twin_findings")}
                )
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
