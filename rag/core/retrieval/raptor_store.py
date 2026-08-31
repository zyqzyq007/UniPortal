"""Transactional, source-scoped RAPTOR summary hierarchy."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from utils.log_utils import log

__all__ = [
    "RAPTOR_DB_PATH",
    "RaptorRetrievalResult",
    "RaptorStore",
    "get_raptor_store",
    "reset_raptor_store",
    "raptor_enabled",
]

RAPTOR_DB_PATH = os.getenv("RAPTOR_DB_PATH", "./data/raptor.db")
_MAX_SUMMARY_CHARS = 1600
_MAX_RAW_CHARS = 8000


@dataclass(frozen=True)
class RaptorRetrievalResult:
    documents: list[Document]
    degraded: bool = False
    error: str | None = None
    generation_count: int = 0


class RaptorStore:
    def __init__(self, db_path: str | os.PathLike[str] | None = None):
        self._db_path = os.fspath(db_path or RAPTOR_DB_PATH)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS source_generations (
                    generation_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    embedding_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('building', 'ready', 'retired')),
                    created_at REAL NOT NULL,
                    ready_at REAL,
                    retired_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_raptor_generation_source
                    ON source_generations(source, status);

                CREATE TABLE IF NOT EXISTS active_generations (
                    source TEXT PRIMARY KEY,
                    generation_id TEXT NOT NULL REFERENCES source_generations(generation_id)
                );

                CREATE TABLE IF NOT EXISTS summary_nodes (
                    generation_id TEXT NOT NULL REFERENCES source_generations(generation_id)
                        ON DELETE CASCADE,
                    node_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    level INTEGER NOT NULL,
                    title_path TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    embedding_json TEXT,
                    PRIMARY KEY (generation_id, node_id)
                );
                CREATE INDEX IF NOT EXISTS idx_raptor_nodes_source
                    ON summary_nodes(source, generation_id);

                CREATE TABLE IF NOT EXISTS node_provenance (
                    generation_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    chunk_text TEXT NOT NULL,
                    parent_id TEXT NOT NULL,
                    PRIMARY KEY (generation_id, node_id, ordinal),
                    FOREIGN KEY (generation_id, node_id)
                        REFERENCES summary_nodes(generation_id, node_id) ON DELETE CASCADE
                );
                PRAGMA user_version = 1;
                """
            )
            self._conn.commit()

    def build_source(
        self,
        source: str,
        documents: list[Document],
        *,
        content_hash: str | None = None,
        embedding_fingerprint: str = "",
        embedding: Any | None = None,
        summarizer: Any | None = None,
    ) -> str:
        generation = self.stage_source(
            source,
            documents,
            content_hash=content_hash,
            embedding_fingerprint=embedding_fingerprint,
            embedding=embedding,
            summarizer=summarizer,
        )
        self.publish_generation(generation)
        return generation

    def stage_source(
        self,
        source: str,
        documents: list[Document],
        *,
        content_hash: str | None = None,
        embedding_fingerprint: str = "",
        embedding: Any | None = None,
        summarizer: Any | None = None,
    ) -> str:
        source = str(source or "").strip()
        if not source:
            raise ValueError("RAPTOR source must not be empty")
        usable = [document for document in documents if document.page_content.strip()]
        if not usable:
            raise ValueError("RAPTOR source has no usable chunks")
        resolved_hash = content_hash or _content_hash(usable)
        generation_id = uuid.uuid4().hex
        nodes = _build_nodes(source, generation_id, usable, summarizer=summarizer)
        if embedding is not None and nodes:
            try:
                vectors = embedding.embed_documents([node["summary"] for node in nodes])
                if len(vectors) != len(nodes):
                    raise ValueError("RAPTOR embedding batch length mismatch")
                for node, vector in zip(nodes, vectors, strict=True):
                    node["embedding_json"] = json.dumps(
                        [float(value) for value in vector],
                        separators=(",", ":"),
                    )
            except Exception as exc:
                log.warning(
                    f"RAPTOR summary embeddings unavailable; lexical retrieval retained: "
                    f"{type(exc).__name__}"
                )
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO source_generations
                        (generation_id, source, content_hash, embedding_fingerprint,
                         status, created_at)
                    VALUES (?, ?, ?, ?, 'building', ?)
                    """,
                    (
                        generation_id,
                        source,
                        resolved_hash,
                        embedding_fingerprint or "",
                        time.time(),
                    ),
                )
                for node in nodes:
                    self._conn.execute(
                        """
                        INSERT INTO summary_nodes
                            (generation_id, node_id, source, level, title_path,
                             summary, embedding_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            generation_id,
                            node["node_id"],
                            source,
                            node["level"],
                            node["title_path"],
                            node["summary"],
                            node.get("embedding_json"),
                        ),
                    )
                    for ordinal, provenance in enumerate(node["provenance"]):
                        self._conn.execute(
                            """
                            INSERT INTO node_provenance
                                (generation_id, node_id, ordinal, chunk_text, parent_id)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                generation_id,
                                node["node_id"],
                                ordinal,
                                provenance[0][:_MAX_RAW_CHARS],
                                provenance[1],
                            ),
                        )
        return generation_id

    def publish_generation(self, generation_id: str) -> None:
        with self._lock:
            with self._conn:
                self._validate_generation(generation_id)
                row = self._conn.execute(
                    "SELECT source, status FROM source_generations WHERE generation_id = ?",
                    (generation_id,),
                ).fetchone()
                if row is None:
                    raise ValueError("RAPTOR generation does not exist")
                if row["status"] != "building":
                    raise ValueError("only a building RAPTOR generation can be published")
                source = row["source"]
                previous = self._conn.execute(
                    "SELECT generation_id FROM active_generations WHERE source = ?",
                    (source,),
                ).fetchone()
                now = time.time()
                if previous is not None and previous["generation_id"] != generation_id:
                    self._conn.execute(
                        """
                        UPDATE source_generations
                        SET status = 'retired', retired_at = ?
                        WHERE generation_id = ? AND status = 'ready'
                        """,
                        (now, previous["generation_id"]),
                    )
                self._conn.execute(
                    """
                    UPDATE source_generations
                    SET status = 'ready', ready_at = ?, retired_at = NULL
                    WHERE generation_id = ?
                    """,
                    (now, generation_id),
                )
                self._conn.execute(
                    """
                    INSERT INTO active_generations(source, generation_id)
                    VALUES (?, ?)
                    ON CONFLICT(source) DO UPDATE SET generation_id = excluded.generation_id
                    """,
                    (source, generation_id),
                )

    def _validate_generation(self, generation_id: str) -> None:
        count = self._conn.execute(
            "SELECT COUNT(*) AS count FROM summary_nodes WHERE generation_id = ?",
            (generation_id,),
        ).fetchone()["count"]
        if count <= 0:
            raise RuntimeError("RAPTOR generation has no summary nodes")
        missing = self._conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM summary_nodes n
            WHERE n.generation_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM node_provenance p
                  WHERE p.generation_id = n.generation_id AND p.node_id = n.node_id
              )
            """,
            (generation_id,),
        ).fetchone()["count"]
        if missing:
            raise RuntimeError("RAPTOR generation has summary nodes without raw provenance")

    def generation_status(self, generation_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM source_generations WHERE generation_id = ?",
                (generation_id,),
            ).fetchone()
        return row["status"] if row else None

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        filter_expr: str | None = None,
        current_content_hash: str | None = None,
        embedding_fingerprint: str | None = None,
        embedding: Any | None = None,
    ) -> RaptorRetrievalResult:
        from core.retrieval.filter_scope import FilterCapability, FilterKind, FilterScope

        scope = FilterScope.parse(filter_expr)
        if scope.kind is FilterKind.INVALID or not scope.supports(FilterCapability.SOURCE_SET):
            return RaptorRetrievalResult([], degraded=True, error="unsupported_filter")
        try:
            with self._lock:
                clauses = ["g.status = 'ready'"]
                params: list[Any] = []
                if scope.sources:
                    placeholders = ",".join("?" for _ in scope.sources)
                    clauses.append(f"g.source IN ({placeholders})")
                    params.extend(sorted(scope.sources))
                if current_content_hash is not None:
                    clauses.append("g.content_hash = ?")
                    params.append(current_content_hash)
                if embedding_fingerprint is not None:
                    clauses.append("g.embedding_fingerprint = ?")
                    params.append(embedding_fingerprint)
                rows = self._conn.execute(
                    f"""
                    SELECT n.*, g.content_hash, g.embedding_fingerprint
                    FROM active_generations a
                    JOIN source_generations g ON g.generation_id = a.generation_id
                    JOIN summary_nodes n ON n.generation_id = g.generation_id
                    WHERE {" AND ".join(clauses)}
                    """,
                    params,
                ).fetchall()
                active_count = self._active_count(scope.sources)
                if not rows:
                    stale_requested = (
                        current_content_hash is not None or embedding_fingerprint is not None
                    ) and active_count > 0
                    return RaptorRetrievalResult(
                        [],
                        degraded=stale_requested,
                        error="raptor_stale" if stale_requested else None,
                    )
                scored = self._score_rows(query, rows, embedding)
                documents: list[Document] = []
                seen: set[tuple[str, str]] = set()
                for score, row in scored:
                    provenance = self._conn.execute(
                        """
                        SELECT chunk_text, parent_id FROM node_provenance
                        WHERE generation_id = ? AND node_id = ? ORDER BY ordinal
                        """,
                        (row["generation_id"], row["node_id"]),
                    ).fetchall()
                    for item in provenance:
                        key = (row["source"], item["chunk_text"])
                        if key in seen:
                            continue
                        seen.add(key)
                        documents.append(
                            Document(
                                page_content=item["chunk_text"],
                                metadata={
                                    "source": row["source"],
                                    "parent_id": item["parent_id"] or "",
                                    "retrieval_source": "raptor",
                                    "raptor_node_id": row["node_id"],
                                    "raptor_level": row["level"],
                                    "raptor_summary": row["summary"],
                                    "raptor_score": score,
                                    "score": score,
                                },
                            )
                        )
                        if len(documents) >= max(1, int(top_k)):
                            return RaptorRetrievalResult(
                                documents,
                                generation_count=active_count,
                            )
                return RaptorRetrievalResult(documents, generation_count=active_count)
        except Exception as exc:
            log.warning(f"RAPTOR retrieval unavailable: {type(exc).__name__}")
            return RaptorRetrievalResult([], degraded=True, error="raptor_unavailable")

    def _score_rows(
        self,
        query: str,
        rows: list[sqlite3.Row],
        embedding: Any | None,
    ) -> list[tuple[float, sqlite3.Row]]:
        if embedding is not None and all(row["embedding_json"] for row in rows):
            try:
                import numpy as np

                query_vector = np.asarray(embedding.embed_query(query), dtype=np.float32)
                query_norm = float(np.linalg.norm(query_vector)) or 1.0
                scored = []
                for row in rows:
                    vector = np.asarray(json.loads(row["embedding_json"]), dtype=np.float32)
                    denominator = query_norm * (float(np.linalg.norm(vector)) or 1.0)
                    scored.append((float(np.dot(query_vector, vector) / denominator), row))
                return sorted(scored, key=lambda item: item[0], reverse=True)
            except Exception:
                pass
        query_terms = _terms(query)
        scored = []
        for row in rows:
            summary_terms = _terms(row["summary"])
            overlap = len(query_terms & summary_terms)
            substring = 1 if query.strip().casefold() in row["summary"].casefold() else 0
            if not overlap and not substring:
                continue
            score = (overlap + substring) / max(1, len(query_terms) + 1)
            scored.append((float(score), row))
        return sorted(scored, key=lambda item: (item[0], item[1]["level"]), reverse=True)

    def _active_count(self, sources: frozenset[str]) -> int:
        if sources:
            placeholders = ",".join("?" for _ in sources)
            return int(
                self._conn.execute(
                    f"SELECT COUNT(*) AS count FROM active_generations WHERE source IN ({placeholders})",
                    tuple(sorted(sources)),
                ).fetchone()["count"]
            )
        return int(
            self._conn.execute("SELECT COUNT(*) AS count FROM active_generations").fetchone()[
                "count"
            ]
        )

    def remove_by_source(self, source: str) -> int:
        if not source:
            return 0
        with self._lock:
            with self._conn:
                existed = self._conn.execute(
                    "SELECT 1 FROM active_generations WHERE source = ?",
                    (source,),
                ).fetchone()
                self._conn.execute("DELETE FROM active_generations WHERE source = ?", (source,))
                generation_ids = [
                    row["generation_id"]
                    for row in self._conn.execute(
                        "SELECT generation_id FROM source_generations WHERE source = ?",
                        (source,),
                    ).fetchall()
                ]
                for generation_id in generation_ids:
                    self._conn.execute(
                        "DELETE FROM source_generations WHERE generation_id = ?",
                        (generation_id,),
                    )
        return 1 if existed else 0

    def collect_garbage(self, *, older_than_seconds: float = 3600) -> int:
        cutoff = time.time() - max(0, older_than_seconds)
        with self._lock:
            with self._conn:
                rows = self._conn.execute(
                    """
                    SELECT generation_id FROM source_generations
                    WHERE status IN ('retired', 'building') AND created_at < ?
                      AND generation_id NOT IN (SELECT generation_id FROM active_generations)
                    """,
                    (cutoff,),
                ).fetchall()
                for row in rows:
                    self._conn.execute(
                        "DELETE FROM source_generations WHERE generation_id = ?",
                        (row["generation_id"],),
                    )
        return len(rows)

    def close(self) -> None:
        with self._lock:
            connection = getattr(self, "_conn", None)
            if connection is None:
                return
            self._conn = None
            connection.close()


def _content_hash(documents: list[Document]) -> str:
    digest = hashlib.sha256()
    for document in documents:
        digest.update(" ".join(document.page_content.split()).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _extractive_summary(texts: list[str]) -> str:
    parts: list[str] = []
    for text in texts:
        normalized = " ".join(text.split())
        if not normalized:
            continue
        parts.append(normalized[:600])
        if sum(len(part) for part in parts) >= _MAX_SUMMARY_CHARS:
            break
    return " ".join(parts)[:_MAX_SUMMARY_CHARS]


def _build_nodes(
    source: str,
    generation_id: str,
    documents: list[Document],
    *,
    summarizer: Any | None,
) -> list[dict[str, Any]]:
    groups: dict[str, list[Document]] = {}
    for index, document in enumerate(documents):
        metadata = document.metadata or {}
        title_path = str(metadata.get("title_path") or "").strip()
        if not title_path and metadata.get("page") not in (None, ""):
            title_path = f"page:{metadata['page']}"
        groups.setdefault(title_path or f"document:{index // 8}", []).append(document)
    nodes: list[dict[str, Any]] = []
    all_provenance: list[tuple[str, str]] = []
    section_summaries: list[str] = []
    for title_path, group in groups.items():
        texts = [document.page_content for document in group]
        summary = _summarize(texts, summarizer)
        section_summaries.append(summary)
        provenance = [
            (document.page_content, str((document.metadata or {}).get("parent_id") or ""))
            for document in group
        ]
        all_provenance.extend(provenance)
        node_id = hashlib.sha1(f"1:{title_path}".encode()).hexdigest()[:16]
        nodes.append(
            {
                "generation_id": generation_id,
                "node_id": node_id,
                "level": 1,
                "title_path": title_path,
                "summary": summary,
                "provenance": provenance,
            }
        )
    if len(nodes) > 1:
        nodes.append(
            {
                "generation_id": generation_id,
                "node_id": hashlib.sha1(f"2:{source}".encode()).hexdigest()[:16],
                "level": 2,
                "title_path": "document",
                "summary": _summarize(section_summaries, summarizer),
                "provenance": all_provenance,
            }
        )
    return nodes


def _summarize(texts: list[str], summarizer: Any | None) -> str:
    if summarizer is not None:
        try:
            value = summarizer(texts)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())[:_MAX_SUMMARY_CHARS]
        except Exception:
            pass
    return _extractive_summary(texts)


def _terms(text: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text or "")
        if token.strip()
    }


_store: RaptorStore | None = None
_store_lock = threading.Lock()


def get_raptor_store() -> RaptorStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = RaptorStore(RAPTOR_DB_PATH)
    return _store


def reset_raptor_store() -> None:
    global _store
    previous = _store
    _store = None
    if previous is not None:
        try:
            previous.close()
        except Exception:
            pass


def raptor_enabled() -> bool:
    return os.getenv("RAPTOR_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
