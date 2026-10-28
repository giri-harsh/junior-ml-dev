"""Action guard: structural enforcement that does not depend on the model behaving.

Even if injected text fully convinces an agent, these gates decide. Each decision names the rule.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from harness.policies.code_policy import check_code

ApprovalValidator = Callable[[str, str, str], bool]  # (token, action, payload_hash) -> valid


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["run_code", "read_file", "fetch_url", "deploy", "set_target"]
    code: str | None = None
    path: str | None = None
    url: str | None = None
    approval_token: str | None = None
    payload_hash: str = ""
    new_target: str | None = None


@dataclass(frozen=True)
class Decision:
    allowed: bool
    rule: str


@dataclass
class RunContext:
    started: bool = True  # target is immutable once a run has started
    allowed_hosts: tuple[str, ...] = ()  # empty: no network at all
    approval_validator: ApprovalValidator | None = None


def guard(action: Action, ctx: RunContext) -> Decision:
    if action.type == "run_code":
        res = check_code(action.code or "")
        return Decision(res.allowed, "code_policy" if not res.allowed else "ok")
    if action.type == "read_file":
        probe = check_code(f"open({action.path!r})")
        return Decision(probe.allowed, "path_policy" if not probe.allowed else "ok")
    if action.type == "fetch_url":
        host = (action.url or "").split("//")[-1].split("/")[0]
        ok = host in ctx.allowed_hosts
        return Decision(ok, "no_egress" if not ok else "ok")
    if action.type == "deploy":
        if not action.approval_token or ctx.approval_validator is None:
            return Decision(False, "approval_required")
        valid = ctx.approval_validator(action.approval_token, "deploy", action.payload_hash)
        return Decision(valid, "approval_invalid" if not valid else "ok")
    if action.type == "set_target":
        return Decision(not ctx.started, "target_immutable" if ctx.started else "ok")
    return Decision(False, "unknown_action")
