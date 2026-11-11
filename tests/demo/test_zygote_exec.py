"""The warm fork-server executor, exercised against a fake zygote script (no fork needed)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from apps.api.demo.service import DemoJob
from apps.api.demo.zygote_exec import ZygoteExecutor
from harness.agent.models import RunBudget, RunConfig, RunTask

FAKE = r"""
import json, sys, time
print("ready imports_s=0.5", flush=True)
mode = sys.argv[1]
for line in sys.stdin:
    job = json.loads(open(line.strip(), encoding="utf-8").read())
    print("started 4242", flush=True)
    if mode == "ok":
        open(job["run_dir"] + "/result.json", "w", encoding="utf-8").write(json.dumps({"status": "done", "v": 1}))
        print("done 4242 0", flush=True)
    elif mode == "crash":
        print("done 4242 1", flush=True)
    elif mode == "hang":
        time.sleep(30)
    elif mode == "die":
        sys.exit(3)
"""


def _job(tmp: Path, run_id: str, wall: float = 20.0) -> DemoJob:
    task = RunTask(name="t", data_path=str(tmp / "d.csv"), target="y", task_type="binary",
                   metric="roc_auc")  # fmt: skip
    cfg = RunConfig(run_id=run_id, task=task, budget=RunBudget(flaml_budget_s=0, tune_trials=1))
    return DemoJob(run_id, tmp / "runs" / run_id, cfg, wall, 0.0, tmp)


def _exec(tmp: Path, mode: str, kill: list[int] | None = None) -> ZygoteExecutor:
    script = tmp / "fake_zygote.py"
    script.write_text(FAKE, encoding="utf-8")
    return ZygoteExecutor(
        [sys.executable, str(script), mode], ready_timeout_s=30,
        kill=(lambda pid: kill.append(pid)) if kill is not None else (lambda pid: None),
    )  # fmt: skip


def test_runs_two_jobs_in_the_same_warm_worker(tmp_path: Path) -> None:
    ex = _exec(tmp_path, "ok")
    try:
        ex.warm()
        first = ex(_job(tmp_path, "r1"))
        second = ex(_job(tmp_path, "r2"))
        assert first.status == "done" and first.result["v"] == 1 and second.status == "done"
        assert ex.imports_s == 0.5  # parsed from the ready line, paid once
        spec = json.loads((tmp_path / "runs" / "r1" / "job.json").read_text(encoding="utf-8"))
        assert spec["data_dir"] == str(tmp_path.resolve()) and spec["run_dir"].endswith("r1")
    finally:
        ex.close()


def test_hung_job_is_killed_at_the_wall_clock(tmp_path: Path) -> None:
    killed: list[int] = []
    ex = _exec(tmp_path, "hang", killed)
    try:
        out = ex(_job(tmp_path, "r1", wall=1.0))
        assert out.status == "timeout" and "wall limit" in out.error
        assert killed == [4242]  # the forked child's own pid, not the worker's
    finally:
        ex.close()


def test_nonzero_exit_and_worker_death_are_failures_not_hangs(tmp_path: Path) -> None:
    crash = _exec(tmp_path, "crash")
    try:
        out = crash(_job(tmp_path, "r1"))
        assert out.status == "failed" and "exit 1" in out.error
    finally:
        crash.close()
    die = _exec(tmp_path, "die")
    try:
        out = die(_job(tmp_path, "r2"))
        assert out.status == "failed" and "worker exited" in out.error
    finally:
        die.close()


def test_warm_up_job_is_a_valid_demo_job_that_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.demo import runner, zygote

    for kind in ("binary", "regression"):
        job = zygote._warm_job(tmp_path, kind)
        spec = json.loads(job.read_text(encoding="utf-8"))
        assert spec["flaml_s"] == 0.0 and spec["config"]["planner"] == "scripted"
        monkeypatch.setenv("DATA_TOOLS_ROOTS", str(Path(spec["data_dir"]).resolve()))
        monkeypatch.setenv("EXPERIMENTS_DIR", str((job.parent / "exp").resolve()))
        monkeypatch.setenv("TRAJECTORY_DIR", str((job.parent / "traj").resolve()))
        out = runner.execute(job)
        assert out["status"] in {"done", "budget_exhausted"}, out
        assert (job.parent / "current.json").is_file()  # the in-flight marker is written


def test_warm_up_is_skipped_where_fork_does_not_exist() -> None:
    from apps.api.demo import zygote

    if sys.platform == "win32":
        assert zygote.warm_up(1.0) == 0.0
    src = Path(zygote.__file__).read_text(encoding="utf-8")
    assert "DEMO_ZYGOTE_WARMUP" in src and "warm_s=" in src
