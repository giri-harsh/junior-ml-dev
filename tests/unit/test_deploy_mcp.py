"""Smoke test: deploy tools through the official MCP client over stdio."""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]


async def _calls(tmp: Path) -> tuple[list[str], bool]:
    env = {**os.environ, "DEPLOY_DIR": str(tmp), "PYTHONPATH": str(ROOT), "APPROVAL_SECRET": ""}
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "mcp_servers.deploy.server"], env=env, cwd=str(ROOT)
    )
    async with AsyncExitStack() as stack:
        errlog = stack.enter_context(open(os.devnull, "w"))  # noqa: SIM115
        read, write = await stack.enter_async_context(stdio_client(params, errlog=errlog))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        tools = sorted(t.name for t in (await session.list_tools()).tools)
        res = await session.call_tool(
            "deploy_local",
            {"request": {"run_id": "r", "model_id": "m", "approval_token": "x" * 20}},
        )
    return tools, bool(res.is_error)


def test_deploy_tools_and_refusal_without_approvals(tmp_path: Path) -> None:
    tools, refused = asyncio.run(_calls(tmp_path))
    assert tools == ["deploy_local", "package_model"] and refused
