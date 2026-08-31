from __future__ import annotations

import numpy as np
from langchain_core.documents import Document


def _doc(text: str, score: float = 0.0) -> Document:
    return Document(page_content=text, metadata={"score": score})


def test_colbert_maxsim_is_deterministic_and_token_bounded():
    from core.retrieval.colbert_reranker import maxsim_score

    query = np.asarray([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], dtype=np.float32)
    document = np.asarray([[1.0, 0.0], [0.0, 1.0], [-1.0, -1.0]], dtype=np.float32)

    score = maxsim_score(
        query,
        document,
        max_query_tokens=2,
        max_document_tokens=2,
    )

    assert score == 1.0


def test_colbert_reranker_scores_only_bounded_candidates_and_normalizes_metadata():
    from core.retrieval.colbert_reranker import ColBERTReranker, ColBERTRerankerConfig

    class Embedding:
        def __init__(self):
            self.calls = []

        def encode_colbert_documents(self, texts, *, max_tokens, batch_size):
            self.calls.append((list(texts), max_tokens, batch_size))
            return [
                [[1.0, 0.0], [0.0, 1.0]],
                [[-1.0, 0.0], [0.0, -1.0]],
            ]

    embedding = Embedding()
    reranker = ColBERTReranker(
        embedding,
        ColBERTRerankerConfig(
            max_candidates=2,
            max_query_tokens=2,
            max_document_tokens=4,
            batch_size=2,
        ),
    )
    documents = [_doc("good"), _doc("bad"), _doc("not-scored", score=0.9)]

    result = reranker.rerank(
        [[1.0, 0.0], [0.0, 1.0]],
        documents,
        top_k=2,
    )

    assert embedding.calls == [(["good", "bad"], 4, 2)]
    assert [doc.page_content for doc in result.documents] == ["good", "bad", "not-scored"]
    assert result.documents[0].metadata["colbert_score"] == 1.0
    assert result.documents[1].metadata["colbert_score"] == 0.0
    assert "colbert_score" not in result.documents[2].metadata
    assert result.degraded is False


def test_colbert_unavailable_or_oom_preserves_prior_order_without_zero_scores():
    from core.retrieval.colbert_reranker import ColBERTReranker

    class Embedding:
        def encode_colbert_documents(self, *args, **kwargs):
            raise MemoryError("oom")

    documents = [_doc("first", 0.9), _doc("second", 0.8)]

    result = ColBERTReranker(Embedding()).rerank([[1.0, 0.0]], documents, top_k=2)

    assert result.documents == documents
    assert result.degraded is True
    assert result.error == "colbert_unavailable"
    assert all("colbert_score" not in doc.metadata for doc in result.documents)


def test_bge_m3_document_colbert_encoding_uses_one_bounded_forward():
    from models.bge_m3_embeddings import BGEM3Embeddings

    class Array:
        def __init__(self, value):
            self.value = value

        def tolist(self):
            return self.value

    class FlagModel:
        def __init__(self):
            self.calls = []

        def encode(self, texts, **kwargs):
            self.calls.append((list(texts), kwargs))
            return {
                "dense_vecs": [Array([1.0, 0.0]) for _ in texts],
                "lexical_weights": [{} for _ in texts],
                "colbert_vecs": [Array([[float(index), 0.0] for index in range(6)]) for _ in texts],
            }

    embedding = BGEM3Embeddings("unused", device="cpu", batch_size=8)
    model = FlagModel()
    embedding._flag_model = model
    embedding._flag_load_attempted = True
    embedding.hybrid_heads_available = True

    vectors = embedding.encode_colbert_documents(
        ["a", "b"],
        max_tokens=3,
        batch_size=2,
    )

    assert len(model.calls) == 1
    assert model.calls[0][1]["return_colbert_vecs"] is True
    assert model.calls[0][1]["batch_size"] == 2
    assert all(len(item) == 3 for item in vectors)
