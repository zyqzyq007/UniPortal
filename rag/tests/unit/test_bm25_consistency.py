#!/usr/bin/env python3
"""
F01 — BM25 read/write consistency (singleton unification) + cache invalidation.

Regression guard for the historical divergence where ``HybridRetriever`` built
its own ``BM25Retriever()`` instance while the documents router wrote to the
``get_bm25_retriever()`` singleton — so runtime document mutations never reached
the retriever's BM25 leg.

Also guards the cache-invalidation contract: after a knowledge-base mutation
(``bump_retrieval_cache_version``), a previously-cached retrieval result must be
recomputed against the new index rather than re-served.

These tests hit the singleton getters directly (not via the HTTP client) so they
do not depend on the e2e conftest wiring (per design M4 decoupling).

Run: pytest tests/unit/test_bm25_consistency.py -v
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")


# ===========================================================================
# F01a — hybrid retriever reads the SAME BM25 instance the write path uses
# ===========================================================================


class TestBM25SingletonUnification:
    def test_hybrid_sparse_retriever_is_the_module_singleton(self):
        """The hybrid retriever must consume the shared BM25 singleton, not a
        private copy, so document mutations are visible on the read path."""
        from core.retrieval.bm25_retriever import get_bm25_retriever
        from core.retrieval.hybrid_retriever import HybridRetriever, HybridRetrieverConfig

        # Build a retriever WITHOUT touching Milvus: inject a fake dense manager
        # whose query() returns nothing so _ensure_sparse_indexed is a no-op.
        # enable_native_sparse=False forces the legacy BM25 leg (this test guards
        # the BM25 singleton contract, not the M3 native sparse path).
        class _FakeDense:
            def query(self, **kwargs):
                return []

        hr = HybridRetriever(
            dense_manager=_FakeDense(),
            config=HybridRetrieverConfig(enable_native_sparse=False),
        )
        singleton = get_bm25_retriever()
        # Accessing the property resolves to the singleton.
        assert hr.sparse_retriever is singleton

    def test_document_add_then_retrieve_sees_new_doc(self):
        """End-to-end (in-process): write via the singleton's add_documents,
        read via the hybrid retriever's sparse leg, and confirm the new doc is
        reachable. This is the AC-F01 contract."""
        from langchain_core.documents import Document

        from core.retrieval.bm25_retriever import get_bm25_retriever
        from core.retrieval.cache import bump_retrieval_cache_version
        from core.retrieval.hybrid_retriever import HybridRetriever, HybridRetrieverConfig

        class _FakeDense:
            def query(self, **kwargs):
                return []  # do not bootstrap from Milvus

            def search(self, **kwargs):
                return []  # dense leg returns nothing; isolate BM25

        singleton = get_bm25_retriever()
        marker = "UNIQUE_BM25_CONSISTENCY_MARKER_ZZZ"
        before = [d for d in singleton._documents if marker in d.page_content]
        # Sanity: the marker should not already be present (hermetic start).
        assert not before, "marker already present before test — singleton leaked state"
        try:
            doc = Document(
                page_content=f"{marker} 服务启动失败的排查方法",
                metadata={"source": "consistency_test", "title": "t", "score": 0.9},
            )
            singleton.add_documents([doc])
            bump_retrieval_cache_version()  # mirrors documents router behaviour

            # enable_native_sparse=False forces BM25 (this test guards BM25 contract).
            hr = HybridRetriever(
                dense_manager=_FakeDense(),
                config=HybridRetrieverConfig(enable_native_sparse=False),
            )
            results = hr.retrieve(marker, top_k=3)
            assert any(marker in d.page_content for d in results), (
                "BM25 mutation did not propagate to the hybrid read path"
            )
        finally:
            # Clean up: remove the test source so other tests stay hermetic.
            try:
                singleton.remove_by_source("consistency_test")
                bump_retrieval_cache_version()
            except Exception:
                pass
            assert not [d for d in singleton._documents if marker in d.page_content]


# ===========================================================================
# F01b — cache invalidation: version bump evicts stale results
# ===========================================================================


class TestRetrievalCacheVersionInvalidation:
    def test_bump_version_clears_cached_results(self):
        """A cached retrieval for a query must not be re-served after the
        index version is bumped (documents router calls this on add/remove)."""
        from core.retrieval.cache import (
            LRUCache,
            bump_retrieval_cache_version,
            get_retrieval_cache,
            get_retrieval_cache_version,
        )

        cache: LRUCache = get_retrieval_cache()
        cache.clear()
        v0 = get_retrieval_cache_version()
        cache.put("k", "v0")
        assert cache.get("k") == "v0"

        bump_retrieval_cache_version()
        v1 = get_retrieval_cache_version()
        assert v1 == v0 + 1
        # bump clears the cache outright (defence in depth).
        assert cache.get("k") is None

    def test_version_advances_monotonically(self):
        from core.retrieval.cache import (
            bump_retrieval_cache_version,
            get_retrieval_cache_version,
        )

        start = get_retrieval_cache_version()
        bump_retrieval_cache_version()
        bump_retrieval_cache_version()
        assert get_retrieval_cache_version() == start + 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
