from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from agent.memory.types import MemoryEntry, MemoryQuery, MemoryType
from utils.log_utils import log

# Module-level path so tests/conftest.py can redirect it to tmp_path
# (AGENTS.md §6/§10 persistence contract). Shared with FeedbackCollector.
DEFAULT_DB_PATH = "./data/agent_memory.db"


class MemoryStore:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # WAL improves concurrent reader/writer throughput on the shared file
        # (this store shares agent_memory.db with FeedbackCollector).
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
        except Exception as e:  # noqa: BLE001 - WAL is best-effort
            log.debug(f"MemoryStore: WAL mode unavailable: {e}")
        # Guard all cursor/commit access: the single shared connection is used
        # from multiple hook callbacks (and across threads), so unsynchronised
        # commits can interleave and raise "database is locked" / corrupt
        # cursor state. inference_store fixed this; MemoryStore had not.
        self._lock = threading.RLock()
        with self._lock:
            self._init_table()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Hold the connection lock for a DB transaction."""
        with self._lock:
            yield

    def _init_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_memory (
                id TEXT PRIMARY KEY,
                memory_type TEXT,
                content TEXT,
                metadata_json TEXT,
                created_at REAL,
                access_count INT DEFAULT 0,
                relevance_score REAL DEFAULT 1.0
            )
        """)
        self._conn.commit()

    def store(self, entry: MemoryEntry) -> str:
        with self._locked():
            self._conn.execute(
                "INSERT INTO agent_memory (id, memory_type, content, metadata_json, created_at, access_count, relevance_score) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.id,
                    entry.memory_type.value,
                    entry.content,
                    json.dumps(entry.metadata),
                    entry.created_at,
                    entry.access_count,
                    entry.relevance_score,
                ),
            )
            self._conn.commit()
        log.debug(f"MemoryStore: stored memory {entry.id}")
        return entry.id

    def retrieve(self, query: MemoryQuery) -> list[MemoryEntry]:
        """
        Retrieve memories matching the query.

        Uses semantic (embedding) retrieval when available, falling back to
        the legacy SQL LIKE substring match if embeddings are unavailable.
        """
        # Try semantic retrieval first (handles synonyms / paraphrases that
        # a substring LIKE match would miss).
        try:
            semantic = self.retrieve_semantic(query)
            if semantic is not None:
                return semantic
        except Exception as e:  # noqa: BLE001
            log.debug(f"Semantic memory retrieve unavailable, using LIKE: {e}")

        return self._retrieve_like(query)

    def retrieve_semantic(self, query: MemoryQuery) -> list[MemoryEntry] | None:
        """
        Embedding-based semantic retrieval. Returns None when embeddings are
        unavailable (caller falls back to LIKE).

        The expensive embedding step runs outside the connection lock; only the
        candidate fetch and the access-count write-back are locked.
        """
        # Gather candidates with a broad LIKE (or all rows for small stores),
        # then re-rank by embedding cosine similarity.
        sql = "SELECT * FROM agent_memory"
        params: list = []
        if query.memory_types:
            placeholders = ",".join("?" for _ in query.memory_types)
            sql += f" WHERE memory_type IN ({placeholders})"
            params.extend(mt.value for mt in query.memory_types)
        sql += " LIMIT 500"
        with self._locked():
            rows = self._conn.execute(sql, params).fetchall()
        if not rows:
            return []

        try:
            import numpy as np

            from models.embedding_models import get_local_embeddings

            emb = get_local_embeddings()
            contents = [r["content"] for r in rows]
            doc_vecs = np.asarray(emb.embed_documents(contents), dtype=np.float32)
            q_vec = np.asarray(emb.embed_query(query.query), dtype=np.float32)
            q_norm = np.linalg.norm(q_vec) or 1.0
            sims = (doc_vecs @ q_vec) / (np.linalg.norm(doc_vecs, axis=1) * q_norm + 1e-9)
        except Exception as e:  # noqa: BLE001
            log.debug(f"Embedding retrieval failed: {e}")
            return None  # signal fallback

        # Rank by similarity, take top results.
        ranked = sorted(enumerate(rows), key=lambda x: sims[x[0]], reverse=True)
        results = []
        with self._locked():
            for idx, row in ranked[: query.limit]:
                entry = self._row_to_entry(row)
                # Boost access count for retrieved memories.
                self._conn.execute(
                    "UPDATE agent_memory SET access_count = access_count + 1 WHERE id = ?",
                    (entry.id,),
                )
                results.append(entry)
            self._conn.commit()
        return results

    def _retrieve_like(self, query: MemoryQuery) -> list[MemoryEntry]:
        """Legacy substring (LIKE) retrieval — the original implementation."""
        sql = "SELECT * FROM agent_memory WHERE content LIKE ?"
        params: list = [f"%{query.query}%"]

        if query.min_relevance > 0:
            sql += " AND relevance_score >= ?"
            params.append(query.min_relevance)

        if query.memory_types:
            placeholders = ",".join("?" for _ in query.memory_types)
            sql += f" AND memory_type IN ({placeholders})"
            params.extend(mt.value for mt in query.memory_types)

        sql += " ORDER BY relevance_score DESC, access_count DESC LIMIT ?"
        params.append(query.limit)

        with self._locked():
            rows = self._conn.execute(sql, params).fetchall()

            results = []
            for row in rows:
                entry = self._row_to_entry(row)
                self._conn.execute(
                    "UPDATE agent_memory SET access_count = access_count + 1 WHERE id = ?",
                    (entry.id,),
                )
                results.append(entry)
            self._conn.commit()
        return results

    def update(self, id: str, updates: dict) -> bool:
        if not updates:
            return False
        set_clauses = []
        values = []
        for key, val in updates.items():
            if key == "metadata":
                set_clauses.append("metadata_json = ?")
                values.append(json.dumps(val))
            elif key == "memory_type":
                set_clauses.append("memory_type = ?")
                values.append(val.value if isinstance(val, MemoryType) else val)
            else:
                set_clauses.append(f"{key} = ?")
                values.append(val)
        values.append(id)
        with self._locked():
            cursor = self._conn.execute(
                f"UPDATE agent_memory SET {', '.join(set_clauses)} WHERE id = ?",
                values,
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def delete(self, id: str) -> bool:
        with self._locked():
            cursor = self._conn.execute("DELETE FROM agent_memory WHERE id = ?", (id,))
            self._conn.commit()
            return cursor.rowcount > 0

    def get_by_id(self, id: str) -> MemoryEntry | None:
        with self._locked():
            row = self._conn.execute("SELECT * FROM agent_memory WHERE id = ?", (id,)).fetchone()
            return self._row_to_entry(row) if row else None

    def _row_to_entry(self, row) -> MemoryEntry:
        return MemoryEntry(
            id=row["id"],
            memory_type=MemoryType(row["memory_type"]),
            content=row["content"],
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
            created_at=row["created_at"],
            access_count=row["access_count"],
            relevance_score=row["relevance_score"],
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


_memory_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore()
    return _memory_store


def reset_memory_store() -> None:
    """Close and clear the shared singleton (mainly for tests)."""
    global _memory_store
    if _memory_store is not None:
        _memory_store.close()
    _memory_store = None
