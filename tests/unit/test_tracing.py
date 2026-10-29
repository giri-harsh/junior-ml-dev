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
