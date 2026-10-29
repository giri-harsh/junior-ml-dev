"""Deploy-server adapters for the agent runner (registered by default)."""

from __future__ import annotations

from typing import Any

from harness.agent.tools import Reducer, Tool, ToolCtx
from mcp_servers.deploy import service as dp


def package_model(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    res = dp.package_model(dp.PackageRequest(run_id=ctx.cfg.run_id, model_id=args["model_id"]))
    return res.model_dump(mode="json")


def deploy_local(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    token = ctx.extra.get("token")
    if not token:
        raise dp.DeployError("no approval token")
    res = dp.deploy_local(
        dp.DeployRequest(run_id=ctx.cfg.run_id, model_id=args["model_id"], approval_token=token),
        ctx.extra.get("approvals"),
    )
    return res.model_dump(mode="json")


def _r_package(st: dict[str, Any], args: dict[str, Any], res: dict[str, Any]) -> None:
    st["bundle_dir"] = res["bundle_dir"]


def _r_deploy(st: dict[str, Any], args: dict[str, Any], res: dict[str, Any]) -> None:
    st["deployed"] = {"status": res["status"], "smoke_ok": res["smoke_ok"]}


REGISTRY: dict[str, tuple[Tool, Reducer]] = {
    "package_model": (package_model, _r_package),
    "deploy_local": (deploy_local, _r_deploy),
}
