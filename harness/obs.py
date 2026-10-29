"""Structured JSON logging with a run_id context, plus Prometheus-style text rendering."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {"level": record.levelname, "logger": record.name}
        payload["msg"] = record.getMessage()
        payload.update(getattr(record, "ctx", {}))
        return json.dumps(payload, default=str, sort_keys=True)


def configure(name: str = "agent", level: int = logging.INFO) -> logging.Logger:
    log = logging.getLogger(name)
    if not log.handlers:
        h = logging.StreamHandler(sys.stderr)  # stderr: MCP stdio owns stdout
        h.setFormatter(JsonFormatter())
        log.addHandler(h)
        log.propagate = False
    log.setLevel(level)
    return log


def _trace_ids() -> dict[str, str]:
    """trace_id/span_id of the current OpenTelemetry span (empty when tracing is off)."""
    try:
        from opentelemetry import trace
    except ImportError:  # pragma: no cover
        return {}
    ctx = trace.get_current_span().get_span_context()
    if not ctx.is_valid:
        return {}
    return {"trace_id": format(ctx.trace_id, "032x"), "span_id": format(ctx.span_id, "016x")}


def log_event(log: logging.Logger, msg: str, run_id: str, **ctx: Any) -> None:
    """One JSON line with run_id, any step fields (idx, tool, ...) and the current trace ids, so
    a log line can be joined to its span."""
    log.info(msg, extra={"ctx": {"run_id": run_id, **_trace_ids(), **ctx}})


def render_metrics(runs: list[dict[str, Any]], steps: list[dict[str, Any]]) -> str:
    """Prometheus exposition text from RunStore aggregates."""
    lines = ["# TYPE jmd_runs gauge"]
    by_status: dict[str, int] = {}
    for r in runs:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    lines += [f'jmd_runs{{status="{k}"}} {v}' for k, v in sorted(by_status.items())]
    lines += ["# TYPE jmd_steps_total counter", "# TYPE jmd_step_latency_seconds_sum counter"]
    for s in sorted(steps, key=lambda x: x["tool"]):
        tool = str(s["tool"]).replace('"', "")
        lines.append(f'jmd_steps_total{{tool="{tool}"}} {s["n"]}')
        lines.append(f'jmd_steps_failed_total{{tool="{tool}"}} {s["failed"]}')
        lines.append(f'jmd_step_latency_seconds_sum{{tool="{tool}"}} {s["latency_s"]:.3f}')
    return "\n".join(lines) + "\n"
