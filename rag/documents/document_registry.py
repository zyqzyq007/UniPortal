"""
Document Registry - Persistent document metadata storage.

Uses SQLite to persist document metadata across server restarts.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Literal

from utils.log_utils import log

# Module-level path so tests/conftest.py can redirect it to tmp_path
# (AGENTS.md §6/§10 persistence contract).
DEFAULT_DB_PATH = "./data/documents.db"

# 文档处理状态：上传后后台分块/向量化/索引的生命周期取值
DocumentStatus = Literal["processing", "indexed", "failed"]


class DocumentRegistry:
    """
    SQLite-backed persistent document registry.

    Stores document metadata (id, filename, status, chunks, file_hash, etc.)
    so that document tracking survives server restarts.
    """

    def __init__(self, db_path: str | None = None):
        # Resolve lazily from the module attribute so tests/conftest.py and the
        # Playwright fakes harness can redirect DEFAULT_DB_PATH at runtime
        # (AGENTS.md §6/§10 persistence path-sealability). A default-arg bound
        # at def time would freeze the original path and leak real-data reads.
        if db_path is None:
            db_path = DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'processing',
                chunks INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                file_hash TEXT NOT NULL DEFAULT ''
            )"""
        )
        self._conn.commit()
        log.info(f"Document registry initialized: {db_path}")

    def put(
        self,
        doc_id: str,
        filename: str,
        status: DocumentStatus,
        chunks: int,
        created_at: float,
        size_bytes: int,
        file_hash: str,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO documents "
            "(id, filename, status, chunks, created_at, size_bytes, file_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (doc_id, filename, status, chunks, created_at, size_bytes, file_hash),
        )
        self._conn.commit()

    def get(self, doc_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return dict(row) if row else None

    def find_by_filename(self, filename: str) -> dict | None:
        """Find document by exact filename."""
        row = self._conn.execute(
            "SELECT * FROM documents WHERE filename = ? LIMIT 1", (filename,)
        ).fetchone()
        return dict(row) if row else None

    def find_by_file_hash(self, file_hash: str) -> dict | None:
        """Find document by exact file hash."""
        row = self._conn.execute(
            "SELECT * FROM documents WHERE file_hash = ? LIMIT 1", (file_hash,)
        ).fetchone()
        return dict(row) if row else None

    def update_status(self, doc_id: str, status: DocumentStatus, chunks: int = 0) -> None:
        self._conn.execute(
            "UPDATE documents SET status = ?, chunks = ? WHERE id = ?",
            (status, chunks, doc_id),
        )
        self._conn.commit()

    def delete(self, doc_id: str) -> bool:
        cursor = self._conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    def list_all(self, skip: int = 0, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM documents ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, skip),
        ).fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()
        return row[0] if row else 0

    def contains(self, doc_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM documents WHERE id = ? LIMIT 1", (doc_id,)
        ).fetchone()
        return row is not None

    def close(self) -> None:
        """Close the underlying SQLite connection. Idempotent."""
        conn = getattr(self, "_conn", None)
        if conn is None:
            return
        self._conn = None
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


# Module-level singleton
_registry: DocumentRegistry | None = None


def get_document_registry() -> DocumentRegistry:
    """Get or create the document registry singleton."""
    global _registry
    if _registry is None:
        _registry = DocumentRegistry()
    return _registry


def reset_document_registry() -> None:
    """Close and clear the shared singleton (mainly for tests)."""
    global _registry
    if _registry is not None:
        _registry.close()
    _registry = None
