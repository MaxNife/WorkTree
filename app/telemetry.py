"""OpenTelemetry hooks. Off by default; a no-op unless enabled and the ``otel`` extra is installed.

Call sites use :func:`span` unconditionally. With telemetry disabled (the default) it costs one
function call and records nothing, so the platform has no hard dependency on OpenTelemetry.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.config import Settings
from app.logging_setup import get_logger

_tracer: Any = None


def configure_telemetry(settings: Settings) -> bool:
    """Install a tracer when ``otel.enabled`` is true. Returns whether tracing is active."""
    global _tracer
    _tracer = None
    if not settings.otel.enabled:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
    except ImportError:
        get_logger(__name__).warning(
            "otel_unavailable", hint="install the optional extra: pip install 'uaf[otel]'"
        )
        return False
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        trace.set_tracer_provider(TracerProvider())
    _tracer = trace.get_tracer("uaf")
    return True


def is_enabled() -> bool:
    return _tracer is not None


@contextmanager
def span(name: str, **attributes: str | int | float | bool) -> Iterator[None]:
    """Trace a block when telemetry is on; otherwise do nothing."""
    if _tracer is None:
        yield
        return
    with _tracer.start_as_current_span(name, attributes=attributes):
        yield
