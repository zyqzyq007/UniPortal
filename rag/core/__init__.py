"""
Core Module for Enterprise RAG Platform

Provides essential components:
- Intent classification
- Multi-path retrieval
- Session memory management
- Model fallback/circuit breaker
- Distributed tracing
"""

from core.fallback.circuit_breaker import CircuitBreaker, CircuitState
from core.intent.classifier import IntentClassifier, IntentType
from core.memory.redis_memory import RedisSessionMemory
from core.retrieval.hybrid_retriever import HybridRetriever

__all__ = [
    "IntentClassifier",
    "IntentType",
    "HybridRetriever",
    "RedisSessionMemory",
    "CircuitBreaker",
    "CircuitState",
]
