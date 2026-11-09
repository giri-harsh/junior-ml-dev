"""Live-E2B helpers: budget-gated backend + the sandbox latency measurement.

Every sandbox creation is reserved through scripts/budget.py (kind `e2b`, run cap 60). Nothing
here runs without E2B_API_KEY; with no key `main()` exits 0 after printing a one-line skip and
writes nothing (no number is ever produced without a real run).

    python -m harness.sandbox.e2b_live            # >= 20 execs -> benchmarks/results/e2b_v1.json
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from harness.sandbox.backends import E2BBackend, ExecResult

LATENCY_N = 20
LATENCY_CODE = "print(sum(range(1000)))\nopen('out_latency.txt', 'w').write('ok')\n"
_HERE = Path(__file__).resolve()


class BudgetDenied(RuntimeError):
    """scripts/budget.py refused the reservation (or the helper is missing): nothing was run."""


def _budget_script() -> Path | None:
    for root in (_HERE.parents[2], *_main_checkout()):
        cand = root / "scripts" / "budget.py"
        if cand.exists():
            return cand
    return None


def _main_checkout() -> list[Path]:
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True, cwd=_HERE.parent,
        ).stdout.strip()  # fmt: skip
    except (OSError, subprocess.CalledProcessError):
        return []
    return [Path(common).parent]


def _budget(*args: str) -> int:
    script = _budget_script()
    if script is None:
        return 1
    p = subprocess.run(
        [sys.executable, str(script), *args], capture_output=True, text=True, cwd=_HERE.parent
    )
    return p.returncode


def reserve(n: int) -> bool:
    return _budget("reserve", "e2b", str(n)) == 0


def commit(actual: int, reserved: int) -> None:
    _budget("commit", "e2b", str(actual), str(reserved))


class BudgetedE2B(E2BBackend):
    """E2BBackend that reserves one creation from the shared ledger before each exec."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.creations = 0

    def run_python(self, code: str, timeout_s: float, files: dict[str, bytes]) -> ExecResult:
        if not reserve(1):
            raise BudgetDenied("e2b budget denied (scripts/budget.py reserve e2b 1)")
        self.creations += 1
        return super().run_python(code, timeout_s, files)


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile (q in 0..100) of a non-empty list."""
    s = sorted(values)
    return s[max(0, math.ceil(q / 100 * len(s)) - 1)]


def measure_latency(backend: E2BBackend, n: int = LATENCY_N) -> dict[str, Any]:
    totals: list[float] = []
    stages: dict[str, list[float]] = {}
    failures = 0
    for _ in range(n):
        try:
            r = backend.run_python(LATENCY_CODE, 30, {})
        except BudgetDenied:
            raise
        except Exception:  # noqa: BLE001 - a failed exec is counted, never hidden
            failures += 1
            continue
        if r.exit_code != 0 or "out_latency.txt" not in r.files:
            failures += 1
            continue
        totals.append(r.duration_s)
        for k, v in backend.last_timings.items():
            stages.setdefault(k, []).append(v)
    if not totals:
        raise RuntimeError(f"all {n} live execs failed: no latency to report")

    def pq(xs: list[float]) -> dict[str, float]:
        return {"p50": percentile(xs, 50), "p95": percentile(xs, 95), "max": max(xs)}

    return {
        "n_requested": n,
        "n_ok": len(totals),
        "n_failed": failures,
        "total_s": pq(totals),
        "stages_s": {k: pq(v) for k, v in stages.items()},
    }


def main() -> int:
    if not os.environ.get("E2B_API_KEY"):
        print("E2B_API_KEY not set: live latency measurement NOT RUN, nothing written")
        return 0
    from benchmarks.results_writer import Conditions, write_result

    if not reserve(LATENCY_N):
        print("e2b budget denied: latency measurement deferred, nothing written")
        return 1
    be = E2BBackend()
    try:
        res = measure_latency(be, LATENCY_N)
    finally:
        commit(LATENCY_N, LATENCY_N)  # conservative: every attempt may have created a sandbox
    cond = Conditions(
        llm="none", sandbox="e2b", n=res["n_ok"],
        notes="fresh sandbox per exec, no internet; total_s = create+upload+exec+download "
        "(kill is in stages_s)",
    )  # fmt: skip
    path = write_result("e2b_v1", res, cond, command="python -m harness.sandbox.e2b_live")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
