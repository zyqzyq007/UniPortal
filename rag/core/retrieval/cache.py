"""
Embedding + query-result cache (P3.6).

Caches:
  1. Query embeddings (BGE vectors) keyed on the query text — repeated queries
     skip the (CPU-bound) embedding call.
  2. Full hybrid-retrieval results keyed on (query, filter_expr, top_k, version) —
     repeated identical queries return cached docs instantly.

Uses an LRU cache (thread-safe). Cache size is configurable via env
``RETRIEVAL_CACHE_SIZE`` (default 512). Hit ratio is logged for observability.

Index-version invalidation: every document add/remove bumps
``_retrieval_cache_version`` via :func:`bump_retrieval_cache_version`; the hybrid
retriever folds the version into its cache key, so stale results from a prior
index state are never served after a knowledge-base mutation.

This wraps the embedding model and the hybrid retriever transparently —
existing callers get caching for free.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import OrderedDict
from typing import Any

from utils.log_utils import log

__all__ = [
    "LRUCache",
    "cached_embedding_function",
    "cache_key",
    "embedding_fingerprint",
    "get_retrieval_cache",
    "get_retrieval_cache_version",
    "bump_retrieval_cache_version",
    "reset_embedding_cache",
]


def _max_size() -> int:
    try:
        return max(16, int(os.getenv("RETRIEVAL_CACHE_SIZE", "512")))
    except (TypeError, ValueError):
        return 512


class LRUCache:
    """Thread-safe bounded LRU cache."""

    def __init__(self, maxsize: int = 512):
        self._maxsize = maxsize
        self._data: OrderedDict = OrderedDict()
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self.hits += 1
                return self._data[key]
            self.misses += 1
            return None

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = value
            while len(self._data) > self._maxsize:
                self._data.popitem(last=False)

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            return {
                "size": len(self._data),
                "maxsize": self._maxsize,
                "hits": self.hits,
                "misses": self.misses,
                "hit_ratio": self.hits / total if total else 0.0,
            }

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.hits = 0
            self.misses = 0


# Singleton caches.
_embedding_cache = LRUCache(maxsize=_max_size())
_retrieval_cache = LRUCache(maxsize=_max_size())

# Monotonic index-version counter. Bumped on every knowledge-base mutation
# (document add/remove/rebuild) so that cached retrieval results computed
# against an older index state are never re-served. Folded into the hybrid
# retriever's cache key via get_retrieval_cache_version().
_retrieval_cache_version = 0
_version_lock = threading.Lock()


def get_retrieval_cache() -> LRUCache:
    return _retrieval_cache


def get_retrieval_cache_version() -> int:
    """Current retrieval index version (fold into cache keys for invalidation)."""
    with _version_lock:
        return _retrieval_cache_version


def bump_retrieval_cache_version() -> None:
    """
    Invalidate retrieval-result cache entries by advancing the index version.

    Callers that mutate the knowledge base (document upload/delete/rebuild)
    invoke this so subsequent retrievals are recomputed against the new index
    rather than serving stale cached results. O(1); old entries age out via LRU.
    """
    global _retrieval_cache_version
    with _version_lock:
        _retrieval_cache_version += 1
        new_version = _retrieval_cache_version
    # Also clear outright so warm-cache hits cannot serve pre-bump results even
    # if a caller forgot to fold the version into its key (defence in depth).
    _retrieval_cache.clear()
    log.debug(f"Retrieval cache version bumped to {new_version} (cache cleared)")


def cache_key(*parts: Any) -> str:
    """Build a stable cache key from arbitrary parts."""
    namespace = os.getenv("RETRIEVAL_CACHE_NAMESPACE", "default")
    raw = "|".join([namespace, *(str(p) for p in parts)])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def embedding_fingerprint(base: Any) -> str:
    """Stable non-secret identity for query-vector cache namespacing."""
    target = getattr(base, "base", base)
    config = getattr(target, "config", None)
    values = {
        "class": f"{type(target).__module__}.{type(target).__qualname__}",
        "model": _known_attr(target, config, "model_path", "model_name", "model", "model_id"),
        "revision": _known_attr(target, config, "revision", "model_revision"),
        "dimension": _known_attr(target, config, "dimension", "dense_dim", "embedding_dimension"),
        "normalize": _known_attr(
            target,
            config,
            "normalize_embeddings",
            "normalize",
            "embedding_normalize",
        ),
        "query_prefix": _known_attr(
            target,
            config,
            "query_instruction",
            "query_prefix",
            "prompt_name",
        ),
        "hybrid_heads": _known_attr(target, config, "hybrid_head_fingerprint"),
    }
    raw = json.dumps(values, ensure_ascii=True, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _known_attr(target: Any, config: Any, *names: str) -> Any:
    for owner in (target, config):
        if owner is None:
            continue
        for name in names:
            value = getattr(owner, name, None)
            if value not in (None, ""):
                return value
    encode_kwargs = getattr(target, "encode_kwargs", None)
    if isinstance(encode_kwargs, dict):
        for name in names:
            if name in encode_kwargs:
                return encode_kwargs[name]
    return None


def reset_embedding_cache() -> None:
    """Clear only query-vector entries (tests/provider reconfiguration)."""
    _embedding_cache.clear()


class CachedEmbeddingFunction:
    """
    Wraps an embedding model to cache query embeddings.

    Only query embedding (``embed_query``) is cached — document embedding
    (``embed_documents``) is write-path and not cached (each doc embeds once
    during indexing).
    """

    def __init__(self, base):
        self._base = base
        self._fingerprint = embedding_fingerprint(base)

    def embed_query(self, text: str):
        key = cache_key(self._fingerprint, text)
        cached = _embedding_cache.get(key)
        if cached is not None:
            return cached
        vec = self._base.embed_query(text)
        _embedding_cache.put(key, vec)
        return vec

    def embed_documents(self, texts: list[str]):
        return self._base.embed_documents(texts)

    @property
    def base(self):
        return self._base

    def __getattr__(self, name):
        """Transparently delegate unknown attributes (e.g. encode_hybrid_batch,
        encode_late_chunked) to the wrapped base, so BGE-M3 hybrid methods are
        reachable through the cache wrapper (add_documents / markdown_parser
        check hasattr(emb_fn, 'encode_hybrid_batch'))."""
        return getattr(self._base, name)


def cached_embedding_function(base):
    """Wrap an embedding model with query caching."""
    return CachedEmbeddingFunction(base)
