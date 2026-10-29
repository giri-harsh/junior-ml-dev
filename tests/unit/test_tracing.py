"""Span structure of an agent run: one run span, a step span per step, tool.call children."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("opentelemetry.sdk.trace")
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402

from harness import tracing  # noqa: E402
from harness.agent.models import RunBudget  # noqa: E402
from tests.unit.test_agent_runner import cfg_for, make_csv, runner  # noqa: E402
from tests.unit.test_agent_runner import env as env  # noqa: E402,F401


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    exp = InMemorySpanExporter()
    tracing.configure_tracing(exp)
    yield exp
    tracing.configure_tracing()  # back to the environment default


def test_run_step_and_tool_spans_nest_correctly(
    env: Path, tmp_path: Path, spans: InMemorySpanExporter
) -> None:  # noqa: F811
    cfg = cfg_for(make_csv(env), run_id="traced", budget=RunBudget(flaml_budget_s=0, tune_trials=0))
    res = runner(tmp_path).run(cfg)
    finished = spans.get_finished_spans()
    by_name: dict[str, list] = {}  # type: ignore[type-arg]
    for s in finished:
        by_name.setdefault(s.name, []).append(s)
    (run,) = by_name["agent.run"]
    steps, tools = by_name["agent.step"], by_name["tool.call"]
    assert run.parent is None and run.attributes["jmd.run_id"] == "traced"
    assert run.attributes["jmd.status"] == res["status"] == "done"
    assert len(steps) == res["n_steps"] and all(
        s.parent.span_id == run.context.span_id for s in steps
    )
    step_ids = {s.context.span_id for s in steps}
    assert tools and all(t.parent.span_id in step_ids for t in tools)
    assert {s.attributes["jmd.tool"] for s in steps} >= {"profile_dataset", "train_model", "report"}
    assert all("jmd.latency_s" in s.attributes and "jmd.ok" in s.attributes for s in steps)
    blob = repr([dict(s.attributes) for s in finished])
    assert "ignore previous" not in blob and str(env) not in blob  # ids and counts only


def test_exporter_selection_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JMD_TRACE", "off")
    assert tracing._exporter_from_env() is None
    monkeypatch.setenv("JMD_TRACE", "console")
    assert type(tracing._exporter_from_env()).__name__ == "ConsoleSpanExporter"
    monkeypatch.setenv("JMD_TRACE", "otlp")
    assert type(tracing._exporter_from_env()).__name__ == "OTLPSpanExporter"


def test_log_lines_carry_trace_ids_inside_spans_and_not_outside(
    spans: InMemorySpanExporter,
) -> None:  # noqa: F811
    import json
    import logging

    from harness.obs import JsonFormatter, log_event

    lines: list[str] = []

    class H(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(JsonFormatter().format(record))

    log = logging.getLogger("obs-test")
    log.handlers = [H()]
    log.setLevel(logging.INFO)
    log.propagate = False
    log_event(log, "outside", "r1", idx=0)
    with tracing.tracer().start_as_current_span("agent.step") as sp:
        log_event(log, "inside", "r1", idx=1, tool="train_model")
        want = format(sp.get_span_context().trace_id, "032x")
    outside, inside = (json.loads(x) for x in lines)
    assert "trace_id" not in outside and outside["run_id"] == "r1"
    assert inside["trace_id"] == want and inside["tool"] == "train_model" and inside["idx"] == 1


def test_metrics_catalog_and_dashboard_match_what_is_exported() -> None:
    import json
    import re

    from harness.obs import render_metrics

    text = render_metrics(
        [{"run_id": "r", "status": "done", "created": 0, "updated": 0}],
        [{"tool": "train_model", "n": 2, "failed": 1, "latency_s": 1.5}],
    )
    exported = set(re.findall(r"^(jmd_[a-z_]+)", text, flags=re.M))
    catalog = Path("docs/METRICS_CATALOG.md").read_text(encoding="utf-8")
    assert all(f"`{m}`" in catalog for m in exported), exported
    dash = json.loads(Path("deploy/grafana/jmd-dashboard.json").read_text(encoding="utf-8"))
    used = set(
        re.findall(
            r"jmd_[a-z_]+", " ".join(t["expr"] for p in dash["panels"] for t in p["targets"])
        )
    )
    assert used <= exported, used - exported
