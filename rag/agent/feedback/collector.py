from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from agent.feedback.types import FeedbackEntry, FeedbackType
from utils.log_utils import log

# Module-level path so tests/conftest.py can redirect it to tmp_path
# (AGENTS.md §6/§10 persistence contract). Shared with MemoryStore.
DEFAULT_DB_PATH = "./data/agent_memory.db"


class FeedbackCollector:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # WAL + locking: this collector shares agent_memory.db with MemoryStore.
        # Without synchronisation, concurrent feedback writes interleave with
        # memory reads on the same file and intermittently raise
        # "database is locked". See agent/memory/store.py for the same fix.
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
        except Exception as e:  # noqa: BLE001
            log.debug(f"FeedbackCollector: WAL mode unavailable: {e}")
        self._lock = threading.RLock()
        with self._lock:
            self._init_table()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._lock:
            yield

    def _init_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                message_id TEXT,
                feedback_type TEXT,
                content TEXT,
                original_answer TEXT,
                corrected_answer TEXT,
                timestamp REAL
            )
        """)
        self._conn.commit()

    def record(self, entry: FeedbackEntry) -> str:
        with self._locked():
            self._conn.execute(
                "INSERT INTO feedback (id, session_id, message_id, feedback_type, content, original_answer, corrected_answer, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.id,
                    entry.session_id,
                    entry.message_id,
                    entry.feedback_type.value,
                    entry.content,
                    entry.original_answer,
                    entry.corrected_answer,
                    entry.timestamp,
                ),
            )
            self._conn.commit()
        log.debug(f"FeedbackCollector: recorded feedback {entry.id}")
        return entry.id

    def get_feedback(self, session_id: str) -> list[FeedbackEntry]:
        with self._locked():
            rows = self._conn.execute(
                "SELECT * FROM feedback WHERE session_id = ? ORDER BY timestamp DESC",
                (session_id,),
            ).fetchall()
            return [self._row_to_entry(row) for row in rows]

    def get_stats(self) -> dict:
        with self._locked():
            total = self._conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
            by_type = {}
            for row in self._conn.execute(
                "SELECT feedback_type, COUNT(*) as cnt FROM feedback GROUP BY feedback_type"
            ).fetchall():
                by_type[row["feedback_type"]] = row["cnt"]
        positive = by_type.get(FeedbackType.THUMBS_UP.value, 0)
        positive_rate = positive / total if total > 0 else 0.0
        return {"total": total, "by_type": by_type, "positive_rate": positive_rate}

    def _row_to_entry(self, row) -> FeedbackEntry:
        return FeedbackEntry(
            id=row["id"],
            session_id=row["session_id"],
            message_id=row["message_id"] or "",
            feedback_type=FeedbackType(row["feedback_type"]),
            content=row["content"] or "",
            original_answer=row["original_answer"] or "",
            corrected_answer=row["corrected_answer"] or "",
            timestamp=row["timestamp"],
        )

    def close(self) -> None:
        """Close the underlying SQLite connection. Idempotent."""
        with self._lock:
            conn = getattr(self, "_conn", None)
            if conn is None:
                return
            self._conn = None
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


_feedback_collector: FeedbackCollector | None = None
# Guards singleton init so concurrent first requests don't create two
# FeedbackCollector instances (each opening a sqlite connection to the shared
# agent_memory.db — one becomes orphaned). Mirrors get_inference_store (B12).
_collector_lock = threading.Lock()


def get_feedback_collector() -> FeedbackCollector:
    global _feedback_collector
    if _feedback_collector is None:
        with _collector_lock:
            if _feedback_collector is None:
                _feedback_collector = FeedbackCollector()
    return _feedback_collector


def reset_feedback_collector() -> None:
    """Close and clear the shared singleton (mainly for tests)."""
    global _feedback_collector
    if _feedback_collector is not None:
        _feedback_collector.close()
    _feedback_collector = None
