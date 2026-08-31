"""
Tracing Middleware for Enterprise RAG Platform

Adds distributed tracing to all requests.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from utils.log_utils import log


def _current_otel_trace_id() -> str:
    """Return the active OpenTelemetry trace ID when one exists."""
    try:
        from opentelemetry import trace

        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            return format(context.trace_id, "032x")
    except Exception:
        pass
    return ""


class TracingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for request tracing.

    Adds trace ID to all requests for distributed tracing.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate or use existing trace ID
        trace_id = (
            _current_otel_trace_id() or request.headers.get("X-Trace-ID") or str(uuid.uuid4())[:16]
        )

        # Store in request state
        request.state.trace_id = trace_id

        # Start timing
        start_time = time.perf_counter()

        # Process request
        response = await call_next(request)
        trace_id = _current_otel_trace_id() or trace_id

        # Calculate duration
        duration = (time.perf_counter() - start_time) * 1000

        # Add trace headers
        response.headers["X-Trace-ID"] = trace_id
        response.headers["X-Response-Time-Ms"] = f"{duration:.1f}"

        # Log request
        log.info(
            f"[{trace_id}] {request.method} {request.url.path} "
            f"- {response.status_code} ({duration:.1f}ms)"
        )

        return response
