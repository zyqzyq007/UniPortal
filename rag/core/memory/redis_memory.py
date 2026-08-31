"""
Redis Session Memory for Enterprise RAG Platform

Provides persistent session storage with:
- Sliding window message retention
- Memory-efficient serialization
- Connection pooling for low-resource servers
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from utils.log_utils import log

__all__ = [
    "RedisSessionMemory",
    "SessionConfig",
    "DEFAULT_SESSION_DB_PATH",
]

# Module-level path attribute (AGENTS.md §6/§10 persistence contract) for the
# SQLite fallback store, so tests/conftest.py and tests/e2e_ui/_fakes.py can
# redirect it to tmp_path. (The in-process client fixture overrides
# get_session_memory via dependency_overrides, so this path is only hit by the
# real uvicorn process when Redis is unavailable.)
DEFAULT_SESSION_DB_PATH = os.getenv("SESSIONS_DB", "./data/sessions.db")


@dataclass
class SessionConfig:
    """Configuration for session memory."""

    redis_url: str = "redis://localhost:6379/0"
    max_messages: int = 50  # Max messages per session
    key_prefix: str = "rag:session:"
    connection_pool_size: int = 5


class RedisSessionMemory:
    """
    Redis-based session memory manager.

    Features:
    - Persistent storage across restarts
    - Sliding window message retention
    - Memory-efficient JSON serialization
    """

    def __init__(
        self,
        config: SessionConfig | None = None,
        redis_client: Any | None = None,
    ):
        self.config = config or SessionConfig()
        self._redis = redis_client
        self._connected = False

    @property
    def redis(self):
        """Get Redis client (lazy initialization)."""
        if self._redis is None:
            try:
                import redis.asyncio as aioredis

                self._redis = aioredis.from_url(
                    self.config.redis_url,
                    max_connections=self.config.connection_pool_size,
                    decode_responses=True,
                )
                self._connected = True
                log.info(f"Redis connected: {self.config.redis_url}")
            except ImportError:
                log.warning("redis package not installed, using SQLite fallback")
                self._redis = _SQLiteStore()
            except Exception as e:
                log.error(f"Redis connection failed: {e}, using SQLite fallback")
                self._redis = _SQLiteStore()
        return self._redis

    def _session_key(self, session_id: str) -> str:
        """Generate Redis key for session."""
        return f"{self.config.key_prefix}{session_id}"

    async def save_message(
        self,
        session_id: str,
        message: BaseMessage,
    ) -> bool:
        """Save a message to session history."""
        try:
            key = self._session_key(session_id)

            msg_data = self._serialize_message(message)
            msg_json = json.dumps(msg_data, ensure_ascii=False)

            # Derive a short title from the first HumanMessage
            title = ""
            if isinstance(message, HumanMessage):
                title = message.content[:50].replace("\n", " ").strip()

            try:
                await self.redis.lpush(key, msg_json)
                await self.redis.ltrim(key, 0, self.config.max_messages - 1)
                await self.redis.register_session(session_id, title)
            except Exception as conn_err:
                if not isinstance(self._redis, _SQLiteStore):
                    log.warning(f"Redis operation failed, switching to SQLite: {conn_err}")
                    self._redis = _SQLiteStore()
                    self._connected = False
                    await self.redis.lpush(key, msg_json)
                    await self.redis.ltrim(key, 0, self.config.max_messages - 1)
                    await self.redis.register_session(session_id, title)
                else:
                    raise conn_err

            log.debug(f"Message saved to session {session_id[:8]}...")
            return True

        except Exception as e:
            log.error(f"Failed to save message: {e}")
            return False

    async def get_messages(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[BaseMessage]:
        """Get messages from session history (newest first)."""
        limit = limit or self.config.max_messages

        try:
            key = self._session_key(session_id)
            msg_jsons = await self.redis.lrange(key, 0, limit - 1)

            messages = []
            for msg_json in msg_jsons:
                try:
                    msg_data = json.loads(msg_json)
                    message = self._deserialize_message(msg_data)
                    if message:
                        messages.append(message)
                except Exception as e:
                    log.warning(f"Failed to deserialize message: {e}")

            log.debug(f"Retrieved {len(messages)} messages from session {session_id[:8]}...")
            return messages

        except Exception as e:
            log.error(f"Failed to get messages: {e}")
            return []

    async def register_session(self, session_id: str, title: str = ""):
        """Register or update a session in the session registry."""
        try:
            await self.redis.register_session(session_id, title)
        except Exception as e:
            log.error(f"Failed to register session: {e}")

    async def list_sessions(self, skip: int = 0, limit: int = 20):
        """List all tracked sessions."""
        try:
            return await self.redis.list_sessions(skip, limit)
        except Exception as e:
            log.error(f"Failed to list sessions: {e}")
            return [], 0

    async def clear_session(self, session_id: str) -> bool:
        """Clear all messages for a session and unregister it."""
        try:
            key = self._session_key(session_id)
            await self.redis.delete(key)
            await self.redis.unregister_session(session_id)
            log.info(f"Session cleared: {session_id[:8]}...")
            return True
        except Exception as e:
            log.error(f"Failed to clear session: {e}")
            return False

    async def session_exists(self, session_id: str) -> bool:
        """Check if session exists."""
        try:
            key = self._session_key(session_id)
            exists = await self.redis.exists(key)
            return exists > 0
        except Exception:
            return False

    async def get_session_info(self, session_id: str) -> dict[str, Any]:
        """Get session metadata."""
        try:
            key = self._session_key(session_id)
            length = await self.redis.llen(key)

            return {
                "session_id": session_id,
                "message_count": length,
                "exists": length > 0,
            }
        except Exception as e:
            return {"session_id": session_id, "error": str(e)}

    def _serialize_message(self, message: BaseMessage) -> dict[str, Any]:
        """Serialize a message to JSON-compatible dict."""
        msg_type = type(message).__name__
        kwargs = dict(getattr(message, "additional_kwargs", {}) or {})
        kwargs["_timestamp"] = time.time()
        return {
            "type": msg_type,
            "content": message.content,
            "additional_kwargs": kwargs,
        }

    def _deserialize_message(self, data: dict[str, Any]) -> BaseMessage | None:
        """Deserialize a message from dict."""
        msg_type = data.get("type", "HumanMessage")
        content = data.get("content", "")
        kwargs = data.get("additional_kwargs", {})

        message_classes = {
            "HumanMessage": HumanMessage,
            "AIMessage": AIMessage,
            "SystemMessage": SystemMessage,
        }

        msg_class = message_classes.get(msg_type, HumanMessage)
        return msg_class(content=content, additional_kwargs=kwargs)

    async def close(self):
        """Close Redis connection."""
        if self._redis is not None and hasattr(self._redis, "close"):
            await self._redis.close()
            log.debug("Redis connection closed")


class _SQLiteStore:
    """
    SQLite-based persistent fallback when Redis is unavailable.

    Data survives restarts. No TTL — sessions persist until manually deleted.
    """

    def __init__(self, db_path: str = DEFAULT_SESSION_DB_PATH):
        import sqlite3

        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.RLock()
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            "  key TEXT NOT NULL,"
            "  idx INTEGER NOT NULL,"
            "  value TEXT NOT NULL,"
            "  PRIMARY KEY (key, idx)"
            ")"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS session_meta ("
            "  session_id TEXT PRIMARY KEY,"
            "  created_at REAL NOT NULL,"
            "  last_active REAL NOT NULL,"
            "  title TEXT NOT NULL DEFAULT ''"
            ")"
        )
        # Migrate: add title column if missing
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(session_meta)").fetchall()]
        if "title" not in cols:
            self._conn.execute("ALTER TABLE session_meta ADD COLUMN title TEXT NOT NULL DEFAULT ''")
        self._conn.commit()
        log.info(f"SQLite session store initialized: {db_path}")

    async def lpush(self, key: str, value: str):
        with self._lock:
            self._conn.execute("UPDATE sessions SET idx = idx + 1 WHERE key = ?", (key,))
            self._conn.execute(
                "INSERT INTO sessions (key, idx, value) VALUES (?, 0, ?)",
                (key, value),
            )
            self._conn.commit()

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT value FROM sessions WHERE key = ? ORDER BY idx LIMIT ? OFFSET ?",
                (key, end - start + 1, start),
            ).fetchall()
            return [r[0] for r in rows]

    async def ltrim(self, key: str, start: int, end: int):
        with self._lock:
            self._conn.execute(
                "DELETE FROM sessions WHERE key = ? AND idx NOT IN "
                "(SELECT idx FROM sessions WHERE key = ? ORDER BY idx LIMIT ? OFFSET ?)",
                (key, key, end - start + 1, start),
            )
            rows = self._conn.execute(
                "SELECT rowid FROM sessions WHERE key = ? ORDER BY idx",
                (key,),
            ).fetchall()
            for new_idx, (rowid,) in enumerate(rows):
                self._conn.execute(
                    "UPDATE sessions SET idx = ? WHERE rowid = ?",
                    (new_idx, rowid),
                )
            self._conn.commit()

    async def llen(self, key: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE key = ?", (key,)
            ).fetchone()
            return row[0] if row else 0

    async def delete(self, key: str):
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE key = ?", (key,))
            self._conn.commit()

    async def exists(self, key: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM sessions WHERE key = ? LIMIT 1", (key,)
            ).fetchone()
            return 1 if row else 0

    async def register_session(self, session_id: str, title: str = ""):
        now = time.time()
        with self._lock:
            existing = self._conn.execute(
                "SELECT title FROM session_meta WHERE session_id = ?", (session_id,)
            ).fetchone()
            if existing:
                if title and not existing[0]:
                    self._conn.execute(
                        "UPDATE session_meta SET last_active = ?, title = ? WHERE session_id = ?",
                        (now, title, session_id),
                    )
                else:
                    self._conn.execute(
                        "UPDATE session_meta SET last_active = ? WHERE session_id = ?",
                        (now, session_id),
                    )
            else:
                self._conn.execute(
                    "INSERT INTO session_meta (session_id, created_at, last_active, title) VALUES (?, ?, ?, ?)",
                    (session_id, now, now, title),
                )
            self._conn.commit()

    async def list_sessions(self, skip: int = 0, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id, created_at, last_active, title FROM session_meta "
                "ORDER BY last_active DESC LIMIT ? OFFSET ?",
                (limit, skip),
            ).fetchall()
            total = self._conn.execute("SELECT COUNT(*) FROM session_meta").fetchone()[0]

        results = []
        for session_id, created_at, last_active, title in rows:
            key = f"rag:session:{session_id}"
            with self._lock:
                msg_count = self._conn.execute(
                    "SELECT COUNT(*) FROM sessions WHERE key = ?", (key,)
                ).fetchone()[0]

            results.append(
                {
                    "session_id": session_id,
                    "message_count": msg_count,
                    "created_at": created_at,
                    "last_active": last_active,
                    "title": title,
                }
            )
        return results, total

    async def unregister_session(self, session_id: str):
        with self._lock:
            self._conn.execute("DELETE FROM session_meta WHERE session_id = ?", (session_id,))
            self._conn.commit()

    async def close(self):
        if self._conn:
            self._conn.close()


# Module-level instance (lazy loaded)
_memory_instance: RedisSessionMemory | None = None


def get_session_memory(config: SessionConfig | None = None) -> RedisSessionMemory:
    """Get or create session memory instance."""
    global _memory_instance

    if _memory_instance is None or config is not None:
        _memory_instance = RedisSessionMemory(config=config)
        log.debug("Created new RedisSessionMemory instance")

    return _memory_instance
