"""
Embedding model version registry.

Binds each Milvus collection to the embedding model + dimension that produced
its vectors, so a silent model swap (which would put query vectors in a
different space from stored vectors) is detected instead of silently
corroding retrieval quality.

Storage: SQLite at ``./data/embedding_registry.db``. The fingerprint is a
short hash of ``(model_name, dimension)``. On collection creation we record
the fingerprint; on search we compare the current embedding config against the
recorded one and emit a prominent warning when they diverge.

Compatibility is a correctness gate. Existing collections without a registry
record, or with a mismatched model/dimension/sparse capability, are blocked
until they are rebuilt into a collection registered with the effective model.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading

from utils.log_utils import log

__all__ = [
    "fingerprint",
    "EmbeddingRegistry",
    "get_registry",
    "reset_embedding_registry",
    "check_collection_compatible",
    "DEFAULT_DB_PATH",
]

# Module-level path attribute (AGENTS.md §6/§10 persistence contract) so
# tests/conftest.py and tests/e2e_ui/_fakes.py can redirect it to tmp_path.
DEFAULT_DB_PATH = os.getenv("EMBEDDING_REGISTRY_DB", "./data/embedding_registry.db")


def fingerprint(model_name: str, dimension: int, sparse_enabled: bool = False) -> str:
    """Stable short fingerprint for an embedding model + dimension pair."""
    raw = f"{model_name}|{int(dimension)}|sparse={int(sparse_enabled)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _legacy_fingerprint(model_name: str, dimension: int) -> str:
    raw = f"{model_name}|{int(dimension)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


class EmbeddingRegistry:
    """Thread-safe SQLite registry of embedding fingerprints per collection."""

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = DEFAULT_DB_PATH
        self._db_path = db_path
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS embedding_registry (
                collection    TEXT PRIMARY KEY,
                fingerprint   TEXT,
                model         TEXT,
                dimension     INTEGER,
                sparse_enabled INTEGER NOT NULL DEFAULT 0,
                created_at    REAL,
                updated_at    REAL
            )
            """
        )
        columns = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(embedding_registry)")
        }
        if "sparse_enabled" not in columns:
            self._conn.execute(
                "ALTER TABLE embedding_registry ADD COLUMN sparse_enabled INTEGER NOT NULL DEFAULT 0"
            )
        self._conn.commit()

    def register(
        self,
        collection: str,
        model_name: str,
        dimension: int,
        sparse_enabled: bool = False,
    ) -> str:
        """Record (or update) the embedding fingerprint for a collection."""
        fp = fingerprint(model_name, dimension, sparse_enabled)
        import time

        now = time.time()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO embedding_registry
                    (collection, fingerprint, model, dimension, sparse_enabled,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(collection) DO UPDATE SET
                    fingerprint = excluded.fingerprint,
                    model = excluded.model,
                    dimension = excluded.dimension,
                    sparse_enabled = excluded.sparse_enabled,
                    updated_at = excluded.updated_at
                """,
                (collection, fp, model_name, int(dimension), int(sparse_enabled), now, now),
            )
            self._conn.commit()
        log.info(f"EmbeddingRegistry: {collection} -> {model_name} dim={dimension} (fp={fp})")
        return fp

    def get(self, collection: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM embedding_registry WHERE collection = ?",
                (collection,),
            ).fetchone()
        return dict(row) if row else None

    def is_compatible(
        self,
        collection: str,
        model_name: str,
        dimension: int,
        sparse_enabled: bool = False,
    ) -> bool:
        """True when the current embedding config matches a recorded collection."""
        return self.compatibility(collection, model_name, dimension, sparse_enabled)["compatible"]

    def compatibility(
        self,
        collection: str,
        model_name: str,
        dimension: int,
        sparse_enabled: bool = False,
    ) -> dict:
        """Return a safe, structured compatibility verdict for an existing collection."""
        record = self.get(collection)
        if record is None:
            return {
                "compatible": False,
                "reason": "registry_missing",
                "record": None,
            }
        expected = fingerprint(model_name, dimension, sparse_enabled)
        if (
            record["model"] == model_name
            and int(record["dimension"]) == int(dimension)
            and record["fingerprint"] == _legacy_fingerprint(model_name, dimension)
        ):
            with self._lock:
                self._conn.execute(
                    """
                    UPDATE embedding_registry
                    SET fingerprint = ?, sparse_enabled = ?
                    WHERE collection = ? AND fingerprint = ?
                    """,
                    (expected, int(sparse_enabled), collection, record["fingerprint"]),
                )
                self._conn.commit()
            record = self.get(collection) or record
        if record["fingerprint"] == expected:
            return {
                "compatible": True,
                "reason": "compatible",
                "record": record,
            }
        if record["model"] != model_name:
            reason = "model_mismatch"
        elif int(record["dimension"]) != int(dimension):
            reason = "dimension_mismatch"
        else:
            reason = "sparse_mismatch"
        return {
            "compatible": False,
            "reason": reason,
            "record": record,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_registry: EmbeddingRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> EmbeddingRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = EmbeddingRegistry()
    return _registry


def reset_embedding_registry() -> None:
    global _registry
    with _registry_lock:
        if _registry is not None:
            _registry.close()
        _registry = None


def check_collection_compatible(
    collection: str,
    model_name: str,
    dimension: int,
    sparse_enabled: bool = False,
) -> bool:
    """
    Fail-closed compatibility helper used by vector read/write paths.
    """
    try:
        reg = get_registry()
        verdict = reg.compatibility(collection, model_name, dimension, sparse_enabled)
        if verdict["compatible"]:
            return True
        record = verdict.get("record") or {}
        log.warning(
            f"Embedding collection incompatible for '{collection}' "
            f"({verdict['reason']}): "
            f"current={model_name}/{dimension} vs "
            f"recorded={record.get('model')}/{record.get('dimension')}. "
            f"Stored vectors are in a different space — re-index this collection."
        )
        return False
    except Exception as e:  # noqa: BLE001 - registry failure is degraded, never compatible
        log.warning(f"embedding compatibility registry unavailable: {e}")
        return False
