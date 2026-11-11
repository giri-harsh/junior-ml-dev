"""Warm fork server for the demo's run processes (POSIX only): `python -m apps.api.demo.zygote`.

On a throttled CPU (Render free: 0.1 vCPU) importing pandas, scikit-learn and lightgbm takes about
45 s, which is most of the 60 s a run is allowed. This process pays that cost once at boot, then
forks one child per job (copy-on-write, no re-import). Protocol on stdin/stdout, one line each:

    ready imports_s=<s> warm_s=<s>   printed once the imports and the warm-up run are done
    <job.json path>            (stdin) run this job in a forked child, one at a time
    started <pid>              the child's pid (its own session, so the web process can kill it)
    done <pid> <exit code>     the child finished or was killed (-9)
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import sys
import tempfile
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


WARM_BUDGET_S = 150.0


def _warm_job(root: Path, kind: str) -> Path:
    """A tiny job on synthetic data, run once at boot so a fresh container pays its one-time
    costs (cold disk reads of lazily imported code, first-call setup) before any visitor does."""
    import numpy as np
    import pandas as pd

    from harness.agent.models import RunBudget, RunConfig, RunTask

    rng = np.random.default_rng(0)
    n = 300
    df = pd.DataFrame(
        {"a": rng.normal(size=n), "b": rng.normal(size=n), "c": rng.choice(["u", "v", "w"], n)}
    )
    binary = kind == "binary"
    df["y"] = (
        (df["a"] + rng.normal(scale=0.5, size=n) > 0).astype(int)
        if binary
        else (df["a"] * 2 + df["b"])
    )
    d = root / kind
    run_dir = d / "run"
    run_dir.mkdir(parents=True)
    data = d / "warm.csv"
    df.to_csv(data, index=False)
    cfg = RunConfig(
        run_id=f"warm-{kind}",
        task=RunTask(
            name="warm", data_path=str(data), target="y",
            task_type="binary" if binary else "regression", metric="roc_auc" if binary else "rmse",
        ),
        budget=RunBudget(
            max_steps=20, max_wall_s=30, max_tokens=0, flaml_budget_s=0, tune_trials=1,
            step_retries=0, selection="cv",
        ),
        planner="scripted", llm_mode="none", deploy=False, sandbox_features=False, mode="dev",
    )  # fmt: skip
    job = run_dir / "job.json"
    job.write_text(
        json.dumps(
            {"config": cfg.model_dump(mode="json"), "run_dir": str(run_dir), "max_wall_s": 60.0,
             "flaml_s": 0.0, "data_dir": str(d)}
        ),
        encoding="utf-8",
    )  # fmt: skip
    return job


def warm_up(budget_s: float = WARM_BUDGET_S) -> float:
    """Run the warm-up jobs in forked children (killed if they overrun); return seconds spent."""
    if sys.platform == "win32":
        return 0.0
    t0 = time.time()
    root = Path(tempfile.mkdtemp(prefix="jmd-warm-"))
    try:
        for kind in ("binary", "regression"):
            left = budget_s - (time.time() - t0)
            if left <= 0:
                break
            job = _warm_job(root, kind)
            pid = os.fork()
            if pid == 0:
                os.setsid()
                os._exit(_run_child(job))
            deadline = time.time() + left
            while time.time() < deadline:
                done, _ = os.waitpid(pid, os.WNOHANG)
                if done:
                    break
                time.sleep(0.2)
            else:
                with contextlib.suppress(OSError):
                    os.killpg(pid, signal.SIGKILL)
                    os.waitpid(pid, 0)
        data_dir = Path(os.environ.get("DEMO_DATA_DIR", "data/demo/samples"))
        for csv in sorted(data_dir.glob("*.csv")):  # pull the samples into the page cache
            with contextlib.suppress(OSError):
                csv.read_bytes()
    except Exception:  # noqa: BLE001  (a failed warm-up must never stop the worker)
        traceback.print_exc(file=sys.stderr)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return time.time() - t0


def main() -> int:
    if sys.platform == "win32":
        print("the fork server needs a POSIX system", file=sys.stderr)
        return 2
    imports_s = time.time() - _T0
    warm_s = warm_up() if os.environ.get("DEMO_ZYGOTE_WARMUP", "1") != "0" else 0.0
    print(f"ready imports_s={imports_s:.1f} warm_s={warm_s:.1f}", flush=True)
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
