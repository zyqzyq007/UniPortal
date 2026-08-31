from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from langchain_core.documents import Document


def _docs(prefix: str) -> list[Document]:
    return [
        Document(
            page_content=f"{prefix} section alpha explains cooling and pressure.",
            metadata={"source": "manual.md", "title_path": "Chapter A", "parent_id": "p1"},
        ),
        Document(
            page_content=f"{prefix} section beta explains vibration and maintenance.",
            metadata={"source": "manual.md", "title_path": "Chapter B", "parent_id": "p2"},
        ),
    ]


def test_raptor_ready_generation_survives_restart_and_resolves_raw_evidence(tmp_path):
    from core.retrieval.raptor_store import RAPTOR_DB_PATH, RaptorStore

    assert RAPTOR_DB_PATH
    path = tmp_path / "raptor.db"
    store = RaptorStore(path)
    generation = store.build_source(
        "manual.md",
        _docs("current"),
        content_hash="hash-v1",
        embedding_fingerprint="embed-v1",
    )
    assert store.generation_status(generation) == "ready"
    store.close()

    reopened = RaptorStore(path)
    result = reopened.retrieve(
        "vibration maintenance overview",
        top_k=2,
        current_content_hash="hash-v1",
        embedding_fingerprint="embed-v1",
    )

    assert result.degraded is False
    assert result.documents
    assert all(doc.metadata["retrieval_source"] == "raptor" for doc in result.documents)
    assert all(doc.page_content.startswith("current section") for doc in result.documents)
    assert all(doc.metadata.get("raptor_summary") for doc in result.documents)
    reopened.close()


def test_raptor_building_generation_is_invisible_until_atomic_publish(tmp_path):
    from core.retrieval.raptor_store import RaptorStore

    store = RaptorStore(tmp_path / "raptor.db")
    old_generation = store.build_source(
        "manual.md",
        _docs("old"),
        content_hash="hash-old",
        embedding_fingerprint="embed-v1",
    )
    new_generation = store.stage_source(
        "manual.md",
        _docs("new"),
        content_hash="hash-new",
        embedding_fingerprint="embed-v1",
    )

    before = store.retrieve("maintenance", top_k=4)
    assert store.generation_status(new_generation) == "building"
    assert {doc.page_content.split()[0] for doc in before.documents} == {"old"}

    store.publish_generation(new_generation)
    after = store.retrieve("maintenance", top_k=4)

    assert store.generation_status(new_generation) == "ready"
    assert store.generation_status(old_generation) == "retired"
    assert {doc.page_content.split()[0] for doc in after.documents} == {"new"}
    store.close()


def test_raptor_failed_publish_keeps_prior_ready_generation(tmp_path, monkeypatch):
    from core.retrieval.raptor_store import RaptorStore

    store = RaptorStore(tmp_path / "raptor.db")
    old_generation = store.build_source(
        "manual.md",
        _docs("old"),
        content_hash="hash-old",
        embedding_fingerprint="embed-v1",
    )
    new_generation = store.stage_source(
        "manual.md",
        _docs("new"),
        content_hash="hash-new",
        embedding_fingerprint="embed-v1",
    )
    monkeypatch.setattr(
        store,
        "_validate_generation",
        lambda generation_id: (_ for _ in ()).throw(RuntimeError("invalid provenance")),
    )

    with pytest.raises(RuntimeError, match="invalid provenance"):
        store.publish_generation(new_generation)

    result = store.retrieve("maintenance", top_k=4)
    assert store.generation_status(old_generation) == "ready"
    assert store.generation_status(new_generation) == "building"
    assert {doc.page_content.split()[0] for doc in result.documents} == {"old"}
    store.close()


def test_raptor_stale_filter_delete_and_concurrent_reads_are_source_safe(tmp_path):
    from core.retrieval.raptor_store import RaptorStore

    store = RaptorStore(tmp_path / "raptor.db")
    store.build_source(
        "manual.md",
        _docs("tenant-a"),
        content_hash="hash-a",
        embedding_fingerprint="embed-v1",
    )
    other_docs = [
        Document(
            page_content="tenant-b maintenance overview",
            metadata={"source": "other.md", "title_path": "Overview", "parent_id": "b1"},
        )
    ]
    store.build_source(
        "other.md",
        other_docs,
        content_hash="hash-b",
        embedding_fingerprint="embed-v1",
    )

    filtered = store.retrieve(
        "maintenance overview",
        filter_expr='source == "manual.md"',
        top_k=4,
    )
    assert {doc.metadata["source"] for doc in filtered.documents} == {"manual.md"}

    stale = store.retrieve(
        "maintenance",
        filter_expr='source == "manual.md"',
        current_content_hash="wrong-hash",
        embedding_fingerprint="embed-v1",
    )
    assert stale.documents == []
    assert stale.degraded is True
    assert stale.error == "raptor_stale"

    with ThreadPoolExecutor(max_workers=4) as pool:
        snapshots = list(pool.map(lambda _: store.retrieve("maintenance", top_k=2), range(8)))
    assert all(snapshot.documents for snapshot in snapshots)

    assert store.remove_by_source("manual.md") == 1
    remaining = store.retrieve("maintenance overview", top_k=4)
    assert {doc.metadata["source"] for doc in remaining.documents} == {"other.md"}
    store.close()


def test_raptor_unsupported_filter_fails_closed_before_summary_fusion(tmp_path):
    from core.retrieval.raptor_store import RaptorStore

    store = RaptorStore(tmp_path / "raptor.db")
    store.build_source(
        "manual.md",
        _docs("current"),
        content_hash="hash-v1",
        embedding_fingerprint="embed-v1",
    )

    result = store.retrieve("overview", filter_expr='status == "active"')

    assert result.documents == []
    assert result.degraded is True
    assert result.error == "unsupported_filter"
    store.close()


def test_global_summary_workflow_fuses_raptor_raw_evidence(monkeypatch):
    from core.retrieval.raptor_store import RaptorRetrievalResult
    from core.retrieval.workflow import RetrievalWorkflow

    class Retriever:
        def retrieve(self, query, top_k=None, filter_expr=None, **kwargs):
            return [
                Document(
                    page_content="base fact",
                    metadata={"source": "manual.md", "rerank_probability": 0.9},
                )
            ]

    class Store:
        def retrieve(self, query, **kwargs):
            assert kwargs["filter_expr"] == 'source == "manual.md"'
            return RaptorRetrievalResult(
                [
                    Document(
                        page_content="raw global evidence",
                        metadata={
                            "source": "manual.md",
                            "retrieval_source": "raptor",
                            "raptor_score": 0.8,
                            "score": 0.8,
                        },
                    )
                ]
            )

    monkeypatch.setenv("RAPTOR_ENABLED", "true")
    monkeypatch.setattr("core.retrieval.raptor_store.get_raptor_store", lambda: Store())

    result = RetrievalWorkflow(retriever=Retriever()).retrieve(
        "summarize the overall maintenance guidance",
        filter_expr='source == "manual.md"',
        final_k=2,
    )

    assert {doc.page_content for doc in result.documents} == {
        "base fact",
        "raw global evidence",
    }
    assert result.diagnostics["channel_counts"]["raptor"] == 1


def test_raptor_ingestion_helper_is_additive_and_never_escapes(monkeypatch):
    from api.routers.documents import _build_raptor_if_enabled

    calls = []

    class Store:
        def build_source(self, source, documents, **kwargs):
            calls.append(
                (
                    source,
                    len(documents),
                    kwargs["content_hash"],
                    kwargs["embedding"],
                    kwargs["embedding_fingerprint"],
                )
            )
            raise RuntimeError("optional store unavailable")

    def unavailable_embeddings():
        raise RuntimeError("embedding unavailable")

    monkeypatch.setenv("RAPTOR_ENABLED", "true")
    monkeypatch.setattr("core.retrieval.raptor_store.get_raptor_store", lambda: Store())
    monkeypatch.setattr("models.embedding_models.get_embeddings", unavailable_embeddings)

    _build_raptor_if_enabled(_docs("current"), "manual.md", "hash-v1")

    assert calls == [("manual.md", 2, "hash-v1", None, "lexical")]
