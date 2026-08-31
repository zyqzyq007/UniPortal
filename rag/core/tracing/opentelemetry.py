"""OpenTelemetry setup and lightweight tracing helpers."""

from __future__ import annotations

import functools
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, TypeVar

from utils.env_utils import (
    OTEL_CONSOLE_EXPORTER,
    OTEL_ENABLED,
    OTEL_EXPORTER_OTLP_ENDPOINT,
    OTEL_SAMPLE_RATE,
    OTEL_SERVICE_NAME,
)
from utils.log_utils import log

T = TypeVar("T")
_configured = False
_instrumented_apps: set[int] = set()


@dataclass
class TracingConfig:
    service_name: str = OTEL_SERVICE_NAME
    environment: str = "development"
    enable_tracing: bool = OTEL_ENABLED
    sample_rate: float = OTEL_SAMPLE_RATE
    export_endpoint: str | None = OTEL_EXPORTER_OTLP_ENDPOINT or None
    console_exporter: bool = OTEL_CONSOLE_EXPORTER


class NoOpSpan:
    """Span-compatible object used when OpenTelemetry is disabled."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def add_event(self, name: str, attributes: dict | None = None) -> None:
        pass

    def record_exception(self, exception: BaseException) -> None:
        pass

    def set_status(self, status: Any, description: str = "") -> None:
        pass


def setup_opentelemetry(config: TracingConfig | None = None) -> bool:
    """Configure the global OpenTelemetry provider once."""
    global _configured
    cfg = config or TracingConfig()
    if _configured:
        return cfg.enable_tracing
    if not cfg.enable_tracing:
        log.info("OpenTelemetry tracing disabled")
        return False

    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SimpleSpanProcessor,
    )
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": cfg.service_name,
                "deployment.environment": cfg.environment,
            }
        ),
        sampler=TraceIdRatioBased(cfg.sample_rate),
    )
    if cfg.export_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=cfg.export_endpoint))
        )
    if cfg.console_exporter:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _configured = True
    log.info(
        f"OpenTelemetry enabled: service={cfg.service_name}, "
        f"sample_rate={cfg.sample_rate}, endpoint={cfg.export_endpoint or 'none'}"
    )
    return True


def instrument_fastapi(app: Any) -> bool:
    """Attach standard HTTP server spans to a FastAPI application."""
    if not setup_opentelemetry() or id(app) in _instrumented_apps:
        return False
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)
    _instrumented_apps.add(id(app))
    return True


def get_tracer():
    if not OTEL_ENABLED:
        return None
    setup_opentelemetry()
    from opentelemetry import trace

    return trace.get_tracer("rag-platform")


@contextmanager
def trace_context(name: str, **attributes):
    """Create an OpenTelemetry span, or a no-op span when disabled."""
    tracer = get_tracer()
    if tracer is None:
        yield NoOpSpan()
        return

    with tracer.start_as_current_span(name, attributes=attributes) as span:
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            raise


def traced(name: str | None = None):
    """Trace a synchronous or asynchronous function."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        span_name = name or func.__name__

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            with trace_context(span_name):
                return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            with trace_context(span_name):
                return func(*args, **kwargs)

        import asyncio

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator


def trace_intent_classification(query: str):
    return trace_context("rag.intent", **{"query.length": len(query)})


def trace_retrieval(query: str, top_k: int = 5):
    return trace_context(
        "rag.retrieval",
        **{"query.length": len(query), "retrieval.top_k": top_k},
    )


def trace_llm_call(model: str, prompt_length: int):
    return trace_context(
        "rag.llm",
        **{"gen_ai.request.model": model, "gen_ai.prompt.length": prompt_length},
    )
