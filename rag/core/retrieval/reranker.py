"""Cross-encoder reranking with lazy loading and runtime status."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path

from langchain_core.documents import Document

from utils.env_utils import (
    RERANKER_BATCH_SIZE,
    RERANKER_DEVICE,
    RERANKER_MODEL,
    RERANKER_MODEL_PATH,
    RERANKER_TOP_K,
)
from utils.log_utils import log

__all__ = [
    "Reranker",
    "RerankerConfig",
    "get_reranker",
    "get_reranker_model_source",
    "is_reranker_model_cached",
]


def get_reranker_model_source() -> str:
    """Prefer an explicitly configured local directory over a Hub model ID."""
    if RERANKER_MODEL_PATH and Path(RERANKER_MODEL_PATH).is_dir():
        return RERANKER_MODEL_PATH
    return RERANKER_MODEL


_cache_status: dict[str, bool] = {}
_cache_status_lock = threading.Lock()


def is_reranker_model_cached(
    model_name: str = RERANKER_MODEL,
    model_path: str = RERANKER_MODEL_PATH,
    *,
    refresh: bool = False,
) -> bool:
    """Return whether the configured reranker is available without a download."""
    if model_path and Path(model_path).is_dir():
        return True
    with _cache_status_lock:
        if not refresh and model_name in _cache_status:
            return _cache_status[model_name]

    try:
        from huggingface_hub import scan_cache_dir

        cached = any(repo.repo_id == model_name for repo in scan_cache_dir().repos)
    except Exception:
        cached = False

    with _cache_status_lock:
        _cache_status[model_name] = cached
    return cached


def _mark_reranker_model_cached(model_name: str) -> None:
    with _cache_status_lock:
        _cache_status[model_name] = True


@dataclass
class RerankerConfig:
    model_name: str = RERANKER_MODEL
    model_path: str = RERANKER_MODEL_PATH
    device: str = RERANKER_DEVICE
    top_k: int = RERANKER_TOP_K
    batch_size: int = RERANKER_BATCH_SIZE

    def __post_init__(self) -> None:
        if self.model_name != RERANKER_MODEL and self.model_path == RERANKER_MODEL_PATH:
            self.model_path = ""

    @property
    def model_source(self) -> str:
        if self.model_path and Path(self.model_path).is_dir():
            return self.model_path
        return self.model_name


class Reranker:
    """Lazy-loaded cross-encoder with graceful retrieval-order fallback."""

    def __init__(self, config: RerankerConfig | None = None):
        self.config = config or RerankerConfig()
        self._model = None
        self._load_attempted = False
        self._load_error: str | None = None
        self._load_lock = threading.Lock()
        log.debug(f"Reranker initialized: model={self.config.model_source}")

    def load(self) -> bool:
        """Load the model once. Hub model IDs download into Hugging Face cache."""
        if self._model is not None:
            return True
        if self._load_attempted:
            return False

        with self._load_lock:
            if self._model is not None:
                return True
            if self._load_attempted:
                return False
            self._load_attempted = True
            try:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(
                    self.config.model_source,
                    device=self.config.device,
                )
                _mark_reranker_model_cached(self.config.model_name)
                self._load_error = None
                log.info(f"Reranker model loaded: {self.config.model_source}")
                return True
            except Exception as exc:
                self._load_error = str(exc)
                log.warning(f"Failed to load reranker model: {exc}")
                return False

    async def aload(self) -> bool:
        """Load without blocking the event loop."""
        return await asyncio.to_thread(self.load)

    def status(self) -> dict:
        """Return runtime state without triggering a model download."""
        loaded = self._model is not None
        # "degraded" = load was attempted but failed and is now sticky for the
        # process lifetime (see _load_attempted). Every retrieval then falls back
        # to RRF order — retrieval still works, but precision reranking is off.
        # Surfaced so /api/admin/health can alert on it rather than silently
        # serving lower-quality results (critic F-RS-002).
        degraded = (not loaded) and self._load_attempted and self._load_error is not None
        return {
            "model": self.config.model_name,
            "model_source": self.config.model_source,
            "device": self.config.device,
            "cached": is_reranker_model_cached(
                self.config.model_name,
                self.config.model_path,
            ),
            "load_attempted": self._load_attempted,
            "loaded": loaded,
            "degraded": degraded,
            "load_error": self._load_error,
        }

    @staticmethod
    def _fallback_documents(
        documents: list[Document],
        top_k: int,
        error: str | None = None,
    ) -> list[Document]:
        results = []
        for doc in documents[:top_k]:
            metadata = dict(doc.metadata)
            metadata["rerank_applied"] = False
            if error:
                metadata["rerank_error"] = error
            results.append(Document(page_content=doc.page_content, metadata=metadata))
        return results

    def rerank(
        self,
        query: str,
        documents: list[Document],
        top_k: int | None = None,
    ) -> list[Document]:
        if not documents:
            return []
        top_k = top_k or self.config.top_k

        if not self.load():
            return self._fallback_documents(documents, top_k, self._load_error)

        try:
            pairs = [
                (
                    query,
                    doc.metadata.get("index_text", doc.page_content)
                    if isinstance(doc.metadata.get("index_text", doc.page_content), str)
                    else doc.page_content,
                )
                for doc in documents
            ]
            scores = self._model.predict(
                pairs,
                batch_size=self.config.batch_size,
                show_progress_bar=False,
            )
            scored_docs = sorted(zip(documents, scores), key=lambda item: item[1], reverse=True)

            results = []
            for doc, score in scored_docs[:top_k]:
                metadata = dict(doc.metadata)
                # Preserve the upstream retrieval score (e.g. RRF) under its
                # own key so downstream stages (MMR) still see it; previously
                # the raw cross-encoder logit overwrote "score", which broke
                # MMR's score-blending (negative logits got clamped to 0).
                if "score" not in metadata:
                    metadata["score"] = 0.0
                metadata["retrieval_score"] = metadata.get("score", 0.0)
                metadata["rerank_score"] = float(score)
                metadata["rerank_applied"] = True
                results.append(Document(page_content=doc.page_content, metadata=metadata))
            log.debug(f"Reranked {len(documents)} documents -> {len(results)}")
            return results
        except Exception as exc:
            log.warning(f"Reranking failed: {exc}")
            return self._fallback_documents(documents, top_k, str(exc))

    async def arerank(
        self,
        query: str,
        documents: list[Document],
        top_k: int | None = None,
    ) -> list[Document]:
        return await asyncio.to_thread(self.rerank, query, documents, top_k)


_reranker: Reranker | None = None


def get_reranker() -> Reranker:
    global _reranker
    if _reranker is None:
        _reranker = Reranker()
    return _reranker
