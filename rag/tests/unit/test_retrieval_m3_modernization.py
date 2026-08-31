#!/usr/bin/env python3
"""
F1 retrieval-backend-modernization — regression guards for critic findings.

F-02: _rrf_fusion must preserve dense/sparse double-hit accumulation semantics
      (two INDEPENDENT searches, not Milvus hybrid_search's pre-fused single rank).
      Guards against RRF-of-RRF where a doc hit by both legs gets only one fused
      rank contribution instead of two separate accumulations.
F-01: native sparse_search must honour filter_expr (zero cross-source leakage).
      Guards against the hybrid_search top-level filter pitfall (pymilvus 2.5.18
      silently drops it; search(filter=) is the first-class path).

Run: pytest tests/unit/test_retrieval_m3_modernization.py -v
"""

from __future__ import annotations

import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, ".")


# ===========================================================================
# F-02 — RRF fusion preserves double-hit accumulation (two independent ranks)
# ===========================================================================


class TestRRFFusionSemantics:
    """F-02: the dense and sparse legs contribute INDEPENDENT rank lists, so a
    document hit by BOTH gets accumulated contributions (not a single pre-fused
    rank). This is the core invariant of 方案 A (two independent searches).
    """

    def test_double_hit_accumulates_more_than_single_hit(self):
        """A doc hit at dense#1 AND sparse#1 must score higher than a doc hit at
        dense#1 only — proving the two legs accumulate independently."""
        from langchain_core.documents import Document

        from core.retrieval.hybrid_retriever import (
            HybridRetriever,
            HybridRetrieverConfig,
            RetrievalResult,
        )

        config = HybridRetrieverConfig(
            dense_weight=0.5,
            sparse_weight=0.5,
            graph_weight=0.0,
            enable_graph=False,
            rrf_k=60,
            enable_reranker=False,
            enable_mmr=False,
        )
        hr = HybridRetriever(config=config)

        doc_single = Document(page_content="single hit doc", metadata={})
        doc_double = Document(page_content="double hit doc", metadata={})

        # Case A: doc_single hit at dense#1 only (sparse misses it)
        dense_a = [RetrievalResult(document=doc_single, score=1.0, source="dense", rank=1)]
        sparse_a: list[RetrievalResult] = []
        fused_a = hr._rrf_fusion(dense_a, sparse_a, [])
        score_single = fused_a[0].score

        # Case B: doc_double hit at dense#1 AND sparse#1 (double hit)
        dense_b = [RetrievalResult(document=doc_double, score=1.0, source="dense", rank=1)]
        sparse_b = [RetrievalResult(document=doc_double, score=1.0, source="sparse", rank=1)]
        fused_b = hr._rrf_fusion(dense_b, sparse_b, [])
        score_double = fused_b[0].score

        # Double-hit must accumulate: score_double > score_single (two contributions
        # vs one). This proves the legs are independent, NOT RRF-of-RRF.
        assert score_double > score_single, (
            f"Double-hit ({score_double:.6f}) should outrank single-hit "
            f"({score_single:.6f}) — double-hit accumulation broken (RRF-of-RRF?)"
        )

    def test_double_hit_score_equals_sum_of_two_single_contributions(self):
        """Numerical check: double-hit score == dense#1 contrib + sparse#1 contrib."""
        from langchain_core.documents import Document

        from core.retrieval.hybrid_retriever import (
            HybridRetriever,
            HybridRetrieverConfig,
            RetrievalResult,
        )

        config = HybridRetrieverConfig(
            dense_weight=0.5,
            sparse_weight=0.5,
            graph_weight=0.0,
            enable_graph=False,
            rrf_k=60,
            enable_reranker=False,
            enable_mmr=False,
        )
        hr = HybridRetriever(config=config)

        doc = Document(page_content="test doc", metadata={})
        # Both legs: weights normalise to 0.5 each (total=1.0), k=60.
        # Single dense#1: 0.5/61. Single sparse#1: 0.5/61. Double: 0.5/61 + 0.5/61.
        expected_double = 0.5 / 61 + 0.5 / 61

        dense = [RetrievalResult(document=doc, score=1.0, source="dense", rank=1)]
        sparse = [RetrievalResult(document=doc, score=1.0, source="sparse", rank=1)]
        fused = hr._rrf_fusion(dense, sparse, [])

        assert abs(fused[0].score - expected_double) < 1e-9, (
            f"Double-hit score {fused[0].score:.10f} != expected {expected_double:.10f}"
        )

    def test_graph_weight_unchanged_with_native_sparse(self):
        """F-02: graph_weight normalisation is identical whether sparse is BM25
        or native M3 — the three-leg denominator doesn't depend on sparse source."""
        from langchain_core.documents import Document

        from core.retrieval.hybrid_retriever import (
            HybridRetriever,
            HybridRetrieverConfig,
            RetrievalResult,
        )

        config = HybridRetrieverConfig(
            dense_weight=0.5,
            sparse_weight=0.5,
            graph_weight=0.4,
            enable_graph=True,
            rrf_k=60,
            enable_reranker=False,
            enable_mmr=False,
        )
        hr = HybridRetriever(config=config)

        doc = Document(page_content="graph doc", metadata={})
        dense = [RetrievalResult(document=doc, score=1.0, source="dense", rank=1)]
        sparse = [RetrievalResult(document=doc, score=1.0, source="sparse", rank=1)]
        graph = [RetrievalResult(document=doc, score=1.0, source="graph", rank=1)]

        fused = hr._rrf_fusion(dense, sparse, graph)
        # total = 0.5+0.5+0.4 = 1.4; graph_w = 0.4/1.4 ≈ 0.2857
        # graph#1 contrib = 0.2857/61
        expected_graph_contrib = (0.4 / 1.4) / 61
        # The doc's total = dense + sparse + graph contributions
        expected_total = (0.5 / 1.4) / 61 + (0.5 / 1.4) / 61 + expected_graph_contrib
        assert abs(fused[0].score - expected_total) < 1e-9


# ===========================================================================
# F-01 — native sparse_search honours filter (zero cross-source leakage)
# ===========================================================================


class TestSparseSearchFilterSafety:
    """F-01: filter_expr must be applied (zero leakage). Since MilvusClient.search
    honours filter= as a first-class param (unlike hybrid_search's top-level
    filter which pymilvus 2.5.18 drops), sparse_search passes it through. This
    test mocks the Milvus client to assert filter_expr reaches search(filter=)."""

    def test_sparse_search_passes_filter_to_milvus(self):
        """sparse_search must forward filter_expr to client.search(filter=...)."""
        from documents.milvus_db import MilvusManager

        manager = MilvusManager()
        manager._collection_loaded = True  # skip _ensure_collection_loaded

        # Mock client: capture the filter argument.
        mock_client = MagicMock()
        mock_client.search.return_value = [[]]
        manager._client = mock_client

        manager.sparse_search(
            query_sparse={1: 0.5, 2: 0.3},
            top_k=5,
            filter_expr='source == "manual_A"',
        )

        # Assert search was called with the filter.
        call_kwargs = mock_client.search.call_args.kwargs
        assert call_kwargs.get("filter") == 'source == "manual_A"', (
            f"sparse_search did not forward filter_expr to search(filter=); "
            f"got filter={call_kwargs.get('filter')!r}"
        )
        assert call_kwargs.get("anns_field") == "sparse"

    def test_sparse_search_filter_none_does_not_crash(self):
        """sparse_search with filter_expr=None must not pass a spurious filter."""
        from documents.milvus_db import MilvusManager

        manager = MilvusManager()
        manager._collection_loaded = True
        mock_client = MagicMock()
        mock_client.search.return_value = [[]]
        manager._client = mock_client

        manager.sparse_search(query_sparse={1: 0.5}, top_k=5, filter_expr=None)
        call_kwargs = mock_client.search.call_args.kwargs
        # filter should be None (no filtering), not a malformed expression.
        assert call_kwargs.get("filter") is None


# ===========================================================================
# F-02 — _sparse_retrieve dispatches to M3 vs BM25 by config
# ===========================================================================


class TestSparseRetrieveDispatch:
    """enable_native_sparse controls BM25 (legacy) vs M3 native sparse."""

    def test_native_sparse_uses_m3_path(self):
        """When enable_native_sparse=True, _sparse_retrieve calls the M3 path
        (encode_hybrid + sparse_search), not BM25."""
        from core.retrieval.hybrid_retriever import (
            HybridRetriever,
            HybridRetrieverConfig,
        )

        hr = HybridRetriever(
            config=HybridRetrieverConfig(enable_native_sparse=True),
        )

        with (
            patch.object(hr, "_sparse_retrieve_m3", return_value=[]) as mock_m3,
        ):
            hr._sparse_retrieve("test query", None)
            mock_m3.assert_called_once_with("test query", None)

    def test_legacy_sparse_uses_bm25_path(self):
        """When enable_native_sparse=False, _sparse_retrieve falls back to BM25."""
        from core.retrieval.hybrid_retriever import (
            HybridRetriever,
            HybridRetrieverConfig,
        )

        # Build a retriever with native sparse OFF, and a mock sparse_retriever
        # that is already "indexed" (so the property's _ensure_sparse_indexed is a no-op).
        mock_bm25 = MagicMock()
        mock_bm25._index_built = True
        mock_bm25._documents = ["placeholder"]  # truthy → skip rehydrate
        mock_bm25.retrieve.return_value = []
        mock_dense = MagicMock()
        mock_dense.query.return_value = []

        hr = HybridRetriever(
            dense_manager=mock_dense,
            sparse_retriever=mock_bm25,
            config=HybridRetrieverConfig(enable_native_sparse=False),
        )

        with patch.object(hr, "_sparse_retrieve_m3") as mock_m3:
            hr._sparse_retrieve("test query", None)
            mock_m3.assert_not_called()
            mock_bm25.retrieve.assert_called_once()

    def test_m3_sparse_degrades_to_empty_on_failure(self):
        """REQ-RBM-004: _sparse_retrieve_m3 returns [] on failure (never raises)."""
        from core.retrieval.hybrid_retriever import (
            HybridRetriever,
            HybridRetrieverConfig,
        )

        hr = HybridRetriever(
            config=HybridRetrieverConfig(enable_native_sparse=True),
        )

        # encode_hybrid raises → must degrade to [], not propagate.
        with patch("models.bge_m3_embeddings.get_bge_m3_embeddings") as mock_get:
            mock_get.side_effect = RuntimeError("model unavailable")
            result = hr._sparse_retrieve_m3("query", None)
        assert result == [], "M3 sparse failure should degrade to [], not raise"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ===========================================================================
# F1 dispatch — _get_local_embeddings returns BGEM3Embeddings for bge-m3
# ===========================================================================


class TestEmbeddingDispatch:
    """The local embedding factory must return BGEM3Embeddings when the model
    is BGE-M3, and HuggingFaceEmbeddings otherwise. Regression for the dispatch
    bug found in smoke testing (Stage A had the design but not the impl)."""

    def test_bge_m3_model_returns_bgem3_adapter(self):
        """When EMBEDDING_MODEL contains 'bge-m3', get_embeddings() local branch
        returns a BGEM3Embeddings instance (has encode_hybrid_batch)."""
        from models.bge_m3_embeddings import BGEM3Embeddings
        from models.embedding_models import reset_embeddings

        fake_huggingface = types.ModuleType("langchain_huggingface")

        with (
            patch.dict(
                os.environ,
                {
                    "EMBEDDING_PROVIDER": "local",
                    "EMBEDDING_MODEL": "BAAI/bge-m3",
                    "EMBEDDING_MODEL_PATH": "models/local_models/bge-m3",
                    "EMBEDDING_DIMENSION": "1024",
                    "MILVUS_SPARSE_INDEX": "true",
                },
            ),
            patch.dict(sys.modules, {"langchain_huggingface": fake_huggingface}),
        ):
            reset_embeddings()
            from models.embedding_models import get_embeddings

            emb = get_embeddings()
            assert isinstance(emb, BGEM3Embeddings), (
                f"Expected BGEM3Embeddings for bge-m3, got {type(emb).__name__}"
            )
            reset_embeddings()

    def test_non_m3_model_returns_huggingface(self):
        """When EMBEDDING_MODEL is bge-small, get_embeddings() returns a
        HuggingFaceEmbeddings (not BGEM3Embeddings)."""
        from models.bge_m3_embeddings import BGEM3Embeddings
        from models.embedding_models import reset_embeddings

        fake_huggingface = types.ModuleType("langchain_huggingface")
        mock_hf = MagicMock()
        fake_huggingface.HuggingFaceEmbeddings = mock_hf

        with (
            patch.dict(
                os.environ,
                {
                    "EMBEDDING_PROVIDER": "local",
                    "EMBEDDING_MODEL": "BAAI/bge-small-zh-v1.5",
                    "EMBEDDING_MODEL_PATH": "",
                    "EMBEDDING_DIMENSION": "512",
                    "MILVUS_SPARSE_INDEX": "false",
                },
            ),
            patch.dict(sys.modules, {"langchain_huggingface": fake_huggingface}),
        ):
            mock_hf.return_value = MagicMock(spec=[])
            reset_embeddings()
            from models.embedding_models import get_embeddings

            emb = get_embeddings()
            # Must NOT be a BGEM3Embeddings instance.
            assert not isinstance(emb, BGEM3Embeddings), (
                "bge-small should return HuggingFaceEmbeddings, not BGEM3Embeddings"
            )
            reset_embeddings()


class TestHybridHeadAssets:
    @staticmethod
    def _base_model(path):
        path.mkdir()
        (path / "config.json").write_text("{}", encoding="utf-8")
        (path / "model.safetensors").write_bytes(b"base")

    def test_missing_trained_heads_degrades_to_dense_without_random_sparse(self, tmp_path):
        import numpy as np

        from models.bge_m3_embeddings import BGEM3Embeddings

        model_path = tmp_path / "bge-m3"
        self._base_model(model_path)
        embedding = BGEM3Embeddings(str(model_path), device="cpu", use_fp16=False)

        class FakeModel:
            def encode(self, texts, **kwargs):
                assert kwargs["return_sparse"] is False
                assert kwargs["return_colbert_vecs"] is False
                return {
                    "dense_vecs": np.asarray(
                        [[1.0, 2.0] for _ in texts],
                        dtype=np.float32,
                    )
                }

        embedding._flag_model = FakeModel()
        representation = embedding.encode_query_representation("query", return_colbert=True)
        batch = embedding.encode_hybrid_batch(["document"])

        assert representation == {
            "dense": [1.0, 2.0],
            "sparse": None,
            "colbert": None,
        }
        assert batch == [([1.0, 2.0], {})]

    def test_hybrid_asset_fingerprint_requires_both_trained_heads(self, tmp_path):
        from models.bge_m3_embeddings import (
            bge_m3_hybrid_asset_fingerprint,
            bge_m3_hybrid_assets_ready,
        )

        model_path = tmp_path / "bge-m3"
        self._base_model(model_path)
        assert bge_m3_hybrid_assets_ready(str(model_path)) is False
        assert bge_m3_hybrid_asset_fingerprint(str(model_path)) == "missing"

        (model_path / "sparse_linear.pt").write_bytes(b"trained-sparse")
        (model_path / "colbert_linear.pt").write_bytes(b"trained-colbert")

        assert bge_m3_hybrid_assets_ready(str(model_path)) is True
        first = bge_m3_hybrid_asset_fingerprint(str(model_path))
        (model_path / "sparse_linear.pt").write_bytes(b"changed-sparse-with-new-size")
        assert bge_m3_hybrid_asset_fingerprint(str(model_path)) != first

    def test_download_contract_requires_sparse_and_colbert_heads(self, tmp_path):
        from scripts.download_bge_m3 import missing_required_assets

        model_path = tmp_path / "bge-m3"
        self._base_model(model_path)
        assert set(missing_required_assets(model_path)) == {
            "sparse_linear.pt",
            "colbert_linear.pt",
        }

        (model_path / "sparse_linear.pt").write_bytes(b"sparse")
        (model_path / "colbert_linear.pt").write_bytes(b"colbert")
        assert missing_required_assets(model_path) == ()
