"""Bounded BGE-M3 ColBERT late-interaction reranking."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import numpy as np
from langchain_core.documents import Document

from utils.log_utils import log

__all__ = [
    "ColBERTReranker",
    "ColBERTRerankerConfig",
    "ColBERTRerankResult",
    "colbert_rerank_enabled",
    "maxsim_score",
]


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


@dataclass(frozen=True)
class ColBERTRerankerConfig:
    max_candidates: int = 32
    max_query_tokens: int = 64
    max_document_tokens: int = 512
    batch_size: int = 4

    @classmethod
    def from_env(cls) -> ColBERTRerankerConfig:
        return cls(
            max_candidates=_env_int("COLBERT_MAX_CANDIDATES", 32, 1, 128),
            max_query_tokens=_env_int("COLBERT_MAX_QUERY_TOKENS", 64, 1, 256),
            max_document_tokens=_env_int("COLBERT_MAX_DOCUMENT_TOKENS", 512, 1, 2048),
            batch_size=_env_int("COLBERT_BATCH_SIZE", 4, 1, 32),
        )


@dataclass(frozen=True)
class ColBERTRerankResult:
    documents: list[Document]
    degraded: bool
    error: str | None = None
    scored_count: int = 0


def _token_matrix(value: Any, maximum: int) -> np.ndarray:
    matrix = np.asarray(value, dtype=np.float32)
    if matrix.ndim != 2 or not matrix.shape[0] or not matrix.shape[1]:
        raise ValueError("ColBERT token matrix must be a non-empty rank-2 array")
    return matrix[:maximum]


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms > 1e-12, norms, 1.0)
    return matrix / norms


def maxsim_score(
    query_tokens: Any,
    document_tokens: Any,
    *,
    max_query_tokens: int = 64,
    max_document_tokens: int = 512,
) -> float:
    """Mean over query-token maximum cosine similarities."""
    query = _l2_normalize(_token_matrix(query_tokens, max_query_tokens))
    document = _l2_normalize(_token_matrix(document_tokens, max_document_tokens))
    if query.shape[1] != document.shape[1]:
        raise ValueError("ColBERT query/document dimensions differ")
    similarities = query @ document.T
    return float(np.max(similarities, axis=1).mean())


class ColBERTReranker:
    def __init__(
        self,
        embedding: Any,
        config: ColBERTRerankerConfig | None = None,
    ):
        self._embedding = embedding
        self._config = config or ColBERTRerankerConfig.from_env()

    def rerank(
        self,
        query_colbert: Any,
        documents: list[Document],
        *,
        top_k: int,
    ) -> ColBERTRerankResult:
        if not documents:
            return ColBERTRerankResult([], degraded=False)
        if query_colbert is None or not hasattr(self._embedding, "encode_colbert_documents"):
            return ColBERTRerankResult(
                documents,
                degraded=True,
                error="colbert_unavailable",
            )
        candidate_count = min(
            len(documents),
            max(1, int(top_k)),
            self._config.max_candidates,
        )
        candidates = documents[:candidate_count]
        texts = [
            str(document.metadata.get("index_text", document.page_content))
            for document in candidates
        ]
        try:
            document_vectors = self._embedding.encode_colbert_documents(
                texts,
                max_tokens=self._config.max_document_tokens,
                batch_size=self._config.batch_size,
            )
            if len(document_vectors) != candidate_count:
                raise ValueError("ColBERT document encoder returned an unexpected batch size")
            raw_scores = [
                maxsim_score(
                    query_colbert,
                    vectors,
                    max_query_tokens=self._config.max_query_tokens,
                    max_document_tokens=self._config.max_document_tokens,
                )
                for vectors in document_vectors
            ]
            low, high = min(raw_scores), max(raw_scores)
            span = high - low
            normalized = [
                (score - low) / span if span > 1e-12 else max(0.0, min(1.0, (score + 1) / 2))
                for score in raw_scores
            ]
            scored: list[tuple[float, int, Document]] = []
            for index, (document, raw_score, normalized_score) in enumerate(
                zip(candidates, raw_scores, normalized, strict=True)
            ):
                metadata = dict(document.metadata)
                metadata["colbert_score"] = float(normalized_score)
                metadata["colbert_raw_score"] = float(raw_score)
                metadata["colbert_applied"] = True
                scored.append(
                    (
                        raw_score,
                        index,
                        Document(page_content=document.page_content, metadata=metadata),
                    )
                )
            scored.sort(key=lambda item: (-item[0], item[1]))
            reranked = [item[2] for item in scored]
            reranked.extend(documents[candidate_count:])
            return ColBERTRerankResult(
                reranked,
                degraded=False,
                scored_count=candidate_count,
            )
        except Exception as exc:
            log.warning(f"ColBERT rerank unavailable; preserving prior order: {type(exc).__name__}")
            return ColBERTRerankResult(
                documents,
                degraded=True,
                error="colbert_unavailable",
            )


def colbert_rerank_enabled() -> bool:
    return os.getenv("COLBERT_RERANK_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
