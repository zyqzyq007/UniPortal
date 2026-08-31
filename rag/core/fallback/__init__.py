"""
Model Fallback Module

Provides resilience patterns for LLM calls:
- Circuit breaker (prevent cascading failures)
- Graceful degradation strategies

Note: ``retry_with_backoff`` was removed — the decorator was defined but never
applied to any call site at runtime. Exponential-backoff retry, if needed in
future, should be reintroduced with an actual integration point.
"""

from core.fallback.circuit_breaker import CircuitBreaker, CircuitBreakerError, CircuitState
from core.fallback.degradation import DegradationHandler, FallbackMode

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "CircuitBreakerError",
    "DegradationHandler",
    "FallbackMode",
]
