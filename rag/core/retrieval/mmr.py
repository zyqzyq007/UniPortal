"""
Maximal Marginal Relevance (MMR) re-ranking.

After RRF fusion, retrieved chunks are often near-duplicates (the same manual
paragraph indexed at slightly different offsets, or overlapping table text).
MMR de-redundancies the result set by selecting chunks that are both relevant
to the query AND diverse from already-selected chunks.

Formula:
    MMR(d) = argmax [ lambda * sim(d, q) - (1-lambda) * max_{d' in S} sim(d, d') ]

where sim is cosine similarity over the project's local BGE embeddings.

This module is Milvus-free (pure numpy + the embedding singleton), so it is
unit-testable without a vector store. ``rerank`` accepts ``Document`` objects
and returns a diversity-ordered subset.
"""

from __future__ import annotations

import numpy as np
from langchain_core.documents import Document

from utils.log_utils import log

__all__ = ["mmr_rerank", "DEFAULT_LAMBDA"]


DEFAULT_LAMBDA = 0.7  # 1.0 = pure relevance, 0.0 = pure diversity


def _embeddings():
    """Lazy access to the shared BGE embedding model."""
    from models.embedding_models import get_local_embeddings

    return get_local_embeddings()


def _cosine_matrix(vectors: np.ndarray) -> np.ndarray:
    """Pairwise cosine similarity for a (n, d) matrix."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    normed = vectors / norms
    return normed @ normed.T


def mmr_rerank(
    query: str,
    documents: list[Document],
    top_k: int = 4,
    lambda_: float = DEFAULT_LAMBDA,
    fetch_k: int | None = None,
    query_vector: list[float] | np.ndarray | None = None,
) -> list[Document]:
    """
    Re-rank documents with Maximal Marginal Relevance.

    Args:
        query: the user query.
        documents: candidate documents (already relevance-ranked; the score in
            metadata["score"] is used as the relevance signal).
        top_k: number of documents to return.
        lambda_: relevance/diversity trade-off (0..1).
        fetch_k: pool size to consider before selecting top_k (defaults to
            min(len(documents), 4*top_k)).
        query_vector: request-local precomputed query vector. When present MMR
            embeds only documents and never repeats query encoding.

    Returns:
        A diversity-ordered list of at most ``top_k`` documents.
    """
    if not documents:
        return []
    if len(documents) <= 1 or top_k <= 1:
        return documents[: max(1, top_k)]

    # Restrict the candidate pool.
    pool = documents
    if fetch_k and fetch_k < len(documents):
        pool = documents[:fetch_k]
    elif 4 * top_k < len(documents):
        pool = documents[: 4 * top_k]

    try:
        emb = _embeddings()
    except Exception as e:  # noqa: BLE001 - MMR must not break retrieval
        log.debug(f"MMR embeddings unavailable, returning relevance order: {e}")
        return documents[:top_k]

    # Embed the query and all pool docs.
    try:
        doc_texts = [d.page_content for d in pool]
        doc_vecs = np.asarray(emb.embed_documents(doc_texts), dtype=np.float32)
        q_vec = (
            np.asarray(query_vector, dtype=np.float32)
            if query_vector is not None
            else np.asarray(emb.embed_query(query), dtype=np.float32)
        )
    except Exception as e:  # noqa: BLE001
        log.debug(f"MMR embedding failed, returning relevance order: {e}")
        return pool[:top_k]

    if doc_vecs.ndim != 2 or doc_vecs.shape[0] == 0:
        return pool[:top_k]

    # Relevance = cosine(doc, query); also use metadata score when present to
    # blend with the retriever's own signal.
    q_norm = np.linalg.norm(q_vec) or 1.0
    rel = (doc_vecs @ q_vec) / (np.linalg.norm(doc_vecs, axis=1) * q_norm + 1e-9)
    # Blend with retrieval score if available. Scores are min-max normalised
    # *within the candidate pool* (not globally clamped): RRF scores are tiny
    # (~0.01) and reranker logits can be negative, so a global clamp to [0,1]
    # would destroy the ranking signal. Min-max preserves relative ordering.
    raw_scores = [d.metadata.get("rerank_score", d.metadata.get("score")) for d in pool]
    scores = _norm_scores(raw_scores)
    if scores.max() > 0:
        relevance = 0.5 * rel + 0.5 * scores
    else:
        relevance = rel

    sim_doc = _cosine_matrix(doc_vecs)

    selected: list[int] = []
    remaining = list(range(len(pool)))

    # Greedy selection.
    while remaining and len(selected) < top_k:
        best_idx = None
        best_score = -float("inf")
        for i in remaining:
            if selected:
                max_sim = sim_doc[i, selected].max()
            else:
                max_sim = 0.0
            mmr = lambda_ * relevance[i] - (1.0 - lambda_) * max_sim
            if mmr > best_score:
                best_score = mmr
                best_idx = i
        if best_idx is None:
            break
        selected.append(best_idx)
        remaining.remove(best_idx)

    return [pool[i] for i in selected]


def _norm_scores(raw_scores) -> np.ndarray:
    """
    Min-max normalise a list of retrieval scores to [0, 1].

    Unlike a global clamp, min-max preserves the relative ordering of the
    candidate pool. This matters because:
      - RRF scores are tiny (~0.01) — clamping to [0,1] collapses them all.
      - Reranker logits can be negative — clamping maps negatives to 0,
        destroying the reranker's ranking signal when MMR runs after it.

    Returns an all-zero array when no numeric scores are present (so the
    caller falls back to pure cosine relevance).
    """
    numeric = []
    for s in raw_scores:
        try:
            numeric.append(float(s))
        except (TypeError, ValueError):
            numeric.append(None)
    if not any(v is not None for v in numeric):
        return np.zeros(len(raw_scores), dtype=np.float32)
    # Replace missing values with the min of present values (least relevant).
    present = [v for v in numeric if v is not None]
    fill = min(present)
    vals = np.array([fill if v is None else v for v in numeric], dtype=np.float32)
    lo, hi = float(vals.min()), float(vals.max())
    if hi - lo < 1e-9:
        # All equal: no discriminative signal; treat as uniform (0.5 mid-band).
        return np.full(len(vals), 0.5, dtype=np.float32)
    return (vals - lo) / (hi - lo)
