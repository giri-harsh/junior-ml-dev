"""Every tool of every MCP server, called once over stdio with fixture data, plus the generated
docs staying in sync with the live schemas. Uses a real subprocess per server (the wire path)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]


async def _session(
    module: str, env: dict[str, str], calls: list[tuple[str, dict[str, Any]]]
) -> dict[str, Any]:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", module],
        env={**os.environ, "PYTHONPATH": str(ROOT), **env},
        cwd=str(ROOT),
    )
    out: dict[str, Any] = {}
    async with AsyncExitStack() as stack:
        errlog = stack.enter_context(open(os.devnull, "w"))  # noqa: SIM115
        read, write = await stack.enter_async_context(stdio_client(params, errlog=errlog))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        out["_tools"] = sorted(t.name for t in (await session.list_tools()).tools)
        for name, args in calls:
            out[name] = await session.call_tool(name, args)
    return out


def _data(tmp: Path) -> tuple[Path, Path]:
    root = tmp / "data"
    root.mkdir()
    rng = np.random.default_rng(0)
    a = rng.normal(size=300)
    df = pd.DataFrame(
        {"a": a, "b": rng.normal(size=300), "y": (a + rng.normal(size=300) > 0).astype(int)}
    )
    p = root / "d.csv"
    df.to_csv(p, index=False)
    return root, p


def test_data_tools_every_tool(tmp_path: Path) -> None:
    root, csv = _data(tmp_path)
    req = {"request": {"path": str(csv), "target": "y", "run_id": "all"}}
    res = asyncio.run(
        _session(
            "mcp_servers.data_tools.server",
            {"DATA_TOOLS_ROOTS": str(root), "TRAJECTORY_DIR": str(tmp_path / "traj")},
            [("profile_dataset", req), ("detect_leakage", req), ("data_story", req)],
        )
    )
    assert res["_tools"] == ["data_story", "detect_leakage", "profile_dataset"]
    assert all(not res[t].is_error for t in res["_tools"])


def test_sandbox_exec_every_tool(tmp_path: Path) -> None:
    res = asyncio.run(
        _session(
            "mcp_servers.sandbox_exec.server",
            {"JMD_SANDBOX": "local-unsafe"},
            [
                ("check_policy", {"request": {"code": "print(1 + 1)"}}),
                ("install_allowed", {"request": {"package": "numpy"}}),
                ("run_python", {"request": {"code": "print(6 * 7)", "timeout_s": 20}}),
            ],
        )
    )
    assert res["_tools"] == ["check_policy", "install_allowed", "run_python"]
    assert all(not res[t].is_error for t in res["_tools"])
    assert "42" in str(res["run_python"].content)


def test_experiments_every_tool(tmp_path: Path) -> None:
    root, csv = _data(tmp_path)
    base = {
        "data_path": str(csv),
        "target": "y",
        "task_type": "binary",
        "metric": "roc_auc",
        "run_id": "all",
    }
    from mcp_servers.experiments import service as ex  # model ids are deterministic

    train_req = ex.TrainRequest(**base, family="linear")  # type: ignore[arg-type]
    mid = ex._model_id("linear", train_req.model_dump_json())
    feats = tmp_path / "data" / "f.csv"
    pd.read_csv(csv).drop(columns=["y"]).to_csv(feats, index=False)
    res = asyncio.run(
        _session(
            "mcp_servers.experiments.server",
            {"DATA_TOOLS_ROOTS": str(root), "EXPERIMENTS_DIR": str(tmp_path / "exp")},
            [
                ("train_model", {"request": {**base, "family": "linear"}}),
                (
                    "tune_model",
                    {"request": {**base, "family": "hgb", "n_trials": 1, "time_budget_s": 20}},
                ),
                ("refit_full", {"request": {"run_id": "all", "model_id": mid}}),
                (
                    "evaluate_model",
                    {
                        "request": {
                            "run_id": "all",
                            "model_id": mid,
                            "data_path": str(csv),
                            "target": "y",
                        }
                    },
                ),
                (
                    "predict",
                    {"request": {"run_id": "all", "model_id": mid, "features_path": str(feats)}},
                ),
                ("compare_models", {"request": {"run_id": "all"}}),
                ("explain_model", {"request": {"run_id": "all", "model_id": mid, "n_repeats": 1}}),
            ],
        )
    )
    assert res["_tools"] == [
        "compare_models", "evaluate_model", "explain_model", "predict", "refit_full",
        "train_model", "tune_model",
    ]  # fmt: skip
    bad = {t: res[t].content for t in res["_tools"] if res[t].is_error}
    assert not bad, bad


def test_deploy_every_tool(tmp_path: Path) -> None:
    root, csv = _data(tmp_path)
    from mcp_servers.experiments import service as ex

    env = {
        "DATA_TOOLS_ROOTS": str(root), "EXPERIMENTS_DIR": str(tmp_path / "exp"),
        "DEPLOY_DIR": str(tmp_path / "deploy"), "APPROVAL_SECRET": "",
    }  # fmt: skip
    os.environ.update(
        DATA_TOOLS_ROOTS=env["DATA_TOOLS_ROOTS"], EXPERIMENTS_DIR=env["EXPERIMENTS_DIR"]
    )
    try:
        rec = ex.train_model(
            ex.TrainRequest(
                data_path=str(csv),
                target="y",
                task_type="binary",
                metric="roc_auc",
                run_id="dep",
                family="linear",
            )  # fmt: skip
        )
    finally:
        os.environ.pop("DATA_TOOLS_ROOTS", None)
        os.environ.pop("EXPERIMENTS_DIR", None)
    res = asyncio.run(
        _session(
            "mcp_servers.deploy.server",
            env,
            [
                ("package_model", {"request": {"run_id": "dep", "model_id": rec.model_id}}),
                (
                    "deploy_local",
                    {
                        "request": {
                            "run_id": "dep",
                            "model_id": rec.model_id,
                            "approval_token": "x" * 20,
                        }
                    },
                ),
            ],
        )
    )
    assert res["_tools"] == ["deploy_local", "package_model"]
    assert not res["package_model"].is_error
    assert res["deploy_local"].is_error  # no approval configured: refused, which is the contract


@pytest.mark.timeout(120)
def test_generated_mcp_docs_are_current() -> None:
    p = subprocess.run(
        [sys.executable, "scripts/gen_mcp_docs.py", "--check"],
        cwd=ROOT, capture_output=True, text=True, env={**os.environ, "JMD_SANDBOX": "local-unsafe"},
    )  # fmt: skip
    assert p.returncode == 0, p.stdout + p.stderr
