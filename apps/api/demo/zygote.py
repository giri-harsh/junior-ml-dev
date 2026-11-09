"""Warm fork server for the demo's run processes (POSIX only): `python -m apps.api.demo.zygote`.

On a throttled CPU (Render free: 0.1 vCPU) importing pandas, scikit-learn and lightgbm takes about
45 s, which is most of the 60 s a run is allowed. This process pays that cost once at boot, then
forks one child per job (copy-on-write, no re-import). Protocol on stdin/stdout, one line each:

    ready imports_s=<s>        printed once the heavy imports are done
    <job.json path>            (stdin) run this job in a forked child, one at a time
    started <pid>              the child's pid (its own session, so the web process can kill it)
    done <pid> <exit code>     the child finished or was killed (-9)
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

_T0 = time.time()

from apps.api.demo import runner  # noqa: E402  (heavy imports, once)


def _run_child(job_file: Path) -> int:
    run_dir = job_file.parent
    log = os.open(run_dir / "job.log", os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    os.dup2(log, 1)
    os.dup2(log, 2)
    try:
        job = json.loads(job_file.read_text(encoding="utf-8"))
        os.environ["DATA_TOOLS_ROOTS"] = str(Path(job["data_dir"]).resolve())
        os.environ["EXPERIMENTS_DIR"] = str((run_dir / "exp").resolve())
        os.environ["TRAJECTORY_DIR"] = str((run_dir / "traj").resolve())
        (run_dir / "timeline.json").write_text(
            json.dumps({"child_started": time.time(), "imports_s": 0.0, "forked": True}),
            encoding="utf-8",
        )
        runner.execute(job_file)
        return 0
    except BaseException:
        traceback.print_exc()
        return 1


def main() -> int:
    if sys.platform == "win32":
        print("the fork server needs a POSIX system", file=sys.stderr)
        return 2
    print(f"ready imports_s={time.time() - _T0:.1f}", flush=True)
    for line in sys.stdin:
        path = line.strip()
        if not path:
            continue
        pid = os.fork()
        if pid == 0:  # child: own session, so the whole tree can be killed
            os.setsid()
            os._exit(_run_child(Path(path)))
        print(f"started {pid}", flush=True)
        _, status = os.waitpid(pid, 0)
        print(f"done {pid} {os.waitstatus_to_exitcode(status)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
