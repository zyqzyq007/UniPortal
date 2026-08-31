"""
Session Memory Module

Provides persistent session memory management:
- Redis-based storage
- Sliding window message retention
- Session expiration
- Summary compression for long conversations
"""

from core.memory.redis_memory import RedisSessionMemory, SessionConfig

__all__ = [
    "RedisSessionMemory",
    "SessionConfig",
]
