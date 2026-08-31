from __future__ import annotations

from langchain_core.documents import Document


def _doc(text: str, *, parent_id: str | None = None, source: str = "s.md", score=1.0):
    metadata = {"source": source, "score": score}
    if parent_id is not None:
        metadata["parent_id"] = parent_id
    return Document(page_content=text, metadata=metadata)


def test_budget_resolution_keeps_internal_stages_independent():
    from core.retrieval.hybrid_retriever import HybridRetrieverConfig

    config = HybridRetrieverConfig(
        candidate_k=16,
        rerank_k=12,
        selection_k=8,
        final_top_k=5,
    )

    budgets = config.resolve_budgets(top_k=4)

    assert (budgets.candidate_k, budgets.rerank_k, budgets.selection_k, budgets.final_k) == (
        16,
        12,
        8,
        4,
    )
    assert budgets.degraded is False


def test_budget_resolution_clamps_invalid_order_and_marks_degraded():
    from core.retrieval.hybrid_retriever import HybridRetrieverConfig

    config = HybridRetrieverConfig(
        candidate_k=2,
        rerank_k=3,
        selection_k=4,
        final_top_k=5,
    )

    budgets = config.resolve_budgets()

    assert budgets.candidate_k >= budgets.rerank_k >= budgets.selection_k >= budgets.final_k
    assert budgets.degraded is True


def test_parent_aware_selector_backfills_distinct_evidence():
    from core.retrieval.selector import select_evidence

    ranked = [
        _doc("p1 best", parent_id="p1", score=0.99),
        _doc("p1 duplicate", parent_id="p1", score=0.98),
        _doc("p2", parent_id="p2", score=0.80),
        _doc("orphan", source="other.md", score=0.70),
    ]

    selected = select_evidence(ranked, final_k=3, selection_k=2)

    assert [doc.page_content for doc in selected] == ["p1 best", "p2", "orphan"]


def test_selector_allocates_facet_coverage_before_rank_fill():
    from core.retrieval.selector import select_evidence

    ranked = [
        Document(
            page_content="A-high",
            metadata={"parent_id": "a1", "matched_facets": ["A"], "score": 0.99},
        ),
        Document(
            page_content="A-second",
            metadata={"parent_id": "a2", "matched_facets": ["A"], "score": 0.98},
        ),
        Document(
            page_content="B-lower",
            metadata={"parent_id": "b1", "matched_facets": ["B"], "score": 0.70},
        ),
    ]

    selected = select_evidence(ranked, final_k=2, selection_k=2, facets=("A", "B"))

    assert [doc.page_content for doc in selected] == ["A-high", "B-lower"]


def test_hybrid_pipeline_reranks_more_than_final_and_backfills(monkeypatch):
    from core.retrieval.hybrid_retriever import (
        HybridRetriever,
        HybridRetrieverConfig,
        RetrievalResult,
    )

    docs = [
        _doc("p1 best", parent_id="p1", score=0.99),
        _doc("p1 duplicate", parent_id="p1", score=0.98),
        _doc("p2", parent_id="p2", score=0.80),
    ]
    retriever = HybridRetriever(
        config=HybridRetrieverConfig(
            enable_parallel=False,
            enable_native_sparse=False,
            enable_graph=False,
            enable_reranker=True,
            enable_mmr=False,
            candidate_k=6,
            rerank_k=3,
            selection_k=3,
            final_top_k=2,
        )
    )
    monkeypatch.setattr(
        retriever,
        "_dense_retrieve",
        lambda *args, **kwargs: [
            RetrievalResult(document=doc, score=doc.metadata["score"], source="dense", rank=i)
            for i, doc in enumerate(docs, 1)
        ],
    )
    monkeypatch.setattr(retriever, "_sparse_retrieve", lambda *args, **kwargs: [])
    monkeypatch.setattr(retriever, "_graph_retrieve", lambda *args, **kwargs: [])
    seen = {}

    def _rerank(_query, candidates, top_k):
        seen["candidate_count"] = len(candidates)
        seen["top_k"] = top_k
        return candidates[:top_k]

    monkeypatch.setattr(retriever, "_rerank", _rerank)

    result = retriever.retrieve("q", top_k=2)

    assert seen == {"candidate_count": 3, "top_k": 3}
    assert [doc.page_content for doc in result] == ["p1 best", "p2"]
    retriever.close()
