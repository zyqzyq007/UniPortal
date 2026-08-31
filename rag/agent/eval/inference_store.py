"""
Online inference store.

Captures the joined tuple (query, retrieved contexts, answer, trace_id) for a
sample of production requests, so they can be:
  - re-evaluated by the LLM-as-judge (flywheel),
  - promoted into the golden dataset (candidates),
  - joined to user feedback via trace_id / message_id.

This is the missing "first-class production-conversation log": previously the
retrieved context only survived inside LangGraph checkpoint msgpack blobs that
are not queryable for evaluation.

Storage: SQLite at ``data/inferences.db``. The single shared connection is
guarded by a threading.RLock (the FeedbackCollector in the same project has
the same shape but lacks the lock — we do not repeat that mistake here).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from utils.log_utils import log

__all__ = [
    "InferenceRecord",
    "InferenceStore",
    "get_inference_store",
]

DEFAULT_DB_PATH = "./data/inferences.db"


@dataclass
class InferenceRecord:
    """One production inference, captured for offline analysis."""

    trace_id: str = ""
    message_id: str = ""
    session_id: str = ""
    query: str = ""
    retrieved_docs: list[dict[str, Any]] = field(default_factory=list)
    answer: str = ""
    reasoning: str = ""
    route: str = ""  # rag | fast | general_chat | degraded
    prompt_profile: str = ""
    intent: str = ""
    latency_ms: float = 0.0
    token_usage: dict[str, Any] = field(default_factory=dict)
    git_commit: str = ""
    sampled: bool = True
    created_at: float = field(default_factory=time.time)


class InferenceStore:
    """Thread-safe SQLite store for inference records."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS inference (
                    trace_id        TEXT PRIMARY KEY,
                    message_id      TEXT,
                    session_id      TEXT,
                    query           TEXT,
                    retrieved_docs  TEXT,
                    answer          TEXT,
                    reasoning       TEXT,
                    route           TEXT,
                    prompt_profile  TEXT,
                    intent          TEXT,
                    latency_ms      REAL,
                    token_usage     TEXT,
                    git_commit      TEXT,
                    sampled         INTEGER DEFAULT 1,
                    created_at      REAL
                )
                """
            )
            # Indexes for the common query patterns used by the flywheel.
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_inference_session ON inference(session_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_inference_message ON inference(message_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_inference_sampled "
                "ON inference(sampled) WHERE sampled = 1"
            )
            self._conn.commit()

    def record(self, rec: InferenceRecord) -> str:
        """Insert (or replace) an inference record. Returns the trace_id."""
        if not rec.trace_id:
            rec.trace_id = uuid.uuid4().hex
        if not rec.message_id:
            rec.message_id = uuid.uuid4().hex
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO inference
                (trace_id, message_id, session_id, query, retrieved_docs,
                 answer, reasoning, route, prompt_profile, intent,
                 latency_ms, token_usage, git_commit, sampled, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.trace_id,
                    rec.message_id,
                    rec.session_id,
                    rec.query,
                    json.dumps(rec.retrieved_docs, ensure_ascii=False),
                    rec.answer,
                    rec.reasoning,
                    rec.route,
                    rec.prompt_profile,
                    rec.intent,
                    rec.latency_ms,
                    json.dumps(rec.token_usage, ensure_ascii=False),
                    rec.git_commit,
                    1 if rec.sampled else 0,
                    rec.created_at,
                ),
            )
            self._conn.commit()
        log.debug(f"InferenceStore: recorded trace={rec.trace_id[:12]}... route={rec.route}")
        return rec.trace_id

    def get(self, trace_id: str) -> InferenceRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM inference WHERE trace_id = ?",
                (trace_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def get_by_message(self, message_id: str) -> InferenceRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM inference WHERE message_id = ? ORDER BY created_at DESC LIMIT 1",
                (message_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def get_by_session(self, session_id: str, limit: int = 50) -> list[InferenceRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM inference WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def list_sampled(self, limit: int = 100, offset: int = 0) -> list[InferenceRecord]:
        """Sampled candidates for review / promotion to golden."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM inference WHERE sampled = 1 "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM inference").fetchone()[0]
            sampled = self._conn.execute(
                "SELECT COUNT(*) FROM inference WHERE sampled = 1"
            ).fetchone()[0]
            by_route: dict[str, int] = {}
            for row in self._conn.execute(
                "SELECT route, COUNT(*) AS c FROM inference GROUP BY route"
            ).fetchall():
                by_route[row["route"] or "unknown"] = row["c"]
        return {"total": total, "sampled": sampled, "by_route": by_route}

    def _row_to_record(self, row: sqlite3.Row) -> InferenceRecord:
        return InferenceRecord(
            trace_id=row["trace_id"],
            message_id=row["message_id"] or "",
            session_id=row["session_id"] or "",
            query=row["query"] or "",
            retrieved_docs=json.loads(row["retrieved_docs"] or "[]"),
            answer=row["answer"] or "",
            reasoning=row["reasoning"] or "",
            route=row["route"] or "",
            prompt_profile=row["prompt_profile"] or "",
            intent=row["intent"] or "",
            latency_ms=row["latency_ms"] or 0.0,
            token_usage=json.loads(row["token_usage"] or "{}"),
            git_commit=row["git_commit"] or "",
            sampled=bool(row["sampled"]),
            created_at=row["created_at"],
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_store: InferenceStore | None = None
_store_lock = threading.Lock()


def get_inference_store() -> InferenceStore:
    """Get the shared InferenceStore singleton."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = InferenceStore()
    return _store
