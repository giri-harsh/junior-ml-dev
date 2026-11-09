"""`python -m apps.api.demo.run_job <job.json>`: run one demo job in this process.

Writes `timeline.json` next to the job file as soon as the heavy imports are done, so the public
run status can say how long the child spent starting up (on a throttled CPU this is the largest
part of a short run).
"""

from __future__ import annotations

import contextlib
import json
import sys
import time
from pathlib import Path

_T0 = time.time()

from apps.api.demo.runner import main  # noqa: E402  (heavy: pandas, scikit-learn, lightgbm)


def _write_timeline(argv: list[str]) -> None:
    if len(argv) == 2:
        with contextlib.suppress(OSError):
            (Path(argv[1]).parent / "timeline.json").write_text(
                json.dumps({"child_started": _T0, "imports_s": round(time.time() - _T0, 1)}),
                encoding="utf-8",
            )


if __name__ == "__main__":
    _write_timeline(sys.argv)
    sys.exit(main(sys.argv))
