"""
BM25 Retriever for Enterprise RAG Platform

Implements sparse retrieval using BM25 algorithm for keyword matching.
Provides lexical search capability complementary to dense vector search.
"""

from __future__ import annotations

import math
import re
import threading
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain_core.documents import Document

from utils.log_utils import log

if TYPE_CHECKING:
    # RetrievalResult is constructed at runtime via a lazy import inside
    # retrieve(); declared here only for the type annotation.
    from core.retrieval.hybrid_retriever import RetrievalResult

__all__ = ["BM25Retriever"]


@dataclass
class BM25Config:
    """Configuration for BM25 retriever."""

    k1: float = 1.5  # Term frequency saturation
    b: float = 0.75  # Document length normalization
    top_k: int = 5  # Number of results
    # Token-length floors split by script: Chinese tokens (containing CJK) use
    # min_token_length_zh so high-value single-character CJK terms
    # (e.g. 库/表/链/油) survive; English tokens use min_token_length_en to drop
    # single-letter noise. A single min_token_length would mis-handle one or
    # the other (dropping Chinese单字 at >=2, or keeping English 'a' at 1).
    min_token_length_zh: int = 1
    min_token_length_en: int = 2


class BM25Retriever:
    """
    BM25 sparse retriever for keyword-based search.

    BM25 Formula:
        score(D, Q) = Σ IDF(qi) * (f(qi, D) * (k1 + 1)) / (f(qi, D) + k1 * (1 - b + b * |D|/avgdl))

    Features:
    - In-memory index for fast retrieval
    - Chinese text segmentation (jieba)
    - Document persistence support
    """

    def __init__(self, config: BM25Config | None = None):
        """
        Initialize BM25 retriever.

        Args:
            config: BM25 configuration
        """
        self.config = config or BM25Config()
        self._documents: list[Document] = []
        self._doc_tokens: list[list[str]] = []
        self._doc_lengths: list[int] = []
        self._avgdl: float = 0.0
        self._idf: dict[str, float] = {}
        self._doc_freq: dict[str, int] = {}
        self._index_built = False
        # The singleton is mutated by BackgroundTasks indexing while queries
        # run in an executor (run_in_executor) — the three parallel lists are
        # appended/deleted across statements and a reader can observe a
        # half-updated index. The lock guards all mutations and lets `retrieve`
        # snapshot a consistent view before iterating (B7).
        self._lock = threading.RLock()

        log.debug("BM25Retriever initialized")

    def add_documents(self, documents: list[Document]):
        """
        Add documents to the BM25 index.

        Args:
            documents: Documents to index
        """
        with self._lock:
            for doc in documents:
                self._documents.append(doc)
                index_text = doc.metadata.get("index_text", doc.page_content)
                tokens = self._tokenize(
                    index_text if isinstance(index_text, str) else doc.page_content
                )
                self._doc_tokens.append(tokens)
                self._doc_lengths.append(len(tokens))

            self._build_index()
        log.info(f"Added {len(documents)} documents to BM25 index")

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into terms."""
        if not text:
            return []
        text = self._normalize_text(text)

        # Try to use jieba for Chinese text
        try:
            import jieba

            tokens = list(jieba.cut(text))
        except ImportError:
            # Visible degradation: jieba missing collapses Chinese into single
            # whole-sentence tokens (no shared terms with documents), silently
            # crippling the sparse retrieval leg. Warn loudly so this never
            # regresses unnoticed again.
            log.warning(
                "jieba not installed, BM25 falling back to regex tokenizer "
                "— Chinese retrieval will be degraded (whole-sentence tokens)"
            )
            tokens = re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]+", text.lower())

        # Filter short tokens, with script-aware length floors: CJK-containing
        # tokens keep single chars (泵/阀/轴), latin tokens drop single letters.
        zh_floor = self.config.min_token_length_zh
        en_floor = self.config.min_token_length_en
        clean_tokens = []
        for t in tokens:
            token = t.strip().lower()
            if not token:
                continue
            floor = zh_floor if re.search(r"[\u4e00-\u9fff]", token) else en_floor
            if len(token) < floor:
                continue
            clean_tokens.append(token)
        return clean_tokens

    def _normalize_text(self, text: str) -> str:
        """Normalize query/document text for robust matching."""
        normalized = text.lower()
        # Domain-specific token normalization (e.g. chapter-code unification for
        # a domain that uses such codes). Applied only when the active profile
        # declares such patterns — a no-op for domain-agnostic profiles.
        from core.prompts.domain_profile import get_active_profile

        for pattern in get_active_profile().query_patterns:
            try:
                # Normalize code-style "ATA 32" / "ATA-32" -> "ata32" so the
                # token form matches across query and docs.
                if "ata" in pattern:
                    normalized = re.sub(r"\bata[\s\-_:]*([0-9]{2})\b", r"ata\1", normalized)
            except re.error:
                continue
        # Normalize repeated whitespace
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _build_index(self):
        """Build BM25 index from documents."""
        if not self._documents:
            return

        # Calculate average document length
        self._avgdl = sum(self._doc_lengths) / len(self._doc_lengths) if self._doc_lengths else 1

        # Build document frequency
        self._doc_freq = {}
        for tokens in self._doc_tokens:
            seen = set()
            for token in tokens:
                if token not in seen:
                    self._doc_freq[token] = self._doc_freq.get(token, 0) + 1
                    seen.add(token)

        # Calculate IDF for all terms
        n_docs = len(self._documents)
        self._idf = {}
        for term, df in self._doc_freq.items():
            # IDF formula with smoothing
            self._idf[term] = math.log((n_docs - df + 0.5) / (df + 0.5) + 1)

        self._index_built = True
        log.debug(f"BM25 index built: {n_docs} docs, {len(self._idf)} terms")

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        allowed_sources: set[str] | frozenset[str] | None = None,
    ) -> list[RetrievalResult]:
        """
        Retrieve documents using BM25 scoring.

        Args:
            query: Search query
            top_k: Number of results
            allowed_sources: Optional source set applied before BM25 scoring.

        Returns:
            List of retrieval results
        """
        from core.retrieval.hybrid_retriever import RetrievalResult

        top_k = top_k or self.config.top_k
        query_tokens = self._tokenize(query)

        if not query_tokens:
            return []

        # Snapshot the index under the lock so a concurrent add_documents /
        # remove_by_source cannot mutate the parallel lists mid-iteration
        # (which previously surfaced as IndexError, swallowed to [] by the
        # caller). Iteration then runs on the stable copies without holding
        # the lock, so a long query never blocks indexing (B7).
        with self._lock:
            if not self._index_built or not self._documents:
                log.warning("BM25 index not built or empty")
                return []
            documents = list(self._documents)
            doc_tokens = list(self._doc_tokens)
            doc_lengths = list(self._doc_lengths)
            idf = dict(self._idf)
            avgdl = self._avgdl

        # Calculate BM25 scores for each document
        scores = []
        for doc_idx, tokens in enumerate(doc_tokens):
            if allowed_sources is not None:
                source = str(documents[doc_idx].metadata.get("source", ""))
                if source not in allowed_sources:
                    continue
            score = self._bm25_score(query_tokens, tokens, doc_idx, doc_lengths, idf, avgdl)
            if score > 0:
                scores.append((doc_idx, score))

        # Sort by score and get top-k
        scores.sort(key=lambda x: x[1], reverse=True)
        top_results = scores[:top_k]

        # Create retrieval results
        results = []
        for rank, (doc_idx, score) in enumerate(top_results, 1):
            results.append(
                RetrievalResult(
                    document=documents[doc_idx],
                    score=score,
                    source="sparse",
                    rank=rank,
                )
            )

        log.debug(f"BM25 retrieved {len(results)} results for query")
        return results

    def _bm25_score(
        self,
        query_tokens: list[str],
        doc_tokens: list[str],
        doc_idx: int,
        doc_lengths: list[int],
        idf: dict[str, float],
        avgdl: float,
    ) -> float:
        """Calculate BM25 score for a document against a snapshotted index."""
        score = 0.0
        doc_len = doc_lengths[doc_idx]
        doc_counter = Counter(doc_tokens)

        k1 = self.config.k1
        b = self.config.b

        for term in query_tokens:
            if term not in idf:
                continue

            tf = doc_counter.get(term, 0)
            term_idf = idf[term]

            # BM25 formula
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * doc_len / avgdl)

            if denominator > 0:
                score += term_idf * (numerator / denominator)

        return score

    def clear(self):
        """Clear the index."""
        with self._lock:
            self._documents.clear()
            self._doc_tokens.clear()
            self._doc_lengths.clear()
            self._idf.clear()
            self._doc_freq.clear()
            self._avgdl = 0.0
            self._index_built = False
        log.debug("BM25 index cleared")

    def remove_by_source(self, source: str):
        """Remove documents matching a source filename and rebuild index."""
        with self._lock:
            if not self._documents or not source:
                return
            indices_to_remove = [
                i for i, doc in enumerate(self._documents) if doc.metadata.get("source") == source
            ]
            if not indices_to_remove:
                return
            for idx in sorted(indices_to_remove, reverse=True):
                del self._documents[idx]
                del self._doc_tokens[idx]
                del self._doc_lengths[idx]
            self._build_index()
        log.info(f"BM25 removed {len(indices_to_remove)} docs for source={source}")

    @property
    def stats(self) -> dict[str, Any]:
        """Get index statistics."""
        return {
            "document_count": len(self._documents),
            "term_count": len(self._idf),
            "avg_doc_length": self._avgdl,
            "index_built": self._index_built,
        }


# Module-level instance
_bm25_retriever: BM25Retriever | None = None


def get_bm25_retriever() -> BM25Retriever:
    """Get or create BM25 retriever instance."""
    global _bm25_retriever
    if _bm25_retriever is None:
        _bm25_retriever = BM25Retriever()
    return _bm25_retriever
