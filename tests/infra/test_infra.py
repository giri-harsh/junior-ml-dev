"""Real-service tests. NOT RUN on the development machine (no Docker/Postgres/Redis/MinIO).

Run: `python scripts/tasks.py up app` then `python scripts/tasks.py test-infra`.
Each test skips when its service is unreachable (see conftest.py).
"""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from harness.agent.models import Step, StepRecord
from harness.agent.sql_store import SqlRunStore
from tests.unit.test_agent_runner import cfg_for, make_csv
from tests.unit.test_agent_runner import env as env  # noqa: F401

pytestmark = pytest.mark.infra
COMPOSE = ["-f", "deploy/compose/docker-compose.yml", "--profile", "app"]


def _compose(docker: str, *args: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [docker, "compose", *COMPOSE, *args], capture_output=True, text=True, timeout=timeout
    )


def test_postgres_run_store_contract(pg_url: str) -> None:
    store = SqlRunStore(pg_url)
    rid = f"infra-{uuid.uuid4().hex[:8]}"
    cfg = cfg_for(Path("x.csv"), run_id=rid)
    assert store.create(cfg) and not store.create(cfg)
    for i in (1, 0):
        rec = StepRecord(
            idx=i, step=Step(tool="profile_dataset"), ok=True, result={}, latency_s=0.1
        )
        store.checkpoint(rid, rec, {"n": i})
    assert [r.idx for r, _ in store.checkpoints(rid)] == [0, 1]
    store.set_status(rid, "done", {"ok": True})
    assert store.status(rid) == "done" and store.result(rid) == {"ok": True}


def test_arq_worker_executes_an_agent_run_into_postgres(
    pg_url: str,
    redis_url: str,
    env: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    import asyncio

    pytest.importorskip("arq")
    from arq.worker import Worker

    from harness.queue_arq import ArqJobQueue, WorkerSettings

    monkeypatch.setenv("RUNS_DATABASE_URL", pg_url)
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("AUDIT_DB", str(tmp_path / "audit.db"))
    rid = f"infra-{uuid.uuid4().hex[:8]}"
    cfg = cfg_for(make_csv(env), run_id=rid)
    ArqJobQueue().enqueue(rid, {"config": cfg.model_dump(mode="json")})

    async def drain() -> None:
        w = Worker(
            functions=WorkerSettings.functions, redis_settings=WorkerSettings.redis_settings,
            burst=True, poll_delay=0.2,
        )  # fmt: skip
        await w.main()
        await w.close()

    asyncio.run(drain())
    assert SqlRunStore(pg_url).status(rid) == "done"


def test_minio_object_store_roundtrip(minio_endpoint: str, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("minio")
    import os

    from apps.api.minio_store import MinioObjectStore

    monkeypatch.setenv("MINIO_ENDPOINT", minio_endpoint)
    monkeypatch.setenv("MINIO_ROOT_USER", os.environ.get("MINIO_ROOT_USER", "jmdminio"))
    monkeypatch.setenv(
        "MINIO_ROOT_PASSWORD", os.environ.get("MINIO_ROOT_PASSWORD", "change-me-locally")
    )
    store = MinioObjectStore(bucket=f"jmd-test-{uuid.uuid4().hex[:6]}")
    did = uuid.uuid4().hex[:16]
    assert not store.exists(did) and store.get_blob(did, "data.bin") is None
    store.put_blob(did, "data.bin", b"abc")
    store.put_json(did, "meta.json", {"k": 1})
    assert store.get_blob(did, "data.bin") == b"abc" and store.get_json(did, "meta.json") == {
        "k": 1
    }
    assert store.exists(did)


SUBMIT = """
import numpy as np
import pandas as pd
from apps.api.routes import runs
from harness.agent.models import RunBudget, RunConfig, RunTask

r = np.random.default_rng(0)
a = r.normal(size=3000)
pd.DataFrame({"a": a, "b": r.normal(size=3000), "y": (a > 0).astype(int)}).to_parquet(
    "/app/data/infra.parquet"
)
cfg = RunConfig(
    run_id="infra-kill",
    task=RunTask(name="t", data_path="/app/data/infra.parquet", target="y",
                 task_type="binary", metric="roc_auc"),
    budget=RunBudget(flaml_budget_s=20),
)
print(runs.job_queue().enqueue("infra-kill", {"config": cfg.model_dump(mode="json")}))
"""

REFERENCE = """
import json
from harness.agent.models import RunBudget, RunConfig, RunTask
from harness.agent.planners import ScriptedPlanner
from harness.agent.runner import AgentRunner
from harness.agent.store import RunStore

cfg = RunConfig(
    run_id="infra-ref",
    task=RunTask(name="t", data_path="/app/data/infra.parquet", target="y",
                 task_type="binary", metric="roc_auc"),
    budget=RunBudget(flaml_budget_s=20),
)
res = AgentRunner(RunStore("/tmp/ref.db"), ScriptedPlanner(), run_root="/tmp/refruns").run(cfg)
print("RESULT " + json.dumps({k: res[k] for k in ("chosen_family", "val_score", "n_steps")}))
"""


def _exec(docker: str, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [docker, "compose", *COMPOSE, "exec", "-T", "api", "python", "-"],
        input=script, capture_output=True, text=True, timeout=900,
    )  # fmt: skip


@pytest.mark.compose
def test_killed_worker_container_resumes_without_repeating_steps(docker_bin: str) -> None:
    """docker kill the worker mid-run, restart it, then compare with an uninterrupted run."""
    up = _compose(docker_bin, "up", "-d", "--wait", timeout=1200)
    assert up.returncode == 0, up.stdout[-800:] + up.stderr[-800:]
    try:
        sub = _exec(docker_bin, SUBMIT)
        assert sub.returncode == 0, sub.stderr[-800:]
        from tests.infra.conftest import PG_URL

        store = SqlRunStore(PG_URL)  # compose publishes postgres on localhost:5432
        deadline = time.time() + 180
        while time.time() < deadline and len(store.checkpoints("infra-kill")) < 4:
            time.sleep(1)
        before = len(store.checkpoints("infra-kill"))
        assert before >= 4, "worker never started the run"
        subprocess.run([docker_bin, "kill", "jmd-worker-1"], check=True, capture_output=True)
        assert store.status("infra-kill") == "running"  # killed mid-run, not finished
        _compose(docker_bin, "start", "worker")
        deadline = time.time() + 900  # arq re-delivers once the dead worker's key expires (30 s)
        while time.time() < deadline and store.status("infra-kill") != "done":
            time.sleep(5)
        logs = _compose(docker_bin, "logs", "--tail", "40", "worker").stdout
        assert store.status("infra-kill") == "done", logs
        cps = [r for r, _ in store.checkpoints("infra-kill")]
        assert [r.idx for r in cps] == list(range(len(cps))) and len(cps) > before
        keys = [(r.step.tool, json.dumps(r.step.args, sort_keys=True)) for r in cps]
        assert len(keys) == len(set(keys)), "a step ran twice"
        ref = _exec(docker_bin, REFERENCE)
        assert ref.returncode == 0, ref.stderr[-800:]
        want = json.loads(ref.stdout.split("RESULT ", 1)[1])
        got = store.result("infra-kill") or {}
        assert got["chosen_family"] == want["chosen_family"]
        assert got["val_score"] == want["val_score"]
    finally:
        _compose(docker_bin, "down")  # keep volumes


def test_generated_predict_service_container_matches_in_process_predictions(
    docker_bin: str,
    env: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    import urllib.request

    from mcp_servers.deploy import service as dp
    from mcp_servers.experiments import service as ex

    monkeypatch.setenv("DEPLOY_DIR", str(tmp_path / "deploy"))
    monkeypatch.setenv("EXPERIMENTS_DIR", str(tmp_path / "exp"))
    csv = make_csv(env)
    rec = ex.train_model(
        ex.TrainRequest(
            data_path=str(csv),
            target="y",
            task_type="binary",
            metric="roc_auc",
            run_id="r1",
            family="rf",
        )  # fmt: skip
    )
    bundle = Path(
        dp.package_model(dp.PackageRequest(run_id="r1", model_id=rec.model_id)).bundle_dir
    )
    tag = f"jmd-bundle-test-{uuid.uuid4().hex[:6]}"
    build = subprocess.run(
        [docker_bin, "build", "-t", tag, str(bundle)], capture_output=True, text=True, timeout=900
    )
    assert build.returncode == 0, build.stderr[-800:]
    cid = subprocess.run(
        [docker_bin, "run", "-d", "-p", "18000:8000", tag], capture_output=True, text=True
    ).stdout.strip()
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen("http://127.0.0.1:18000/health", timeout=2)
                break
            except OSError:
                time.sleep(1)
        rows = json.loads((bundle / "example_request.json").read_text())
        req = urllib.request.Request(
            "http://127.0.0.1:18000/predict", json.dumps(rows).encode(),
            {"Content-Type": "application/json"},
        )  # fmt: skip
        got = json.loads(urllib.request.urlopen(req, timeout=10).read())["predictions"]
        import pandas as pd

        feats = env / "f.csv"
        pd.DataFrame(rows["rows"]).to_csv(feats, index=False)
        want = pd.read_csv(
            ex.predict(
                ex.PredictRequest(run_id="r1", model_id=rec.model_id, features_path=str(feats))
            ).out_path
        )["pred"].tolist()
        assert got == pytest.approx(want)
    finally:
        subprocess.run([docker_bin, "rm", "-f", cid], capture_output=True)
        subprocess.run([docker_bin, "rmi", "-f", tag], capture_output=True)
