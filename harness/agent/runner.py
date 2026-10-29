"""Plan -> execute loop with guardrails, budgets, checkpoints, resume and audit.

Guarantees: every tool call is policy-checked, audit-logged and checkpointed; a killed process
resumes at the first uncheckpointed step; budget exhaustion jumps to a bounded wrap-up (compare,
review, refit, predict, report) instead of stopping dead; a failed step is retried at most
`step_retries` times (only for transient errors) and then skipped; if no model exists at the end
of the search a baseline is trained directly. The run always ends with a status and a result.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from harness.agent.deploy_tools import REGISTRY as DEPLOY_REGISTRY
from harness.agent.models import RunConfig, Step, StepRecord
from harness.agent.planners import Planner, step_key
from harness.agent.report import write_report
from harness.agent.store import RunStore
from harness.agent.tools import REGISTRY, Reducer, Tool, ToolCtx
from harness.obs import configure, log_event
from harness.policies.actions import Action, RunContext, guard
from harness.security.approvals import ApprovalStore, payload_hash
from harness.security.audit import AuditLog
from mcp_servers.data_tools.service import GuardError
from mcp_servers.experiments.service import ExperimentError
from trajectory.emit import emit
from trajectory.models import EventKind

WRAP_RESERVE = 10  # steps allowed beyond max_steps for the bounded wrap-up
DETERMINISTIC_ERRORS = (ExperimentError, GuardError, ValidationError, ValueError, KeyError)
RISKY_TOOLS = {"deploy_local"}
TERMINAL = {"done", "budget_exhausted", "degenerate"}


def new_state() -> dict[str, Any]:
    return {"done": [], "failures": {}, "models": {}, "dropped": [], "findings": []}


class AgentRunner:
    def __init__(
        self,
        store: RunStore,
        planner: Planner,
        *,
        run_root: Path | str = "data/runs",
        audit: AuditLog | None = None,
        approvals: ApprovalStore | None = None,
        approval_token: str | None = None,
        extra_tools: dict[str, tuple[Tool, Reducer]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        crash_after: int | None = None,
    ) -> None:
        self.store, self.planner = store, planner
        self.run_root = Path(run_root)
        self.audit, self.approvals, self.token = audit, approvals, approval_token
        self.tools = {**REGISTRY, **DEPLOY_REGISTRY, **(extra_tools or {})}
        self.clock = clock
        self.crash_after = crash_after
        self.log = configure("agent")

    def _usage(self) -> tuple[int, float]:
        return int(getattr(self.planner, "tokens", 0)), float(
            getattr(self.planner, "cost_usd", 0.0)
        )

    # --- single step --------------------------------------------------------------------------
    def _guard(self, cfg: RunConfig, step: Step, ctx: ToolCtx) -> str | None:
        task = cfg.task
        for path in (task.data_path, task.test_features_path):
            if path and not guard(Action(type="read_file", path=path), RunContext()).allowed:
                return "blocked:path_policy"
        if step.tool in RISKY_TOOLS:
            payload = {"model_id": step.args.get("model_id")}
            validator = None
            if self.approvals is not None:
                validator = self.approvals.as_validator(cfg.run_id, payload)
            act = Action(
                type="deploy", approval_token=self.token, payload_hash=payload_hash(payload)
            )
            decision = guard(act, RunContext(approval_validator=validator))
            if not decision.allowed:
                return f"blocked:{decision.rule}"
            ctx.extra.update(approvals=self.approvals, token=self.token, payload=payload)
            if cfg.mode != "dev" and self.audit is not None:  # never silent
                self.audit.append(
                    f"agent:{cfg.run_id}", "preseeded_approval_used", {"mode": cfg.mode, **payload}
                )
        return None

    def _execute(
        self,
        cfg: RunConfig,
        step: Step,
        idx: int,
        state: dict[str, Any],
        records: list[StepRecord],
        usage0: tuple[int, float] | None = None,
    ) -> StepRecord:
        ctx = ToolCtx(cfg=cfg, state=state, records=records,
                      extra={"run_root": self.run_root / cfg.run_id})  # fmt: skip
        t0 = self.clock()
        tokens0, cost0 = usage0 or self._usage()
        result: dict[str, Any] = {}
        error = self._guard(cfg, step, ctx)
        attempts = 0
        if error is None and step.tool not in self.tools and step.tool != "report":
            error = "unknown_tool"
        while error is None and attempts <= cfg.budget.step_retries:
            attempts += 1
            try:
                if step.tool == "report":
                    result = write_report(cfg, state, records, self.run_root / cfg.run_id)
                    state["report"] = result
                else:
                    fn, reduce = self.tools[step.tool]
                    result = fn(ctx, step.args)
                    reduce(state, step.args, result)
                error = None
                break
            except DETERMINISTIC_ERRORS as exc:
                error = f"{type(exc).__name__}: {str(exc)[:200]}"
            except Exception as exc:  # transient or unexpected: bounded retry
                error = f"{type(exc).__name__}: {str(exc)[:200]}"
                if attempts <= cfg.budget.step_retries:
                    error = None
                    continue
            break
        ok = error is None
        rec = StepRecord(
            idx=idx, step=step, ok=ok, result=result if ok else {}, error=error,
            latency_s=round(self.clock() - t0, 4), attempts=max(attempts, 1),
            tokens=self._usage()[0] - tokens0,
            cost_usd=self._usage()[1] - cost0,
        )  # fmt: skip
        key = step_key(step)
        state["done"].append(key)
        if not ok:
            state["failures"][key] = error
        if self.audit is not None:
            args_hash = hashlib.sha256(json.dumps(step.args, sort_keys=True).encode()).hexdigest()
            self.audit.append(
                f"agent:{cfg.run_id}", "tool_call",
                {"tool": step.tool, "server": step.server, "args_sha256": args_hash,
                 "ok": ok, "error": (error or "")[:80]},
            )  # fmt: skip
        emit(cfg.run_id, EventKind.TOOL_CALL, {"tool": step.tool, "ok": ok, "idx": idx},
             agent_version=self.planner.name)  # fmt: skip
        log_event(self.log, "step", cfg.run_id, idx=idx, tool=step.tool, ok=ok,
                  latency_s=rec.latency_s, error=error)  # fmt: skip
        return rec

    # --- loop ---------------------------------------------------------------------------------
    def run(self, cfg: RunConfig) -> dict[str, Any]:
        created = self.store.create(cfg)
        if not created and self.store.status(cfg.run_id) in TERMINAL:
            return self.store.result(cfg.run_id) or {}
        cps = self.store.checkpoints(cfg.run_id)
        records = [r for r, _ in cps]
        state = cps[-1][1] if cps else new_state()
        resumed = bool(cps)
        spent_before = sum(r.latency_s for r in records)
        start = self.clock()
        b = cfg.budget
        if resumed:
            log_event(self.log, "resume", cfg.run_id, from_step=len(records))
        while True:
            idx = len(records)
            wall = spent_before + (self.clock() - start)
            tokens = sum(r.tokens for r in records)
            if not state.get("budget_exhausted") and (
                idx >= b.max_steps or wall > b.max_wall_s or tokens > b.max_tokens
            ):
                state["budget_exhausted"] = {
                    "steps": idx,
                    "wall_s": round(wall, 2),
                    "tokens": tokens,
                }
                emit(cfg.run_id, EventKind.BUDGET, dict(state["budget_exhausted"]),
                     agent_version=self.planner.name)  # fmt: skip
            if idx >= b.max_steps + WRAP_RESERVE:
                break
            usage0 = self._usage()  # planner (LLM) usage is attributed to the step it proposes
            step = self.planner.next_step(cfg, state)
            if step is None:
                break
            if step.tool in RISKY_TOOLS and self.token is None and self.approvals is not None:
                pending = self._request_approval(cfg, step)
                return self._finish(
                    cfg, state, records, resumed, spent_before + (self.clock() - start), pending
                )
            if step.tool == "compare_models":
                idx = self._ensure_baselines(cfg, state, records)
            rec = self._execute(cfg, step, idx, state, records, usage0)
            records.append(rec)
            self.store.checkpoint(cfg.run_id, rec, state)
            if self.crash_after is not None and len(records) >= self.crash_after:
                os._exit(137)  # failure injection: simulate a hard kill after a checkpoint
        return self._finish(cfg, state, records, resumed, spent_before + (self.clock() - start))

    def _request_approval(self, cfg: RunConfig, step: Step) -> dict[str, Any]:
        assert self.approvals is not None
        payload = {"model_id": step.args.get("model_id")}
        prior = (self.store.result(cfg.run_id) or {}).get("pending_approval")
        if prior and prior.get("payload") == payload:
            return dict(prior)
        aid = self.approvals.request("deploy", cfg.run_id, payload)
        if self.audit is not None:
            self.audit.append(f"agent:{cfg.run_id}", "approval_requested", {"id": aid, **payload})
        return {"approval_id": aid, "action": "deploy", "payload": payload}

    def _ensure_baselines(
        self, cfg: RunConfig, state: dict[str, Any], records: list[StepRecord]
    ) -> int:
        """If the search produced no usable model, train baselines directly (never end empty)."""
        have = any(m["fit_on"] == "train_split" for m in state["models"].values())
        for fam in () if have else ("linear", "dummy"):
            idx = len(records)
            saved = list(state["dropped"])
            state["dropped"] = []  # the drop list itself may have caused the failure
            step = Step(tool="train_model", args={"family": fam}, reason="fallback baseline")
            rec = self._execute(cfg, step, idx, state, records)
            state["dropped"] = saved if not rec.ok else []
            records.append(rec)
            self.store.checkpoint(cfg.run_id, rec, state)
            if rec.ok:
                break
        return len(records)

    def _finish(
        self,
        cfg: RunConfig,
        state: dict[str, Any],
        records: list[StepRecord],
        resumed: bool,
        elapsed: float,
        awaiting: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        chosen = state.get("chosen")
        m = state["models"].get(chosen or "", {})
        status = (
            "degenerate"
            if chosen is None
            else ("budget_exhausted" if state.get("budget_exhausted") else "done")
        )
        if awaiting is not None:
            status = "awaiting_approval"
        trace = {
            "run_id": cfg.run_id, "planner": self.planner.name, "resumed": resumed,
            "steps": [
                {"idx": r.idx, "tool": r.step.tool, "server": r.step.server, "ok": r.ok,
                 "latency_s": r.latency_s, "tokens": r.tokens, "attempts": r.attempts,
                 "error": r.error}
                for r in records
            ],
        }  # fmt: skip
        out_dir = self.run_root / cfg.run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "trace.json").write_text(json.dumps(trace, indent=1), encoding="utf-8")
        result = {
            "run_id": cfg.run_id, "status": status, "planner": cfg.planner,
            "llm_mode": cfg.llm_mode, "n_steps": len(records), "resumed": resumed,
            "chosen": chosen, "final_model_id": state.get("final_model_id"),
            "chosen_family": m.get("family"), "val_score": m.get("val_score"),
            "predictions_path": state.get("predictions_path"),
            "dropped": state["dropped"], "unresolved": state.get("unresolved", []),
            "review": state.get("review", {}).get("verdict"),
            "failures": state["failures"], "budget_exhausted": state.get("budget_exhausted"),
            "tokens": sum(r.tokens for r in records),
            "cost_usd": round(sum(r.cost_usd for r in records), 6),
            "latency_s": round(elapsed, 3), "report": state.get("report"),
            "trace_path": str(out_dir / "trace.json"),
            "pending_approval": awaiting,
        }  # fmt: skip
        self.store.set_status(cfg.run_id, status, result)
        return result
