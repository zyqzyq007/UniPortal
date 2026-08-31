"""
Graph retrieval leg for the hybrid retriever (GraphRAG / LightRAG-inspired).

Provides the third RRF leg: dual-level retrieval over the entity/relation graph
stored by :class:`documents.graph_store.GraphStore`.

Dual-level retrieval (design.md v2 §5.2):

- **low-level**: query embedding → cosine against the in-memory entity vector
  matrix → top entities → their backing original chunk text (F-06 parent_id
  preserved so ``expand_to_parents`` can still widen the context).
- **high-level**: seed entities (low-level hits ∪ query-keyword entity-name
  matches) → 1-hop relation neighbours (F-08: independent seed so an empty
  low-level does not blank out high-level) → neighbour chunks with decay.

The two levels are fused by a local RRF, then the result Documents carry
``metadata["source"]`` / ``metadata["parent_id"]`` / ``metadata[
"retrieval_source"] = "graph"`` and are source-filtered when the caller passes
a ``filter_expr`` (F-01 — filter is a first-class retrieval contract).

Concurrency (F-02): the entity vector matrix is updated copy-on-write —
``retrieve`` reads a snapshot reference without holding the lock; writers
(``add_documents`` / ``remove_by_source`` / ``reload``) build a fresh matrix and
atomically swap the reference under the lock.

Cold start (F-05): the matrix is lazily rebuilt from the store on first
``retrieve`` if empty (mirrors BM25's ``_ensure_sparse_indexed``), so a process
restart recovers without a re-ingestion.

Degradation (REQ-GR-003): empty graph / embedding failure / SQL error /
fingerprint mismatch → returns ``[]`` with ``degraded=True``; never raises and
never reports "unavailable" as score 0.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import numpy as np
from langchain_core.documents import Document

from documents.graph_store import GraphStore, get_graph_store
from utils.log_utils import log

if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings

__all__ = [
    "GraphRetriever",
    "get_graph_retriever",
    "reset_graph_retriever",
]

# Neighbour score decay: a 1-hop hit contributes at most this fraction of its
# seed's score, keeping precise low-level hits above noisier high-hop ones.
NEIGHBOR_DECAY = 0.5

# Local RRF constant for fusing low-level + high-level within the graph leg.
# Independent of the outer hybrid retriever's k (graph results are re-fused
# there with dense/sparse).
GRAPH_RRF_K = 60


class GraphRetriever:
    """Dual-level graph retrieval over a :class:`GraphStore`."""

    def __init__(
        self,
        store: GraphStore | None = None,
        embedding: Embeddings | None = None,
    ):
        self._store = store
        self._embedding = embedding
        self._lock = threading.RLock()
        # COW matrix state (F-02). ``_matrix`` is replaced atomically by writers;
        # readers grab the current reference and compute without the lock.
        self._matrix: np.ndarray | None = None  # shape (n, dim)
        self._entity_ids: list[str] = []
        self._entity_sources: list[str] = []
        # name→{entity_id} index for the high-level keyword seed (F-08). Built
        # alongside the matrix so _keyword_seeds does not re-scan the store on
        # every query (was a per-query load_all under contention).
        self._name_index: dict[str, set[str]] = {}
        self._loaded = False
        self._degraded = False
        self._fingerprint_ok = True

    # ------------------------------------------------------------------
    # Lazy singletons
    # ------------------------------------------------------------------

    @property
    def store(self) -> GraphStore:
        if self._store is None:
            self._store = get_graph_store()
        return self._store

    @property
    def embedding(self) -> Embeddings:
        if self._embedding is None:
            from models.embedding_models import get_embeddings

            self._embedding = get_embeddings()
        return self._embedding

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filter_expr: str | None = None,
        query_dense: list[float] | np.ndarray | None = None,
        use_ppr: bool = False,
        facets: tuple[str, ...] = (),
    ) -> list:
        """Run dual-level retrieval; return ``list[RetrievalResult]``.

        Never raises (REQ-GR-003). On any failure returns ``[]`` and sets
        ``self._degraded = True``. ``filter_expr`` constrains results to the
        matching source(s) (F-01).
        """
        try:
            from core.retrieval.filter_scope import FilterCapability, FilterScope

            scope = FilterScope.parse(filter_expr)
            if not scope.supports(FilterCapability.SOURCE_SET):
                self._degraded = True
                return []
            allowed_sources = set(scope.sources) if scope.sources else None
            self._ensure_loaded()
            if use_ppr:
                return self._ppr_results(
                    query,
                    top_k,
                    allowed_sources,
                    query_dense=query_dense,
                    facets=facets,
                )
            if self._matrix is None or len(self._entity_ids) == 0:
                return []  # empty graph is a valid, non-degraded empty result

            q_emb = np.asarray(
                query_dense if query_dense is not None else self.embedding.embed_query(query),
                dtype=np.float32,
            )
            low_docs = self._low_level(q_emb, top_k, allowed_sources)
            high_docs = self._high_level(query, q_emb, top_k, allowed_sources)
            fused = self._fuse_low_high(low_docs, high_docs, top_k)
            return self._to_results(fused)
        except Exception as exc:  # noqa: BLE001 — degrade, never raise
            log.warning(f"graph retrieve degraded: {exc}")
            self._degraded = True
            return []

    def _ppr_results(
        self,
        query: str,
        top_k: int,
        allowed_sources: set[str] | None,
        *,
        query_dense: list[float] | np.ndarray | None,
        facets: tuple[str, ...],
    ) -> list:
        from core.retrieval.graph_ppr import bounded_shortest_paths, personalized_pagerank

        adjacency = self.store.source_graph(allowed_sources=allowed_sources)
        if not adjacency:
            return []
        scoped_ids = sorted(adjacency)
        seeds = self._keyword_seeds(query, scoped_ids)
        for facet in facets:
            seeds |= self._keyword_seeds(facet, scoped_ids)
        matrix, ids, sources = self._matrix_snapshot()
        if matrix is not None and query_dense is not None:
            indices = [
                index
                for index, entity_id in enumerate(ids)
                if entity_id in adjacency
                and (allowed_sources is None or sources[index] in allowed_sources)
            ]
            if indices:
                scoped_matrix = matrix[indices]
                semantic_ids = [ids[index] for index in indices]
                seeds |= self._semantic_seeds(
                    np.asarray(query_dense, dtype=np.float32),
                    semantic_ids,
                    scoped_matrix,
                    min(top_k, 3),
                )
        seeds &= set(adjacency)
        if not seeds:
            return []
        ppr = personalized_pagerank(
            adjacency,
            seeds,
            max_iterations=100,
            tolerance=1e-6,
            max_nodes=5000,
        )
        paths = bounded_shortest_paths(
            adjacency,
            seeds,
            max_depth=3,
            max_paths=max(2, top_k),
        )
        path_for: dict[str, list[str]] = {}
        for path in paths:
            for entity_id in path:
                path_for.setdefault(entity_id, path)
        ordered = sorted(ppr.scores.items(), key=lambda item: (-item[1], item[0]))
        documents: list[Document] = []
        seen: set[tuple[str, str]] = set()
        for entity_id, score in ordered:
            for source, text, parent_id in self.store.chunks_for_entity(
                entity_id,
                allowed_sources=allowed_sources,
            ):
                if not text or (source, text) in seen:
                    continue
                seen.add((source, text))
                documents.append(
                    Document(
                        page_content=text,
                        metadata={
                            "source": source,
                            "parent_id": parent_id,
                            "retrieval_source": "graph",
                            "graph_mode": "ppr",
                            "graph_path": path_for.get(entity_id, []),
                            "entity_id": entity_id,
                            "ppr_score": score,
                            "ppr_converged": ppr.converged,
                            "ppr_iterations": ppr.iterations,
                            "score": score,
                        },
                    )
                )
                if len(documents) >= top_k:
                    return self._to_results(documents)
        return self._to_results(documents)

    def add_documents(self, docs: list[Document]) -> None:
        """Reload the matrix from the store after ingestion writes (F-02 COW)."""
        # docs are informational here; the store is the source of truth. We
        # simply invalidate the cached matrix so the next retrieve rebuilds.
        self._invalidate()

    def remove_by_source(self, source: str) -> None:
        """Invalidate the matrix after a source delete (F-02 COW)."""
        self._invalidate()

    def reload(self) -> int:
        """Force a matrix rebuild from the store; returns entity count."""
        self._loaded = False
        self._ensure_loaded()
        return len(self._entity_ids)

    def status(self) -> dict:
        """Expose health state for ``/api/admin/health`` (mirrors reranker)."""
        return {
            "matrix_loaded": self._loaded,
            "entity_count": len(self._entity_ids),
            "degraded": self._degraded,
            "fingerprint_ok": self._fingerprint_ok,
        }

    # ------------------------------------------------------------------
    # Matrix lifecycle (F-02 COW + F-05 cold start + F-09 fingerprint)
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._build_matrix_locked()
            self._loaded = True

    def _invalidate(self) -> None:
        with self._lock:
            self._loaded = False
            self._matrix = None
            self._entity_ids = []
            self._entity_sources = []
            self._name_index = {}

    def _build_matrix_locked(self) -> None:
        """Rebuild the COW matrix snapshot from the store (caller holds lock)."""
        rows = self.store.load_all()
        if not rows:
            self._matrix = None
            self._entity_ids = []
            self._entity_sources = []
            self._name_index = {}
            return

        # F-09: guard against an embedding-model swap corrupting cosine scores.
        # A dimension mismatch (or unset fingerprint on a legacy store) is
        # treated as degraded-empty rather than crashing mid-cosine.
        dim = self._expected_dim()
        vecs: list[np.ndarray] = []
        ids: list[str] = []
        sources: list[str] = []
        name_index: dict[str, set[str]] = {}
        for r in rows:
            # Build the name→id index from every row (not just embedded ones) so
            # keyword seeds can match entities whose embedding is still pending.
            key = r.name.strip().casefold()
            if key:
                name_index.setdefault(key, set()).add(r.entity_id)
            if not r.embedding:
                continue
            if dim and len(r.embedding) != dim:
                log.warning(
                    f"graph matrix: entity {r.entity_id} dim {len(r.embedding)} "
                    f"!= embedding dim {dim}; skipping rebuild (model drift)"
                )
                # Mark both the fingerprint flag and degraded so admin health
                # surfaces the model-drift condition (previously only
                # fingerprint_ok was set, hiding it from degraded monitoring).
                self._fingerprint_ok = False
                self._degraded = True
                self._matrix = None
                self._entity_ids = []
                self._entity_sources = []
                self._name_index = {}
                return
            vecs.append(np.asarray(r.embedding, dtype=np.float32))
            ids.append(r.entity_id)
            sources.append(r.source)

        if not vecs:
            self._matrix = None
            self._entity_ids = []
            self._entity_sources = []
            self._name_index = name_index  # still useful for keyword seeds
            return

        # Stack into (n, dim). The atomic assignment of all fields under the
        # lock is the COW swap point (F-02).
        self._matrix = np.vstack(vecs)
        self._entity_ids = ids
        self._entity_sources = sources
        self._name_index = name_index
        self._fingerprint_ok = True

    def _expected_dim(self) -> int:
        """Expected embedding dim from the store fingerprint (F-09), 0 if unset."""
        raw = self.store.meta("embedding_dim", "")
        try:
            return int(raw) if raw else 0
        except ValueError:
            return 0

    def _matrix_snapshot(self) -> tuple[np.ndarray, list[str], list[str]]:
        """Grab a consistent COW reference for lock-free cosine (F-02).

        The three fields (matrix, ids, sources) are read under the lock so a
        concurrent ``_invalidate`` cannot swap one field (e.g. clear ids) between
        the reads — which would yield a matrix whose row count no longer matches
        the ids length and cause an IndexError in the downstream cosine. The
        returned matrix is the shared numpy array (immutable during its lifetime
        — writers build a fresh array and swap the reference), so lock-free
        compute on it is safe.
        """
        with self._lock:
            return self._matrix, list(self._entity_ids), list(self._entity_sources)

    # ------------------------------------------------------------------
    # Dual-level retrieval
    # ------------------------------------------------------------------

    def _low_level(
        self,
        q_emb: np.ndarray,
        top_k: int,
        allowed_sources: set[str] | None = None,
    ) -> list[tuple[Document, float]]:
        matrix, ids, _sources = self._matrix_snapshot()
        if matrix is None or not ids:
            return []
        q = q_emb / (np.linalg.norm(q_emb) + 1e-9)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9
        scores = (matrix / norms) @ q  # cosine (n,)

        candidate_indices = [
            index
            for index, source in enumerate(_sources)
            if allowed_sources is None or source in allowed_sources
        ]
        order = sorted(candidate_indices, key=lambda index: float(scores[index]), reverse=True)[
            : top_k * 2
        ]
        # Source-scoped chunk lookup (F-01): the same concept across two manuals
        # is two rows with distinct chunks; key by (entity_id, source).
        lookup_keys = [(ids[i], _sources_row(_sources, ids, i)) for i in order]
        chunk_map = self.store.chunk_text_for(lookup_keys)
        out: list[tuple[Document, float]] = []
        for i in order:
            eid = ids[i]
            src = _sources_row(_sources, ids, i)
            text, parent_id = chunk_map.get((eid, src), ("", ""))
            if not text:
                continue
            out.append(
                (
                    Document(
                        page_content=text,
                        metadata={
                            "source": src,
                            "parent_id": parent_id,
                            "retrieval_source": "graph",
                            "entity_id": eid,
                        },
                    ),
                    float(scores[i]),
                )
            )
            if len(out) >= top_k:
                break
        return out

    def _high_level(
        self,
        query: str,
        q_emb: np.ndarray,
        top_k: int,
        allowed_sources: set[str] | None = None,
    ) -> list[tuple[Document, float]]:
        matrix, ids, sources = self._matrix_snapshot()
        if matrix is None or not ids:
            return []

        indices = [
            index
            for index, source in enumerate(sources)
            if allowed_sources is None or source in allowed_sources
        ]
        if not indices:
            return []
        scoped_matrix = matrix[indices]
        scoped_ids = [ids[index] for index in indices]

        # F-08: seed = low-level semantic hits ∪ query-keyword entity-name hits,
        # so an empty low-level still seeds high-level via name matching.
        seed_ids = self._semantic_seeds(q_emb, scoped_ids, scoped_matrix, top_k)
        seed_ids |= self._keyword_seeds(query, scoped_ids)
        if not seed_ids:
            return []

        neighbors = self.store.neighbors(list(seed_ids), allowed_sources=allowed_sources)
        if not neighbors:
            return []
        # Seed score lookup: cosine of each seed.
        seed_score = self._seed_score_map(q_emb, scoped_ids, scoped_matrix)

        out: list[tuple[Document, float]] = []
        for nb_id, _rtype, weight in neighbors:
            # Fan out to every source the neighbour appears in — F-01 filtering
            # at the Document level keeps only allowed sources.
            for src, text, parent_id in self.store.chunks_for_entity(
                nb_id,
                allowed_sources=allowed_sources,
            ):
                if not text:
                    continue
                base = self._best_seed_score(nb_id, neighbors, seed_score)
                score = base * NEIGHBOR_DECAY * weight
                out.append(
                    (
                        Document(
                            page_content=text,
                            metadata={
                                "source": src,
                                "parent_id": parent_id,
                                "retrieval_source": "graph",
                                "entity_id": nb_id,
                            },
                        ),
                        float(score),
                    )
                )
        out.sort(key=lambda x: x[1], reverse=True)
        return out[:top_k]

    # -- seed helpers --------------------------------------------------

    def _semantic_seeds(
        self, q_emb: np.ndarray, ids: list[str], matrix: np.ndarray, top_k: int
    ) -> set[str]:
        q = q_emb / (np.linalg.norm(q_emb) + 1e-9)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9
        scores = (matrix / norms) @ q
        order = np.argsort(-scores)[: max(top_k, 5)]
        return {ids[i] for i in order}

    def _keyword_seeds(self, query: str, ids: list[str]) -> set[str]:
        """Match query tokens against entity names via the cached name index.

        The index is rebuilt alongside the matrix (F-02 COW), so this is an
        O(tokens) lookup rather than a per-query store scan.
        """
        if not query.strip():
            return set()
        try:
            import jieba

            tokens = {t for t in jieba.lcut(query) if len(t.strip()) > 1}
        except ImportError:
            tokens = {w for w in query.split() if len(w) > 1}
        with self._lock:
            name_index = dict(self._name_index)
        out: set[str] = set()
        for tok in tokens:
            for eid in name_index.get(tok.casefold(), ()):  # noqa: B007
                out.add(eid)
        return out

    def _seed_score_map(
        self, q_emb: np.ndarray, ids: list[str], matrix: np.ndarray
    ) -> dict[str, float]:
        q = q_emb / (np.linalg.norm(q_emb) + 1e-9)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9
        scores = (matrix / norms) @ q
        return {ids[i]: float(scores[i]) for i in range(len(ids))}

    @staticmethod
    def _best_seed_score(
        nb_id: str,
        neighbors: list[tuple[str, str, float]],
        seed_score: dict[str, float],
    ) -> float:
        # neighbours don't carry their own cosine; approximate using the average
        # seed score as the decay base. This is a cheap, stable heuristic.
        if not seed_score:
            return 0.0
        return sum(seed_score.values()) / len(seed_score)

    # ------------------------------------------------------------------
    # Local RRF (low + high) + result mapping
    # ------------------------------------------------------------------

    def _fuse_low_high(
        self,
        low: list[tuple[Document, float]],
        high: list[tuple[Document, float]],
        top_k: int,
    ) -> list[Document]:
        """RRF over the two graph levels keyed by (entity_id, source).

        Keying on the (entity_id, source) pair — not entity_id alone — keeps a
        concept surfaced in two manuals as two distinct results so F-01 source
        filtering can retain the allowed one instead of collapsing both into a
        single arbitrary survivor.
        """
        rrf: dict[tuple[str, str], float] = {}
        docs: dict[tuple[str, str], Document] = {}

        def _key(doc: Document) -> tuple[str, str]:
            return (str(doc.metadata.get("entity_id", "")), str(doc.metadata.get("source", "")))

        for rank, (doc, _score) in enumerate(low):
            k = _key(doc)
            rrf[k] = rrf.get(k, 0.0) + 1.0 / (GRAPH_RRF_K + rank + 1)
            docs[k] = doc
        for rank, (doc, _score) in enumerate(high):
            k = _key(doc)
            rrf[k] = rrf.get(k, 0.0) + 0.8 / (GRAPH_RRF_K + rank + 1)
            docs.setdefault(k, doc)
        ordered = sorted(rrf, key=lambda k: rrf[k], reverse=True)[:top_k]
        return [docs[k] for k in ordered]

    def _to_results(self, documents: list[Document]) -> list:
        """Wrap Documents as the hybrid retriever's RetrievalResult.

        Late import avoids a circular dependency: hybrid_retriever imports this
        module (to call retrieve as the graph leg), so we cannot import
        RetrievalResult at module top level.
        """
        from core.retrieval.hybrid_retriever import RetrievalResult

        results = []
        for rank, doc in enumerate(documents, 1):
            score = float(doc.metadata.get("score", 0.0))
            results.append(RetrievalResult(document=doc, score=score, source="graph", rank=rank))
        return results


# ---------------------------------------------------------------------------
# Filter parsing (F-01)
# ---------------------------------------------------------------------------


def _parse_filter_sources(filter_expr: str | None) -> set[str] | None:
    """Extract the allowed source set from a Milvus-style filter_expr.

    Supports the common shapes produced by the documents/retrieval layer:
    ``source == "x"``, ``source in ["x", "y"]``, ``source == 'x'``.
    Returns ``None`` when the expression cannot be parsed → caller treats it
    as "no filter" (fail-open, never silently drop everything).
    """
    if not filter_expr:
        return None
    expr = filter_expr.strip()

    # source in ["a", "b"]
    import re

    m = re.search(r"source\s+in\s*\[([^\]]*)\]", expr, re.IGNORECASE)
    if m:
        vals = re.findall(r'["\']([^"\']+)["\']', m.group(1))
        return set(vals) if vals else None

    # source == "a"
    m = re.search(r'source\s*==\s*["\']([^"\']+)["\']', expr, re.IGNORECASE)
    if m:
        return {m.group(1)}

    # Unparseable → fail-open (do not filter), log so it is observable.
    log.debug(f"graph filter_expr unparseable, ignored: {filter_expr!r}")
    return None


def _sources_row(sources: list[str], ids: list[str], i: int) -> str:
    """Source for matrix index i (bounds-safe)."""
    if i < len(sources):
        return sources[i]
    return ""


# ---------------------------------------------------------------------------
# Module-level singleton (mirrors bm25_retriever)
# ---------------------------------------------------------------------------

_retriever: GraphRetriever | None = None
_retriever_lock = threading.Lock()


def get_graph_retriever() -> GraphRetriever:
    global _retriever
    if _retriever is None:
        with _retriever_lock:
            if _retriever is None:
                _retriever = GraphRetriever()
    return _retriever


def reset_graph_retriever() -> None:
    """Clear the shared singleton (mainly for tests)."""
    global _retriever
    with _retriever_lock:
        if _retriever is not None:
            _retriever._invalidate()
        _retriever = None
