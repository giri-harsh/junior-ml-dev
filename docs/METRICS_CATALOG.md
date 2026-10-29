# Prometheus metrics catalog

Exposed at `GET /metrics` (text exposition format, aggregates only: no run ids, no data). Source:
`harness/obs.py::render_metrics`, fed by the run store. Scrape unauthenticated; the endpoint leaks
only counts.

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `jmd_runs` | gauge | `status` (running, done, budget_exhausted, degenerate, awaiting_approval) | Runs currently in each status |
| `jmd_steps_total` | counter | `tool` | Checkpointed agent steps per tool |
| `jmd_steps_failed_total` | counter | `tool` | Steps that ended in an error after their retries |
| `jmd_step_latency_seconds_sum` | counter | `tool` | Sum of step latencies per tool (divide by `jmd_steps_total` for the mean) |

A sample Grafana dashboard (file only, nothing is installed) is in `deploy/grafana/jmd-dashboard.json`.

## Logs and traces

Every log line is JSON on stderr with `run_id`, the step fields (`idx`, `tool`, `ok`, `latency_s`)
and, inside a span, `trace_id` and `span_id`, so a line can be joined to its OpenTelemetry span
(`agent.run` > `agent.step` > `tool.call`). Exporter: `JMD_TRACE=console|otlp|off`.
