from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from langchain_core.documents import Document


class _FakeM3:
    model_path = "models/fake-bge-m3"
    dimension = 3
    normalize_embeddings = True

    def __init__(self):
        self.calls = 0

    def encode_query_representation(self, text: str, *, return_colbert: bool = False):
        self.calls += 1
        return {
            "dense": [1.0, 0.0, 0.0],
            "sparse": {7: 0.5},
            "colbert": [[1.0, 0.0]] if return_colbert else None,
        }


def test_query_representation_uses_one_forward_for_all_heads():
    from core.retrieval.query_representation import QueryRepresentationProvider

    embedding = _FakeM3()
    result = QueryRepresentationProvider(embedding).encode("query", include_colbert=True)

    assert embedding.calls == 1
    assert result.dense == [1.0, 0.0, 0.0]
    assert result.sparse == {7: 0.5}
    assert result.colbert == [[1.0, 0.0]]
    assert result.degraded is False
    assert result.forward_count == 1


def test_query_representation_is_request_local_under_concurrency():
    from core.retrieval.query_representation import QueryRepresentationProvider

    embedding = _FakeM3()
    provider = QueryRepresentationProvider(embedding)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(provider.encode, ["q1", "q2", "q3", "q4"]))

    assert embedding.calls == 4
    assert all(result.forward_count == 1 for result in results)
    assert len({id(result) for result in results}) == 4


def test_query_representation_atomic_failure_uses_none_not_zero():
    from core.retrieval.query_representation import QueryRepresentationProvider

    class Broken:
        def encode_query_representation(self, text, *, return_colbert=False):
            raise RuntimeError("oom")

    result = QueryRepresentationProvider(Broken()).encode("query", include_colbert=True)

    assert result.dense is None
    assert result.sparse is None
    assert result.colbert is None
    assert result.degraded is True
    assert result.forward_count == 1
    assert result.errors == ("query_representation_unavailable",)


def test_embedding_cache_identity_includes_model_fingerprint():
    from core.retrieval.cache import cached_embedding_function, reset_embedding_cache

    class Base:
        normalize_embeddings = True

        def __init__(self, model_path, value):
            self.model_path = model_path
            self.value = value
            self.calls = 0

        def embed_query(self, text):
            self.calls += 1
            return [self.value]

        def embed_documents(self, texts):
            return [[self.value] for _ in texts]

    reset_embedding_cache()
    first = Base("model-a", 1.0)
    second = Base("model-b", 2.0)
    cached_a = cached_embedding_function(first)
    cached_b = cached_embedding_function(second)

    assert cached_a.embed_query("same") == [1.0]
    assert cached_a.embed_query("same") == [1.0]
    assert cached_b.embed_query("same") == [2.0]
    assert first.calls == 1
    assert second.calls == 1
    reset_embedding_cache()


def test_hybrid_reuses_one_query_forward_for_dense_and_sparse():
    from core.retrieval.hybrid_retriever import HybridRetriever, HybridRetrieverConfig

    class Hit:
        score = 0.8

        def __init__(self, text):
            self.text = text

        def to_document(self):
            return Document(page_content=self.text, metadata={"source": "s.md"})

    class Manager:
        def __init__(self):
            self.embedding_function = _FakeM3()
            self.dense_calls = 0
            self.sparse_calls = 0

        def search_by_vector(self, query_embedding, top_k, filter_expr=None):
            self.dense_calls += 1
            assert query_embedding == [1.0, 0.0, 0.0]
            return [Hit("dense")]

        def sparse_search(self, query_sparse, top_k, filter_expr=None):
            self.sparse_calls += 1
            assert query_sparse == {7: 0.5}
            return [Hit("sparse")]

        def search(self, *args, **kwargs):
            raise AssertionError("legacy dense encoding must not run")

    manager = Manager()
    retriever = HybridRetriever(
        dense_manager=manager,
        config=HybridRetrieverConfig(
            enable_query_reuse=True,
            enable_candidate_funnel=True,
            enable_native_sparse=True,
            enable_graph=False,
            enable_reranker=False,
            enable_mmr=False,
            final_top_k=2,
        ),
    )

    result = retriever.retrieve("one-pass", top_k=2)

    assert len(result) == 2
    assert manager.embedding_function.calls == 1
    assert manager.dense_calls == 1
    assert manager.sparse_calls == 1
    retriever.close()
