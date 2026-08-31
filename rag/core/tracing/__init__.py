"""
Tracing Module for Enterprise RAG Platform

Provides distributed tracing using OpenTelemetry:
- Request tracing across services
- Performance metrics collection
- Error tracking
- Integration with observability platforms
"""

from core.tracing.opentelemetry import (
    TracingConfig,
    get_tracer,
    instrument_fastapi,
    setup_opentelemetry,
    trace_context,
    traced,
)

__all__ = [
    "TracingConfig",
    "trace_context",
    "get_tracer",
    "instrument_fastapi",
    "setup_opentelemetry",
    "traced",
]
