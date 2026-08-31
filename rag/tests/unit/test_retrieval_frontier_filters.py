from __future__ import annotations

from langchain_core.documents import Document


def test_filter_scope_capabilities_are_typed_and_fail_closed():
    from core.retrieval.filter_scope import FilterCapability, FilterKind, FilterScope

    source = FilterScope.parse('source in ["a.md", "b.md"]')
    complex_scope = FilterScope.parse('source == "a.md" and page >= 3')
    invalid = FilterScope.parse("source ==")

    assert source.kind is FilterKind.SOURCE_SET
    assert source.sources == frozenset({"a.md", "b.md"})
    assert source.supports(FilterCapability.SOURCE_SET)
    assert complex_scope.kind is FilterKind.MILVUS_EXPRESSION
    assert complex_scope.supports(FilterCapability.MILVUS_EXPRESSION)
    assert not complex_scope.supports(FilterCapability.SOURCE_SET)
    assert invalid.kind is FilterKind.INVALID
    assert not invalid.supports(FilterCapability.MILVUS_EXPRESSION)


def test_bm25_source_filter_is_applied_before_scoring():
    from core.retrieval.bm25_retriever import BM25Retriever

    retriever = BM25Retriever()
    retriever.add_documents(
        [
            Document(page_content="shared keyword", metadata={"source": "allowed.md"}),
            Document(page_content="shared keyword keyword", metadata={"source": "blocked.md"}),
        ]
    )

    results = retriever.retrieve("keyword", top_k=5, allowed_sources={"allowed.md"})

    assert [result.document.metadata["source"] for result in results] == ["allowed.md"]


def test_complex_filter_excludes_legacy_bm25_and_graph(monkeypatch):
    from core.retrieval.hybrid_retriever import HybridRetriever, HybridRetrieverConfig

    retriever = HybridRetriever(
        config=HybridRetrieverConfig(
            enable_parallel=False,
            enable_native_sparse=False,
            enable_graph=True,
            enable_reranker=False,
            enable_mmr=False,
        )
    )
    calls = {"dense": 0, "sparse": 0, "graph": 0}

    def dense(*args, **kwargs):
        calls["dense"] += 1
        return []

    def sparse(*args, **kwargs):
        calls["sparse"] += 1
        return []

    def graph(*args, **kwargs):
        calls["graph"] += 1
        return []

    monkeypatch.setattr(retriever, "_dense_retrieve", dense)
    monkeypatch.setattr(retriever, "_sparse_retrieve", sparse)
    monkeypatch.setattr(retriever, "_graph_retrieve", graph)

    retriever.retrieve("q", filter_expr='source == "a.md" and page >= 3')

    assert calls == {"dense": 1, "sparse": 0, "graph": 0}
    retriever.close()


def test_sync_fallback_never_drops_filter(monkeypatch):
    from core.retrieval.hybrid_retriever import HybridRetriever, HybridRetrieverConfig

    retriever = HybridRetriever(
        config=HybridRetrieverConfig(enable_parallel=True, enable_reranker=False, enable_mmr=False)
    )
    seen = []

    def explode(*args, **kwargs):
        raise RuntimeError("fusion failure")

    def dense(query, filter_expr=None, *args, **kwargs):
        seen.append(filter_expr)
        return []

    monkeypatch.setattr(retriever, "_parallel_retrieve", explode)
    monkeypatch.setattr(retriever, "_dense_retrieve", dense)

    assert retriever.retrieve("q", filter_expr='source == "allowed.md"') == []
    assert seen == ['source == "allowed.md"']
    retriever.close()
