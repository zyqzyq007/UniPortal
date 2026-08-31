"""
Error Handler Middleware for Enterprise RAG Platform

Provides centralized error handling and response formatting.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from utils.log_utils import log


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """
    Middleware for centralized error handling.

    Catches all exceptions and returns standardized error responses.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)

        except Exception as e:
            # Log the full detail server-side.
            trace_id = getattr(request.state, "trace_id", "unknown")
            log.error(f"[{trace_id}] Unhandled error: {e}", exc_info=True)

            # Return standardized error response. The message is generic — str(e)
            # may contain internal paths, DB URIs, or stack internals (B3
            # information-disclosure hardening). The trace_id lets operators
            # correlate the client-visible error with the server log.
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "type": type(e).__name__,
                        "message": "服务暂时不可用，请稍后重试",
                        "trace_id": trace_id,
                    }
                },
            )
