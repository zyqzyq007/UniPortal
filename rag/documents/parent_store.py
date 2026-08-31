"""
Parent-document store for small-to-big retrieval.

Industrial RAG retrieves with SMALL chunks (precise semantic match) but feeds
the generator the BIGGER context that surrounds the match (a full section /
paragraph) so the answer has complete context rather than a fragment.

This store keeps the mapping ``child chunk -> parent text`` in SQLite. The
retriever stores small chunks in Milvus with a ``parent_id`` metadata field;
``expand_to_parents`` then turns a list of small-chunk hits into their parent
documents (de-duplicated), preserving the child's relevance score on the
parent.

Keyed by ``parent_id`` which is stable per (source file, section index) — so
re-indexing the same source regenerates the same parent ids.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading

from langchain_core.documents import Document

from utils.log_utils import log

__all__ = [
    "ParentStore",
    "make_parent_id",
    "expand_to_parents",
    "get_parent_store",
]

# Module-level path so tests/conftest.py can redirect it to tmp_path
# (AGENTS.md §6/§10 persistence contract).
DEFAULT_DB_PATH = "./data/parent_store.db"


def make_parent_id(source: str, section_index: int) -> str:
    """Stable parent id for a (source, section index) pair."""
    raw = f"{source}::{int(section_index)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class ParentStore:
    """Thread-safe SQLite store of parent documents keyed by parent_id."""

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
            CREATE TABLE IF NOT EXISTS parents (
                parent_id   TEXT PRIMARY KEY,
                source      TEXT,
                title       TEXT,
                content     TEXT,
                created_at  REAL
            )
            """
        )
        self._conn.commit()

    def store(self, parent_id: str, content: str, source: str = "", title: str = "") -> None:
        import time

        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO parents (parent_id, source, title, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (parent_id, source, title, content, time.time()),
            )
            self._conn.commit()

    def get(self, parent_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM parents WHERE parent_id = ?",
                (parent_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_many(self, parent_ids: list[str]) -> dict[str, dict]:
        if not parent_ids:
            return {}
        placeholders = ",".join("?" for _ in parent_ids)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM parents WHERE parent_id IN ({placeholders})",
                parent_ids,
            ).fetchall()
        return {r["parent_id"]: dict(r) for r in rows}

    def list_all(self) -> list[dict]:
        """Return every persisted parent section for offline re-indexing."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT parent_id, source, title, content FROM parents ORDER BY parent_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        with self._lock:
            conn = getattr(self, "_conn", None)
            if conn is None:
                return
            self._conn = None
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


_store: ParentStore | None = None
_store_lock = threading.Lock()


def get_parent_store() -> ParentStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = ParentStore()
    return _store


def reset_parent_store() -> None:
    """Close and clear the shared singleton (mainly for tests)."""
    global _store
    if _store is not None:
        _store.close()
    _store = None


def expand_to_parents(
    children: list[Document],
    top_k: int | None = None,
) -> list[Document]:
    """
    Expand small-chunk hits to their parent documents.

    Args:
        children: retrieved small chunks; each should carry
            ``metadata["parent_id"]``. Chunks without a parent_id are passed
            through unchanged.
        top_k: cap on the number of returned parents (after de-dup).

    Returns:
        De-duplicated parent documents (preserving the highest child score on
        each parent), followed by any child that had no parent_id. Order is by
        descending child score.
    """
    if not children:
        return []

    # Group children by parent_id; track the best (max) score per parent.
    parent_best: dict[str, float | None] = {}
    parent_first: dict[str, Document] = {}
    orphans: list[Document] = []

    for child in children:
        pid = None
        if isinstance(child.metadata, dict):
            pid = child.metadata.get("parent_id")
        if not pid:
            orphans.append(child)
            continue
        score = _norm(child.metadata.get("score"))
        current = parent_best.get(pid)
        if pid not in parent_best or (score is not None and (current is None or score > current)):
            parent_best[pid] = score
            parent_first[pid] = child

    if not parent_best:
        return orphans[:top_k] if top_k else orphans

    # Fetch parent texts.
    try:
        store = get_parent_store()
        parents = store.get_many(list(parent_best.keys()))
    except Exception as e:  # noqa: BLE001
        log.debug(f"parent store unavailable, returning children: {e}")
        return children[:top_k] if top_k else children

    # Build parent Documents, sorted by best child score desc.
    scored_pids = sorted(
        (pid for pid, score in parent_best.items() if score is not None),
        key=lambda pid: parent_best[pid],
        reverse=True,
    )
    ordered_pids = scored_pids + [pid for pid, score in parent_best.items() if score is None]
    expanded: list[Document] = []
    for pid in ordered_pids:
        parent = parents.get(pid)
        if not parent:
            # Parent text missing — fall back to the child chunk itself.
            expanded.append(parent_first[pid])
            continue
        child_meta = dict(parent_first[pid].metadata)
        score = parent_best[pid]
        if score is None:
            child_meta.pop("score", None)
        else:
            child_meta["score"] = score
        child_meta["parent_id"] = pid
        child_meta["expanded_from_child"] = True
        expanded.append(Document(page_content=parent["content"], metadata=child_meta))

    # Append orphans (children without parent_id) after parents.
    expanded.extend(orphans)

    if top_k:
        expanded = expanded[:top_k]
    return expanded


def _norm(s) -> float | None:
    from core.retrieval.scoring import finite_real

    return finite_real(s)
