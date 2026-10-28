"""Smoke test: every tool called through the official MCP client over stdio."""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]


def _write(root: Path) -> Path:
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"x": rng.normal(size=300), "target": rng.integers(0, 2, 300)})
    df["leak"] = df["target"]
    p = root / "d.csv"
    df.to_csv(p, index=False)
    return p


async def _session_calls(csv: Path, root: Path) -> dict[str, Any]:
    env = {
        **os.environ,
        "DATA_TOOLS_ROOTS": str(root),
        "TRAJECTORY_DIR": str(root / "traj"),
        "PYTHONPATH": str(ROOT),
    }
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "mcp_servers.data_tools.server"], env=env, cwd=str(ROOT)
    )
    out: dict[str, Any] = {}
    async with AsyncExitStack() as stack:
        errlog = stack.enter_context(open(os.devnull, "w"))  # noqa: SIM115
        read, write = await stack.enter_async_context(stdio_client(params, errlog=errlog))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        out["tools"] = sorted(t.name for t in (await session.list_tools()).tools)
        args = {"request": {"path": str(csv), "target": "target", "run_id": "smoke"}}
        for name in ("profile_dataset", "detect_leakage", "data_story"):
            out[name] = await session.call_tool(name, args)
        out["bad"] = await session.call_tool(
            "profile_dataset", {"request": {"path": str(root.parent / "nope.csv")}}
        )
        out["invalid"] = await session.call_tool(
            "profile_dataset", {"request": {"path": "", "max_rows": 1}}
        )
    return out


def test_all_tools_via_stdio_client(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    res = asyncio.run(asyncio.wait_for(_session_calls(_write(root), root), timeout=180))
    assert res["tools"] == ["data_story", "detect_leakage", "profile_dataset"]
    for name in ("profile_dataset", "detect_leakage", "data_story"):
        assert not res[name].is_error, res[name]
    leak = res["detect_leakage"].structured_content
    assert any(f["columns"] == ["leak"] for f in leak["findings"])
    assert res["data_story"].structured_content["markdown"].startswith("# Data Story")
    assert res["bad"].is_error and res["invalid"].is_error
