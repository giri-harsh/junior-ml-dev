from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from harness.agent.planners import ScriptedPlanner
from harness.agent.runner import AgentRunner
from harness.agent.store import RunStore
from harness.security.approvals import ApprovalStore
from harness.security.audit import AuditLog
from mcp_servers.deploy import service as dp
from mcp_servers.experiments import service as ex
from tests.unit.test_agent_runner import cfg_for, make_csv
from tests.unit.test_agent_runner import env as env  # noqa: F401


@pytest.fixture(autouse=True)
def _deploy_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEPLOY_DIR", str(tmp_path / "deploy"))
    assert dp.deploy_root() == tmp_path / "deploy"


def _trained(env: Path, family: str = "hgb") -> ex.ModelRecord:  # noqa: F811
    csv = make_csv(env)
    return ex.train_model(
        ex.TrainRequest(
            data_path=str(csv), target="y", task_type="binary", metric="roc_auc",
            run_id="r1", family=family,  # type: ignore[arg-type]
        )
    )  # fmt: skip


def test_package_builds_a_working_bundle(env: Path) -> None:  # noqa: F811
    rec = _trained(env)
    res = dp.package_model(dp.PackageRequest(run_id="r1", model_id=rec.model_id))
    assert {"app.py", "Dockerfile", "docker-compose.yml", "model_card.md", "model.joblib"} <= set(
        res.files
    )
    assert "scikit-learn==" in (Path(res.bundle_dir) / "requirements.txt").read_text()
    assert dp._smoke(Path(res.bundle_dir)) is True


def test_bundle_service_matches_in_repo_predictions(env: Path) -> None:  # noqa: F811
    rec = _trained(env, "rf")
    res = dp.package_model(dp.PackageRequest(run_id="r1", model_id=rec.model_id))
    import importlib.util

    from fastapi.testclient import TestClient

    bundle = Path(res.bundle_dir)
    spec = importlib.util.spec_from_file_location("bundle_x", bundle / "app.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    client = TestClient(mod.app)
    rows = json.loads((bundle / "example_request.json").read_text())
    got = client.post("/predict", json=rows).json()["predictions"]
    model = ex._load_model("r1", rec.model_id)
    import pandas as pd

    df = pd.DataFrame(rows["rows"])[rec.features]
    for c in rec.cat_features:
        df[c] = df[c].astype(object).map(lambda v: None if pd.isna(v) else str(v))
    want = model.predict_proba(df)[:, list(model.classes_).index(rec.positive_label)]
    assert got == pytest.approx(want.tolist())
    assert client.post("/predict", json={"rows": []}).status_code == 422
    assert client.post("/predict", json={"rows": [{"a": 1}]}).status_code == 422


def test_flaml_and_unknown_models_are_refused(env: Path) -> None:  # noqa: F811
    with pytest.raises(dp.DeployError, match="unknown model"):
        dp.package_model(dp.PackageRequest(run_id="r1", model_id="nope"))
    with pytest.raises(ValidationError):
        dp.PackageRequest(run_id="../x", model_id="m")


def test_deploy_needs_a_single_use_bound_token(env: Path, tmp_path: Path) -> None:  # noqa: F811
    rec = _trained(env)
    dp.package_model(dp.PackageRequest(run_id="r1", model_id=rec.model_id))
    store = ApprovalStore(tmp_path / "a.db", "secret-for-tests")

    def tok(model_id: str) -> str:
        return store.approve(store.request("deploy", "r1", {"model_id": model_id}))

    def req(t: str) -> dp.DeployRequest:
        return dp.DeployRequest(run_id="r1", model_id=rec.model_id, approval_token=t)

    with pytest.raises(dp.DeployError, match="not configured"):
        dp.deploy_local(req("x" * 20), None)
    with pytest.raises(dp.DeployError, match="refused"):
        dp.deploy_local(req(tok("some-other-model")), store)  # bound to another payload
    good = tok(rec.model_id)
    res = dp.deploy_local(req(good), store)
    assert res.status == "staged" and res.smoke_ok and not res.containers_started
    with pytest.raises(dp.DeployError, match="already used"):
        dp.deploy_local(req(good), store)


def test_deploy_before_package_is_refused(env: Path, tmp_path: Path) -> None:  # noqa: F811
    rec = _trained(env)
    store = ApprovalStore(tmp_path / "a.db", "secret-for-tests")
    t = store.approve(store.request("deploy", "r1", {"model_id": rec.model_id}))
    with pytest.raises(dp.DeployError, match="package"):
        dp.deploy_local(
            dp.DeployRequest(run_id="r1", model_id=rec.model_id, approval_token=t), store
        )


def test_agent_pauses_for_approval_then_resumes_and_deploys(env: Path, tmp_path: Path) -> None:  # noqa: F811
    csv = make_csv(env)
    cfg = cfg_for(csv, run_id="dep1", deploy=True, mode="test")
    approvals = ApprovalStore(tmp_path / "a.db", "secret-for-tests")
    audit = AuditLog(tmp_path / "audit.db")
    db = tmp_path / "runs.db"

    def mk(token: str | None) -> AgentRunner:
        return AgentRunner(
            RunStore(db), ScriptedPlanner(), run_root=tmp_path / "runs",
            audit=audit, approvals=approvals, approval_token=token,
        )  # fmt: skip

    first = mk(None).run(cfg)
    assert first["status"] == "awaiting_approval" and first["pending_approval"]
    again = mk(None).run(cfg)  # no token yet: same request is reused, not duplicated
    assert again["pending_approval"]["approval_id"] == first["pending_approval"]["approval_id"]
    token = approvals.approve(first["pending_approval"]["approval_id"])
    final = mk(token).run(cfg)
    assert final["status"] == "done" and final["resumed"] and not final["failures"]
    manifest = json.loads(
        (tmp_path / "deploy" / "dep1" / final["final_model_id"] / "deployed.json").read_text()
    )
    assert manifest["smoke_ok"] is True and manifest["containers_started"] is False
    actions = [e["action"] for e in audit.entries()]
    assert "approval_requested" in actions and "preseeded_approval_used" in actions
    assert audit.verify_chain() == (True, None)
    # the token is spent: a second run of the same shape cannot reuse it
    cfg2 = cfg_for(csv, run_id="dep2", deploy=True, mode="test")
    stolen = AgentRunner(
        RunStore(tmp_path / "runs2.db"), ScriptedPlanner(), run_root=tmp_path / "runs2",
        audit=audit, approvals=approvals, approval_token=token,
    ).run(cfg2)  # fmt: skip
    assert any("blocked:approval_invalid" in v for v in stolen["failures"].values())


def test_deploy_without_approval_store_is_a_recorded_failure_not_a_crash(
    env: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    cfg = cfg_for(make_csv(env), run_id="dep3", deploy=True, mode="test")
    res = AgentRunner(RunStore(tmp_path / "r.db"), ScriptedPlanner(), run_root=tmp_path / "r").run(
        cfg
    )
    assert res["status"] == "done"
    assert any("approval_required" in v for v in res["failures"].values())


def test_flaml_model_bundle_predicts_identically_in_a_fresh_process(
    env: Path, tmp_path: Path
) -> None:  # noqa: F811
    import subprocess
    import sys

    import pandas as pd

    csv = make_csv(env)
    rec = ex.train_model(
        ex.TrainRequest(
            data_path=str(csv),
            target="y",
            task_type="binary",
            metric="roc_auc",
            run_id="r1",
            family="flaml",
            time_budget_s=3,
        )  # fmt: skip
    )
    full = ex.refit_full(ex.RefitRequest(run_id="r1", model_id=rec.model_id))
    res = dp.package_model(dp.PackageRequest(run_id="r1", model_id=full.model_id))
    bundle = Path(res.bundle_dir)
    reqs = (bundle / "requirements.txt").read_text()
    assert all(f"{p}==" in reqs for p in ("flaml", "lightgbm", "xgboost"))
    feats = pd.read_csv(csv).drop(columns=["y"]).head(20)
    feats_path = env / "twenty.csv"
    feats.to_csv(feats_path, index=False)
    want = pd.read_csv(
        ex.predict(
            ex.PredictRequest(run_id="r1", model_id=full.model_id, features_path=str(feats_path))
        ).out_path
    )["pred"].to_numpy()
    rows = tmp_path / "rows.json"
    rows.write_text(json.dumps({"rows": json.loads(feats.to_json(orient="records"))}))
    out = tmp_path / "got.json"
    script = (
        "import importlib.util, json, sys\n"
        "from fastapi.testclient import TestClient\n"
        f"spec = importlib.util.spec_from_file_location('b', r'{bundle / 'app.py'}')\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        f"r = TestClient(m.app).post('/predict', json=json.load(open(r'{rows}')))\n"
        f"json.dump(r.json(), open(r'{out}', 'w'))\n"
    )
    proc = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-600:]
    got = json.loads(out.read_text())["predictions"]
    assert len(got) == 20 and got == pytest.approx(want.tolist())
