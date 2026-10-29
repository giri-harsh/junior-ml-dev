"""OpenTelemetry tracing: spans per run, step and tool call.

Exporter comes from JMD_TRACE: `console` (default, spans printed to stderr), `otlp` (HTTP exporter;
endpoint from the standard OTEL_EXPORTER_OTLP_ENDPOINT / OTEL_EXPORTER_OTLP_HEADERS variables), or
`off`. Everything degrades to a no-op when the SDK is not installed. Span attributes carry ids,
tool names, counts and timings only: never dataset values or column names.
"""

from __future__ import annotations

import os
import sys
from typing import Any

try:  # the SDK is a normal dependency, but tracing must never break a run
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

    HAVE_OTEL = True
except ImportError:  # pragma: no cover
    HAVE_OTEL = False

_provider: Any = None


def _exporter_from_env() -> Any:
    kind = os.environ.get("JMD_TRACE", "console").lower()
    if kind == "off" or not HAVE_OTEL:
        return None
    if kind == "otlp":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found,unused-ignore]
            OTLPSpanExporter,
        )

        return OTLPSpanExporter()  # endpoint/headers from OTEL_EXPORTER_OTLP_* variables
    return ConsoleSpanExporter(out=sys.stderr)


def configure_tracing(exporter: Any = None) -> Any:
    """(Re)build the provider. `exporter=None` reads JMD_TRACE; tests pass an in-memory exporter."""
    global _provider
    if not HAVE_OTEL:
        return None
    exp = exporter if exporter is not None else _exporter_from_env()
    _provider = TracerProvider(resource=Resource.create({"service.name": "junior-ml-dev"}))
    if exp is not None:
        _provider.add_span_processor(SimpleSpanProcessor(exp))
    return _provider


class _NoopSpan:
    def __enter__(self) -> _NoopSpan:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def set_attribute(self, *_: object) -> None:
        return None

    def record_exception(self, *_: object) -> None:
        return None


class _NoopTracer:
    def start_as_current_span(self, *_: object, **__: object) -> _NoopSpan:
        return _NoopSpan()


def tracer() -> Any:
    if not HAVE_OTEL:
        return _NoopTracer()
    if _provider is None:
        configure_tracing()
    return _provider.get_tracer("jmd")
