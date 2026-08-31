"""
Circuit Breaker for Enterprise RAG Platform

Implements the circuit breaker pattern to prevent cascading failures
when external services (LLM, Vector DB) become unavailable.

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Circuit tripped, requests fail fast
- HALF_OPEN: Testing if service recovered
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

from utils.log_utils import log

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "CircuitBreakerError",
]

T = TypeVar("T")


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing fast
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreakerError(Exception):
    """Raised when circuit is open."""

    pass


@dataclass
class CircuitStats:
    """Circuit breaker statistics."""

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    last_failure_time: float | None = None
    last_failure_reason: str | None = None
    consecutive_failures: int = 0


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""

    failure_threshold: int = 5  # Failures before opening
    recovery_timeout: float = 30.0  # Seconds before trying half-open
    half_open_max_calls: int = 3  # Test calls in half-open state
    success_threshold: int = 2  # Successes to close from half-open


class CircuitBreaker:
    """
    Circuit breaker implementation for fault tolerance.

    Prevents cascading failures by failing fast when a service
    is unavailable, and automatically recovers when service returns.

    Example:
        >>> breaker = CircuitBreaker("llm_service")
        >>> try:
        ...     result = await breaker.call(llm.invoke, "Hello")
        ... except CircuitBreakerError:
        ...     # Handle open circuit
        ...     pass
    """

    def __init__(
        self,
        name: str = "default",
        config: CircuitBreakerConfig | None = None,
    ):
        """
        Initialize circuit breaker.

        Args:
            name: Circuit breaker name for logging
            config: Configuration parameters
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._stats = CircuitStats()
        self._half_open_calls = 0
        # Consecutive successes observed since entering HALF_OPEN. Used by
        # _on_success to decide when enough healthy calls warrant closing the
        # circuit (B4: the previous code compared against the cumulative
        # successful_calls counter, which is never reset — so after warmup a
        # single half-open success closed the circuit, defeating
        # success_threshold > 1).
        self._half_open_successes = 0
        self._last_state_change = time.time()

        log.debug(f"CircuitBreaker '{name}' created")

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        # Check for recovery timeout
        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._last_state_change
            if elapsed >= self.config.recovery_timeout:
                self._transition_to(CircuitState.HALF_OPEN)

        return self._state

    @property
    def stats(self) -> dict[str, Any]:
        """Get circuit statistics."""
        return {
            "name": self.name,
            "state": self._state.value,
            "total_calls": self._stats.total_calls,
            "successful_calls": self._stats.successful_calls,
            "failed_calls": self._stats.failed_calls,
            "consecutive_failures": self._stats.consecutive_failures,
            "last_failure_reason": self._stats.last_failure_reason,
        }

    async def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """
        Execute a function through the circuit breaker.

        Args:
            func: Async function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            CircuitBreakerError: If circuit is open
        """
        current_state = self.state

        if current_state == CircuitState.OPEN:
            log.warning(f"Circuit '{self.name}' is OPEN, failing fast")
            raise CircuitBreakerError(
                f"Circuit breaker '{self.name}' is open. Service unavailable."
            )

        if current_state == CircuitState.HALF_OPEN:
            if self._half_open_calls >= self.config.half_open_max_calls:
                log.warning(f"Circuit '{self.name}' HALF_OPEN max calls reached")
                raise CircuitBreakerError(f"Circuit breaker '{self.name}' is testing recovery.")
            self._half_open_calls += 1

        # Execute the function
        try:
            self._stats.total_calls += 1
            result = await func(*args, **kwargs)
            self._on_success()
            return result

        except Exception as e:
            self._on_failure(str(e))
            raise

    def call_sync(self, func: Callable[..., T], *args, **kwargs) -> T:
        """
        Execute a synchronous function through the circuit breaker.

        Args:
            func: Sync function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            CircuitBreakerError: If circuit is open
        """
        current_state = self.state

        if current_state == CircuitState.OPEN:
            log.warning(f"Circuit '{self.name}' is OPEN, failing fast")
            raise CircuitBreakerError(
                f"Circuit breaker '{self.name}' is open. Service unavailable."
            )

        if current_state == CircuitState.HALF_OPEN:
            if self._half_open_calls >= self.config.half_open_max_calls:
                raise CircuitBreakerError(f"Circuit breaker '{self.name}' is testing recovery.")
            self._half_open_calls += 1

        try:
            self._stats.total_calls += 1
            result = func(*args, **kwargs)
            self._on_success()
            return result

        except Exception as e:
            self._on_failure(str(e))
            raise

    def _on_success(self):
        """Handle successful call."""
        self._stats.successful_calls += 1
        self._stats.consecutive_failures = 0

        if self._state == CircuitState.HALF_OPEN:
            self._half_open_successes += 1
            if self._half_open_successes >= self.config.success_threshold:
                self._transition_to(CircuitState.CLOSED)

        log.debug(f"Circuit '{self.name}' call succeeded")

    def _on_failure(self, reason: str):
        """Handle failed call."""
        self._stats.failed_calls += 1
        self._stats.consecutive_failures += 1
        self._stats.last_failure_time = time.time()
        self._stats.last_failure_reason = reason

        if self._state == CircuitState.HALF_OPEN:
            self._transition_to(CircuitState.OPEN)

        elif self._state == CircuitState.CLOSED:
            if self._stats.consecutive_failures >= self.config.failure_threshold:
                self._transition_to(CircuitState.OPEN)

        log.warning(f"Circuit '{self.name}' call failed: {reason}")

    def _transition_to(self, new_state: CircuitState):
        """Transition to a new state."""
        old_state = self._state
        self._state = new_state
        self._last_state_change = time.time()
        self._half_open_calls = 0
        # Reset the half-open success window on every transition. Entering
        # HALF_OPEN starts a fresh consecutive-success count; leaving it
        # (to CLOSED or back to OPEN) clears the window so a later re-entry
        # requires the full success_threshold again (B4).
        self._half_open_successes = 0

        log.info(f"Circuit '{self.name}' state change: {old_state.value} -> {new_state.value}")

    def reset(self):
        """Reset the circuit breaker."""
        self._state = CircuitState.CLOSED
        self._stats = CircuitStats()
        self._half_open_calls = 0
        self._half_open_successes = 0
        self._last_state_change = time.time()
        log.info(f"Circuit '{self.name}' reset")

    def force_open(self):
        """Force circuit open (for maintenance)."""
        self._transition_to(CircuitState.OPEN)

    def force_close(self):
        """Force circuit closed (for testing)."""
        self._transition_to(CircuitState.CLOSED)


# Pre-configured circuit breakers for common services
_llm_circuit: CircuitBreaker | None = None
_retriever_circuit: CircuitBreaker | None = None


def get_llm_circuit() -> CircuitBreaker:
    """Get circuit breaker for LLM calls."""
    global _llm_circuit
    if _llm_circuit is None:
        _llm_circuit = CircuitBreaker(
            name="llm_service",
            config=CircuitBreakerConfig(
                failure_threshold=3,
                recovery_timeout=60.0,
            ),
        )
    return _llm_circuit


def get_retriever_circuit() -> CircuitBreaker:
    """Get circuit breaker for retriever calls."""
    global _retriever_circuit
    if _retriever_circuit is None:
        _retriever_circuit = CircuitBreaker(
            name="retriever_service",
            config=CircuitBreakerConfig(
                failure_threshold=5,
                recovery_timeout=30.0,
            ),
        )
    return _retriever_circuit
