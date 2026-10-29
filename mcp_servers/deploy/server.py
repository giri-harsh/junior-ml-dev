"""deploy MCP server (official SDK, stdio). Run: python -m mcp_servers.deploy.server

`deploy_local` needs APPROVAL_SECRET (+ APPROVAL_DB) in the server environment; without them the
tool refuses. Tokens come from the admin approval endpoint (single use, bound to run and model).
"""

from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer

from harness.security.approvals import ApprovalStore
from mcp_servers.deploy import service as s

mcp = MCPServer(
    "deploy",
    instructions="Package trained models and stage local deployments. Deploy needs an approval.",
)


def _approvals() -> ApprovalStore | None:
    secret = os.environ.get("APPROVAL_SECRET", "")
    if not secret:
        return None
    return ApprovalStore(os.environ.get("APPROVAL_DB", "data/approvals.db"), secret)


@mcp.tool()
def package_model(request: s.PackageRequest) -> s.PackageResult:
    """Bundle a model with a predict service, Dockerfile, compose file and model card."""
    return s.package_model(request)


@mcp.tool()
def deploy_local(request: s.DeployRequest) -> s.DeployResult:
    """Stage a local deployment of a packaged model. Requires a single-use approval token."""
    return s.deploy_local(request, _approvals())


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
