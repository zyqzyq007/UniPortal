"""End-to-end tests for the GraphRAG retrieval leg (ingestion → retrieval).

Exercises the full ingestion→graph-build→retrieval data flow with mocked LLM
and embedding singletons (no Ollama/Milvus), plus the hot-path degradation
invariants mandated by core/AGENTS.md §3 and review/tracking.md:

- upload → extraction → graph_store populated → graph leg surfaces in retrieve
- graph leg failure (LLM down) → hybrid degrades to dense+sparse, retrieval
  relevance NOT polluted (不可用≠0)
- document delete → graph_store cleaned + retriever matrix invalidated
- GRAPH_RAG_ENABLED=false → no graph writes/reads (zero-change default)
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

sys.path.insert(0, ".")

from core.retrieval.graph_retriever import get_graph_retriever, reset_graph_retriever
from documents.graph_store import Entity, Relation, get_graph_store, reset_graph_store


@pytest.fixture
def graph_redirect(tmp_path, monkeypatch):
    """Redirect graph_store DEFAULT_DB_PATH to tmp + reset singletons.

    Applied to every test class so no get_graph_store() call (even from tests
    that don't touch the retriever) ever lands in the real ./data dir.
    """
    db = tmp_path / "graph_store.db"
    monkeypatch.setattr("documents.graph_store.DEFAULT_DB_PATH", str(db))
    reset_graph_store()
    reset_graph_retriever()
    yield
    reset_graph_retriever()
    reset_graph_store()


@pytest.fixture
def fake_embeddings():
    """Deterministic BGE stand-in returning unit vectors of a fixed dim."""

    class FakeEmb:
        def embed_query(self, text):
            import numpy as np

            dim = 16
            v = np.zeros(dim, dtype=np.float32)
            for i, ch in enumerate(text):
                v[i % dim] += ord(ch) % 11
            n = np.linalg.norm(v)
            return (v / (n + 1e-9)).tolist()

        def embed_documents(self, texts):
            return [self.embed_query(t) for t in texts]

    return FakeEmb()


@pytest.fixture
def isolated_graph(graph_redirect, fake_embeddings):
    """Point graph_store + retriever singletons at a tmp DB + fake embedding."""
    # Inject the fake embedding into the graph retriever singleton.
    retriever = get_graph_retriever()
    retriever._embedding = fake_embeddings
    yield retriever


# ---------------------------------------------------------------------------
# REQ-GR-008: GRAPH_RAG_ENABLED=false → zero graph activity
# ---------------------------------------------------------------------------


class TestGateOff:
    @pytest.fixture(autouse=True)
    def _redirect(self, graph_redirect):
        """Ensure even the gate-off tests never touch the real DB."""

    def test_extract_noop_when_disabled(self, monkeypatch):
        """_extract_graph_if_enabled returns immediately when disabled."""
        import api.routers.documents as docs_mod

        monkeypatch.setattr(docs_mod, "GRAPH_RAG_ENABLED", False)
        store_before = get_graph_store().count()
        docs_mod._extract_graph_if_enabled(
            [Document(page_content="x")], source="s.md", file_hash="h"
        )
        assert get_graph_store().count() == store_before

    def test_remove_noop_when_disabled(self, monkeypatch):
        import api.routers.documents as docs_mod

        monkeypatch.setattr(docs_mod, "GRAPH_RAG_ENABLED", False)
        # Should not raise even with a bogus source.
        docs_mod._remove_graph_if_enabled("nonexistent.md")


# ---------------------------------------------------------------------------
# Ingestion → graph build (with mocked extractor)
# ---------------------------------------------------------------------------


class TestIngestionFlow:
    def test_extract_populates_graph_store(self, monkeypatch, isolated_graph, fake_embeddings):
        """_extract_graph_if_enabled (enabled) writes entities via the extractor."""
        from types import SimpleNamespace

        import api.routers.documents as docs_mod

        monkeypatch.setattr(docs_mod, "GRAPH_RAG_ENABLED", True)

        # Stub the extractor to return deterministic entities.
        ents = [
            Entity(name="液压泵", type="部件", chunk_text="液压泵是 EDP", parent_id="p1"),
            Entity(name="发动机", type="系统", chunk_text="发动机含燃油系统", parent_id="p2"),
        ]
        rels = [Relation(src=ents[0].id, tgt=ents[1].id, relation_type="属于")]
        fake_extractor = MagicMock()
        fake_extractor.extract.return_value = (ents, rels)
        monkeypatch.setattr("documents.graph_extractor.get_graph_extractor", lambda: fake_extractor)
        monkeypatch.setattr("models.embedding_models.get_embeddings", lambda: fake_embeddings)
        monkeypatch.setattr(
            "utils.env_utils.resolve_embedding_settings",
            lambda: SimpleNamespace(model_source="fake-bge", dimension=16),
        )

        docs_mod._extract_graph_if_enabled(
            [Document(page_content="液压泵属于发动机系统")],
            source="manual.md",
            file_hash="h1",
        )

        store = get_graph_store()
        assert store.count() == 2
        assert store.meta("embedding_model") == "fake-bge"
        assert store.meta("embedding_dim") == "16"

    def test_extract_failure_does_not_block(self, monkeypatch, isolated_graph):
        """If the extractor raises, _extract_graph_if_enabled swallows it
        (main ingestion already indexed into Milvus/BM25)."""
        import api.routers.documents as docs_mod

        monkeypatch.setattr(docs_mod, "GRAPH_RAG_ENABLED", True)
        fake_extractor = MagicMock()
        fake_extractor.extract.side_effect = RuntimeError("ollama down")
        monkeypatch.setattr("documents.graph_extractor.get_graph_extractor", lambda: fake_extractor)

        # Must NOT raise.
        docs_mod._extract_graph_if_enabled(
            [Document(page_content="x")], source="s.md", file_hash="h"
        )
        assert get_graph_store().count() == 0


# ---------------------------------------------------------------------------
# Retrieval: graph leg surfaces hits
# ---------------------------------------------------------------------------


class TestRetrievalFlow:
    def test_graph_leg_returns_chunk(self, isolated_graph, fake_embeddings):
        """After ingestion, the graph retriever returns the backing chunk."""
        store = get_graph_store()
        e = Entity(name="起落架", type="系统", chunk_text="起落架收放系统", parent_id="p1")
        e.embedding = fake_embeddings.embed_query("起落架")
        store.upsert([e], [], source="manual.md", embedding_model="fake-bge", embedding_dim=16)

        results = get_graph_retriever().retrieve("起落架", top_k=5)
        assert len(results) >= 1
        assert "起落架" in results[0].document.page_content
        assert results[0].document.metadata["retrieval_source"] == "graph"

    def test_graph_leg_degradation_not_polluting(self, isolated_graph):
        """Empty graph → [] but no exception (不可用≠0)."""
        results = get_graph_retriever().retrieve("anything", top_k=5)
        assert results == []
        # status reflects a valid empty graph, not a crash.
        st = get_graph_retriever().status()
        assert st["entity_count"] == 0


# ---------------------------------------------------------------------------
# Document deletion cleans the graph (REQ-GR-005)
# ---------------------------------------------------------------------------


class TestDeletionFlow:
    def test_remove_cleans_graph_store(self, monkeypatch, isolated_graph, fake_embeddings):
        import api.routers.documents as docs_mod

        store = get_graph_store()
        e = Entity(name="燃油泵", type="部件", chunk_text="燃油泵供油", parent_id="p1")
        e.embedding = fake_embeddings.embed_query("燃油泵")
        store.upsert([e], [], source="fuel.md", embedding_model="fake-bge", embedding_dim=16)
        assert store.count() == 1

        monkeypatch.setattr(docs_mod, "GRAPH_RAG_ENABLED", True)
        docs_mod._remove_graph_if_enabled("fuel.md")
        assert store.count() == 0
        # retriever matrix invalidated.
        assert get_graph_retriever().status()["matrix_loaded"] is False

    def test_remove_bumps_cache_version(self, monkeypatch, isolated_graph, fake_embeddings):
        """Bug 1 regression: _remove_graph_if_enabled self-contains the cache
        bump so a deletion never leaves stale graph hits in the retrieval cache."""
        import api.routers.documents as docs_mod
        from core.retrieval.cache import get_retrieval_cache_version

        store = get_graph_store()
        e = Entity(name="刹车", type="系统", chunk_text="刹车系统")
        e.embedding = fake_embeddings.embed_query("刹车")
        store.upsert([e], [], source="brake.md", embedding_model="fake-bge", embedding_dim=16)

        before = get_retrieval_cache_version()
        monkeypatch.setattr(docs_mod, "GRAPH_RAG_ENABLED", True)
        docs_mod._remove_graph_if_enabled("brake.md")
        after = get_retrieval_cache_version()
        assert after > before, "graph delete must bump retrieval cache version"


# ---------------------------------------------------------------------------
# Regression: GenerateSkill does not drop graph hits (F-12 / REQ-GR-012)
# ---------------------------------------------------------------------------


class TestSharedStateIntegrity:
    def test_graph_hit_carries_source_for_guardrail(self, isolated_graph, fake_embeddings):
        """Graph hits must carry metadata['source'] (guardrail source check)."""
        store = get_graph_store()
        e = Entity(name="APU", type="部件", chunk_text="辅助动力装置", parent_id="p1")
        e.embedding = fake_embeddings.embed_query("APU")
        store.upsert([e], [], source="apu.md", embedding_model="fake-bge", embedding_dim=16)

        results = get_graph_retriever().retrieve("APU", top_k=5)
        assert results[0].document.metadata.get("source") == "apu.md"

    def test_graph_hit_carries_parent_id_for_expand(self, isolated_graph, fake_embeddings):
        """Graph hits must carry parent_id so expand_to_parents can widen them."""
        store = get_graph_store()
        e = Entity(name="刹车", type="系统", chunk_text="刹车系统", parent_id="parent-99")
        e.embedding = fake_embeddings.embed_query("刹车")
        store.upsert([e], [], source="brake.md", embedding_model="fake-bge", embedding_dim=16)

        results = get_graph_retriever().retrieve("刹车", top_k=5)
        assert results[0].document.metadata.get("parent_id") == "parent-99"
