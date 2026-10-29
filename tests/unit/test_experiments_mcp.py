"""Smoke test: experiments tools through the official MCP client over stdio."""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

import numpy as np
import pandas as pd
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]


async def _calls(csv: Path, root: Path) -> tuple[list[str], bool, bool]:
    env = {
        **os.environ,
        "DATA_TOOLS_ROOTS": str(root),
        "EXPERIMENTS_DIR": str(root.parent / "exp"),
        "PYTHONPATH": str(ROOT),
    }
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_servers.experiments.server"],
        env=env,
        cwd=str(ROOT),
    )
    async with AsyncExitStack() as stack:
        errlog = stack.enter_context(open(os.devnull, "w"))  # noqa: SIM115
        read, write = await stack.enter_async_context(stdio_client(params, errlog=errlog))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        tools = sorted(t.name for t in (await session.list_tools()).tools)
        ok = await session.call_tool(
            "train_model",
            {
                "request": {
                    "data_path": str(csv),
                    "target": "y",
                    "task_type": "binary",
                    "metric": "roc_auc",
                    "run_id": "smoke",
                    "family": "linear",
                }  # fmt: skip
            },
        )
        bad = await session.call_tool(
            "train_model",
            {"request": {"data_path": str(csv.parent.parent / "x.csv"), "target": "y"}},
        )
    return tools, not ok.is_error, bool(bad.is_error)


def test_tools_via_stdio_client(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    rng = np.random.default_rng(0)
    a = rng.normal(size=200)
    csv = root / "d.csv"
    pd.DataFrame({"a": a, "y": (a + rng.normal(size=200) > 0).astype(int)}).to_csv(csv, index=False)
    tools, ok, bad = asyncio.run(_calls(csv, root))
    assert tools == [
        "compare_models", "evaluate_model", "explain_model", "predict", "refit_full", "train_model", "tune_model",
    ]  # fmt: skip
    assert ok and bad
