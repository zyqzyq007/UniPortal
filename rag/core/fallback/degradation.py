"""
Degradation Handler for Enterprise RAG Platform

Provides graceful degradation strategies when services are unavailable:
- Fallback to cached responses
- Simplified response generation
- User notification of degraded service
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from langchain_core.messages import AIMessage

from utils.log_utils import log

__all__ = [
    "DegradationHandler",
    "FallbackMode",
]


class FallbackMode(str, Enum):
    """Degradation fallback modes."""

    FULL = "full"  # Normal operation
    CACHED_ONLY = "cached"  # Use cached responses only
    SIMPLIFIED = "simplified"  # Simplified responses
    OFFLINE = "offline"  # Minimal offline mode


@dataclass
class DegradationConfig:
    """Configuration for degradation handler."""

    default_mode: FallbackMode = FallbackMode.FULL
    cache_ttl: int = 3600  # Cache TTL in seconds
    enable_cache: bool = True


@dataclass
class CachedResponse:
    """Cached response entry."""

    query_hash: str
    response: str
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)


class DegradationHandler:
    """
    Handles graceful degradation when services are unavailable.

    Features:
    - Response caching for fallback
    - Simplified response templates
    - Service status tracking
    - Automatic mode switching
    """

    def __init__(self, config: DegradationConfig | None = None):
        """
        Initialize degradation handler.

        Args:
            config: Degradation configuration
        """
        self.config = config or DegradationConfig()
        self._mode = self.config.default_mode
        self._cache: dict[str, CachedResponse] = {}
        self._service_status: dict[str, bool] = {}

        log.debug(f"DegradationHandler initialized with mode: {self._mode.value}")

    @property
    def mode(self) -> FallbackMode:
        """Get current fallback mode."""
        return self._mode

    @mode.setter
    def mode(self, value: FallbackMode):
        """Set fallback mode."""
        if value != self._mode:
            log.info(f"Degradation mode changed: {self._mode.value} -> {value.value}")
            self._mode = value

    def update_service_status(self, service: str, available: bool):
        """Update service availability status."""
        self._service_status[service] = available

        # Auto-adjust mode based on service status
        if not self._service_status.get("llm", True):
            if self._mode == FallbackMode.FULL:
                self.mode = FallbackMode.CACHED_ONLY
        elif not self._service_status.get("retriever", True):
            if self._mode == FallbackMode.FULL:
                self.mode = FallbackMode.SIMPLIFIED
        else:
            if self._mode in (FallbackMode.CACHED_ONLY, FallbackMode.SIMPLIFIED):
                self.mode = FallbackMode.FULL

    def cache_response(self, query: str, response: str, metadata: dict | None = None):
        """Cache a response for potential fallback."""
        if not self.config.enable_cache:
            return

        import hashlib
        import time

        query_hash = hashlib.md5(query.encode()).hexdigest()
        self._cache[query_hash] = CachedResponse(
            query_hash=query_hash,
            response=response,
            timestamp=time.time(),
            metadata=metadata or {},
        )

        log.debug(f"Cached response for query hash: {query_hash[:8]}...")

    def get_cached_response(self, query: str) -> str | None:
        """Get cached response if available and not expired."""
        if not self.config.enable_cache:
            return None

        import hashlib
        import time

        query_hash = hashlib.md5(query.encode()).hexdigest()
        cached = self._cache.get(query_hash)

        if cached is None:
            return None

        # Check expiration
        if time.time() - cached.timestamp > self.config.cache_ttl:
            del self._cache[query_hash]
            return None

        return cached.response

    def generate_degraded_response(self, query: str, error: str | None = None) -> AIMessage:
        """
        Generate a degraded response based on current mode.

        Args:
            query: User's query
            error: Optional error message

        Returns:
            AI message with appropriate degraded response
        """
        if self._mode == FallbackMode.CACHED_ONLY:
            cached = self.get_cached_response(query)
            if cached:
                return AIMessage(
                    content=f"[缓存响应] {cached}\n\n(服务暂时受限，以上为历史缓存回答)"
                )

        if self._mode == FallbackMode.SIMPLIFIED:
            return AIMessage(content=self._generate_simplified_response(query))

        if self._mode == FallbackMode.OFFLINE:
            return AIMessage(
                content="抱歉，服务暂时不可用。请稍后重试。\n\n"
                "可能的原因：\n"
                "1. 网络连接问题\n"
                "2. 服务正在维护\n"
                "3. 系统负载过高\n\n"
                "请稍后再试，或联系技术支持。"
            )

        # Default error response
        return AIMessage(
            content=f"抱歉，处理您的请求时遇到问题。\n\n"
            f"错误信息: {error or '未知错误'}\n\n"
            f"请稍后重试。"
        )

    def _generate_simplified_response(self, query: str) -> str:
        """Generate a simplified response without full processing."""
        # Simple keyword-based responses
        query_lower = query.lower()

        if any(word in query_lower for word in ["你好", "hello", "hi"]):
            return "您好！有什么可以帮助您的？"

        if any(word in query_lower for word in ["谢谢", "感谢", "thanks"]):
            return "不客气！如果还有其他问题，随时可以问我。"

        if any(word in query_lower for word in ["帮助", "help", "怎么用"]):
            # Help text is sourced from the active domain profile so the
            # degraded path matches the configured domain (aviation refers
            # to 排故/手册; general is domain-neutral).
            from core.prompts.domain_profile import get_active_profile

            return get_active_profile().degradation_help

        return (
            "感谢您的提问。由于服务暂时受限，我无法提供完整的回答。\n\n"
            "建议您：\n"
            "1. 稍后重试\n"
            "2. 简化问题表述\n"
            "3. 联系技术支持获取帮助"
        )

    def clear_cache(self):
        """Clear all cached responses."""
        self._cache.clear()
        log.info("Degradation cache cleared")

    def get_stats(self) -> dict[str, Any]:
        """Get degradation statistics."""
        return {
            "mode": self._mode.value,
            "cache_size": len(self._cache),
            "service_status": self._service_status,
        }


# Module-level instance
_degradation_handler: DegradationHandler | None = None


def get_degradation_handler() -> DegradationHandler:
    """Get or create degradation handler instance."""
    global _degradation_handler
    if _degradation_handler is None:
        _degradation_handler = DegradationHandler()
    return _degradation_handler
