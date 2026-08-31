"""Unit tests for the hybrid retriever's GraphRAG RRF fusion (third leg).

Focuses on the design.md v2 §6 changes and the F-04 closure:
- enable_graph=False is byte-for-byte identical to the pre-graph RRF (zero change)
- enable_graph=True fuses graph results as a normalised third leg
- the graph leg degrades to empty without affecting dense+sparse ranking
- filter_expr propagates to the graph leg

These tests stub the three legs directly (no Milvus/Ollama) to assert the RRF
math + gate behaviour deterministically.
"""

from __future__ import annotations

import pytest
from langchain_core.documents import Document

from core.retrieval.hybrid_retriever import (
    HybridRetriever,
    HybridRetrieverConfig,
    RetrievalResult,
)


def _doc(text: str, source: str = "s.md") -> Document:
    return Document(page_content=text, metadata={"source": source})


def _results(texts: list[str], leg: str = "dense") -> list[RetrievalResult]:
    return [
        RetrievalResult(document=_doc(t), score=1.0 / (i + 1), source=leg, rank=i + 1)
        for i, t in enumerate(texts)
    ]


@pytest.fixture
def retriever():
    """A HybridRetriever with stubbed dense/sparse managers (no I/O)."""
    r = HybridRetriever.__new__(HybridRetriever)
    r.config = HybridRetrieverConfig(enable_graph=False)
    r._dense_manager = None
    r._sparse_retriever = None
    r._initialized = False
    import concurrent.futures

    r._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
    return r


# ---------------------------------------------------------------------------
# F-04: enable_graph=False is byte-for-byte identical to two-leg RRF
# ---------------------------------------------------------------------------


class TestGraphGateOff:
    def test_graph_results_ignored_when_disabled(self, retriever):
        """When enable_graph=False, passing graph_results must NOT change scores."""
        dense = _results(["a", "b"], "dense")
        sparse = _results(["b", "c"], "sparse")
        graph = _results(["a", "z"], "graph")

        retriever.config.enable_graph = False
        two_leg = retriever._rrf_fusion(dense, sparse)
        three_leg_off = retriever._rrf_fusion(dense, sparse, graph)

        # Scores must be identical whether graph results are passed or not.
        assert [r.score for r in two_leg] == [r.score for r in three_leg_off]
        # And the graph-only doc 'z' must not appear.
        contents = [r.document.page_content for r in three_leg_off]
        assert "z" not in contents

    def test_normalisation_excludes_graph_weight_when_off(self, retriever):
        """dense_w + sparse_w must equal 1.0 when graph is off (no leakage)."""
        retriever.config = HybridRetrieverConfig(
            enable_graph=False, dense_weight=0.5, sparse_weight=0.5, graph_weight=0.4
        )
        dense = _results(["a"], "dense")
        result = retriever._rrf_fusion(dense, [], None)
        # dense_w = 0.5/(0.5+0.5) = 0.5 (graph_weight excluded); rank=1, k=60.
        assert result[0].score == pytest.approx(0.5 / 61, rel=1e-9)


# ---------------------------------------------------------------------------
# F-04: enable_graph=True fuses three normalised legs
# ---------------------------------------------------------------------------


class TestGraphGateOn:
    def test_graph_doc_joins_fusion(self, retriever):
        retriever.config = HybridRetrieverConfig(
            enable_graph=True, dense_weight=0.5, sparse_weight=0.5, graph_weight=0.4
        )
        dense = _results(["a"], "dense")
        sparse = _results(["b"], "sparse")
        graph = _results(["c"], "graph")

        fused = retriever._rrf_fusion(dense, sparse, graph)
        contents = {r.document.page_content for r in fused}
        assert {"a", "b", "c"} == contents

    def test_graph_weight_normalised_with_dense_sparse(self, retriever):
        """When graph leg is empty, two-leg normalisation applies (no distortion)."""
        retriever.config = HybridRetrieverConfig(
            enable_graph=True, dense_weight=0.5, sparse_weight=0.5, graph_weight=0.4
        )
        dense = _results(["a"], "dense")
        fused = retriever._rrf_fusion(dense, [], [])
        # graph empty → use_graph=False even though enable_graph=True;
        # dense_w = 0.5/(0.5+0.5) = 0.5 (same as gate-off case).
        assert fused[0].score == pytest.approx(0.5 / 61, rel=1e-9)

    def test_graph_hit_boosts_doc_present_in_dense(self, retriever):
        """A doc hit by both dense AND graph ranks higher than dense-only."""
        retriever.config = HybridRetrieverConfig(
            enable_graph=True, dense_weight=0.5, sparse_weight=0.5, graph_weight=0.4
        )
        # 'shared' is rank-1 in dense AND rank-1 in graph; 'only_dense' is rank-2.
        dense = _results(["shared", "only_dense"], "dense")
        graph = _results(["shared"], "graph")

        fused = retriever._rrf_fusion(dense, [], graph)
        by_text = {r.document.page_content: r.score for r in fused}
        assert by_text["shared"] > by_text["only_dense"]


# ---------------------------------------------------------------------------
# REQ-GR-003: graph leg failure degrades to empty (no crash, no score pollution)
# ---------------------------------------------------------------------------


class TestGraphDegradation:
    def test_graph_retrieve_returns_empty_when_disabled(self, retriever):
        retriever.config.enable_graph = False
        assert retriever._graph_retrieve("q") == []

    def test_graph_retrieve_swallows_exceptions(self, retriever, monkeypatch):
        """If get_graph_retriever raises, the leg returns [] not an exception."""
        retriever.config.enable_graph = True

        def boom():
            raise RuntimeError("graph store corrupted")

        import core.retrieval.graph_retriever as gr_mod

        monkeypatch.setattr(gr_mod, "get_graph_retriever", boom)
        assert retriever._graph_retrieve("q") == []


# ---------------------------------------------------------------------------
# F-01: filter_expr propagates to the graph leg
# ---------------------------------------------------------------------------


class TestFilterPropagation:
    def test_graph_retrieve_forwards_filter_expr(self, retriever, monkeypatch):
        """_graph_retrieve passes filter_expr through to the graph retriever."""
        retriever.config.enable_graph = True
        captured = {}

        class StubGraphRetriever:
            def retrieve(self, query, top_k=5, filter_expr=None):
                captured["filter"] = filter_expr
                return []

        import core.retrieval.graph_retriever as gr_mod

        monkeypatch.setattr(gr_mod, "get_graph_retriever", lambda: StubGraphRetriever())
        retriever._graph_retrieve("q", filter_expr='source == "x.md"')
        assert captured["filter"] == 'source == "x.md"'
