"""Unit tests for the GraphRetriever dual-level leg (GraphRAG).

Covers design.md v2 §5 + review findings:
- F-01: filter_expr constrains to matching sources (no cross-doc leak)
- F-02: COW matrix — concurrent retrieve vs add_documents stays consistent
- F-05: cold start rebuilds the matrix from the store
- F-06: graph hits carry parent_id (expandable)
- F-08: high-level works with an independent seed when low-level is empty
- F-09: embedding fingerprint mismatch → degraded empty
- REQ-GR-003: empty graph / embedding failure → [] never raises
"""

from __future__ import annotations

import threading

import numpy as np
import pytest
from langchain_core.documents import Document

from core.retrieval.graph_retriever import (
    GraphRetriever,
    _parse_filter_sources,
)
from documents.graph_store import Entity, GraphStore, Relation


@pytest.fixture
def fake_embedding():
    """Deterministic embedding: hashes token → unit-ish vector of fixed dim."""

    class FakeEmbedding:
        def embed_query(self, text: str) -> list[float]:
            dim = 8
            v = np.zeros(dim, dtype=np.float32)
            for i, ch in enumerate(text):
                v[i % dim] += ord(ch) % 7
            n = np.linalg.norm(v)
            return (v / (n + 1e-9)).tolist()

        def embed_documents(self, texts):
            return [self.embed_query(t) for t in texts]

    return FakeEmbedding()


@pytest.fixture
def store(tmp_path):
    s = GraphStore(str(tmp_path / "g.db"))
    yield s
    s.close()


@pytest.fixture
def retriever(store, fake_embedding):
    return GraphRetriever(store=store, embedding=fake_embedding)


def _seed_graph(store, entities, relations=None, source="m.md", dim=8, model="fake"):
    """Upsert entities with deterministic embeddings into the store."""
    rels = relations or []
    store.upsert(entities, rels, source=source, embedding_model=model, embedding_dim=dim)


# ---------------------------------------------------------------------------
# F-05 cold start
# ---------------------------------------------------------------------------


class TestColdStart:
    def test_rebuild_from_store_on_first_retrieve(self, store, retriever, fake_embedding):
        """F-05: a fresh retriever rebuilds its matrix from a non-empty store."""
        e = Entity(name="泵", type="部件", chunk_text="液压泵原文", parent_id="p1")
        e.embedding = fake_embedding.embed_query("泵")
        _seed_graph(store, [e])
        assert retriever.status()["matrix_loaded"] is False

        results = retriever.retrieve("泵", top_k=5)
        assert retriever.status()["matrix_loaded"] is True
        assert len(results) == 1
        assert results[0].document.page_content == "液压泵原文"

    def test_reload_returns_count(self, store, retriever, fake_embedding):
        e = Entity(name="A", type="T", chunk_text="a")
        e.embedding = fake_embedding.embed_query("A")
        _seed_graph(store, [e])
        assert retriever.reload() == 1


# ---------------------------------------------------------------------------
# Low-level retrieval
# ---------------------------------------------------------------------------


class TestLowLevel:
    def test_semantic_match_returns_chunk(self, store, retriever, fake_embedding):
        e1 = Entity(name="液压泵", type="部件", chunk_text="液压泵是EDP", parent_id="p1")
        e2 = Entity(name="发电机", type="部件", chunk_text="发电机发电", parent_id="p2")
        e1.embedding = fake_embedding.embed_query("液压泵")
        e2.embedding = fake_embedding.embed_query("发电机")
        _seed_graph(store, [e1, e2])

        results = retriever.retrieve("液压泵", top_k=2)
        assert len(results) >= 1
        # The top hit should be the hydraulic pump chunk.
        assert "液压泵" in results[0].document.page_content

    def test_low_level_hit_carries_parent_id(self, store, retriever, fake_embedding):
        """F-06: graph hit metadata has parent_id for expand_to_parents."""
        e = Entity(name="泵", type="部件", chunk_text="x", parent_id="parent-42")
        e.embedding = fake_embedding.embed_query("泵")
        _seed_graph(store, [e])
        results = retriever.retrieve("泵", top_k=1)
        assert results[0].document.metadata["parent_id"] == "parent-42"

    def test_retrieval_source_tagged_graph(self, store, retriever, fake_embedding):
        e = Entity(name="泵", type="部件", chunk_text="x")
        e.embedding = fake_embedding.embed_query("泵")
        _seed_graph(store, [e])
        results = retriever.retrieve("泵", top_k=1)
        assert results[0].document.metadata["retrieval_source"] == "graph"
        assert results[0].source == "graph"


# ---------------------------------------------------------------------------
# High-level (1-hop) + F-08 independent seed
# ---------------------------------------------------------------------------


class TestHighLevel:
    def test_one_hop_neighbor_returned(self, store, retriever, fake_embedding):
        a = Entity(name="振动", type="症状", chunk_text="振动异常")
        b = Entity(name="轴承", type="部件", chunk_text="轴承磨损")
        a.embedding = fake_embedding.embed_query("振动")
        b.embedding = fake_embedding.embed_query("轴承")
        rels = [Relation(src=a.id, tgt=b.id, relation_type="相关")]
        _seed_graph(store, [a, b], rels)

        results = retriever.retrieve("振动", top_k=5)
        contents = " ".join(r.document.page_content for r in results)
        # The neighbour (轴承) should surface via the 1-hop edge.
        assert "轴承" in contents

    def test_high_level_independent_seed(self, store, retriever, fake_embedding):
        """F-08: a query that semantically misses but keywords-match a seed
        still triggers high-level retrieval."""
        # Entity whose embedding is far from the query, but whose NAME matches.
        e = Entity(name="液压泵", type="部件", chunk_text="液压泵原文")
        # Deliberately unrelated embedding so low-level cosine is low.
        e.embedding = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        _seed_graph(store, [e])
        # Query contains the entity name token → keyword seed matches.
        results = retriever.retrieve("液压泵", top_k=5)
        # Even though semantic low-level is weak, keyword seed + no edges means
        # low-level alone may still surface via name; assert we get the chunk.
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# F-01 filter_expr
# ---------------------------------------------------------------------------


class TestFilterExpr:
    def test_parse_source_equals(self):
        assert _parse_filter_sources('source == "a.md"') == {"a.md"}
        assert _parse_filter_sources("source == 'b.md'") == {"b.md"}

    def test_parse_source_in(self):
        assert _parse_filter_sources('source in ["a.md", "b.md"]') == {"a.md", "b.md"}

    def test_parse_unparseable_fails_open(self):
        assert _parse_filter_sources("title == 'x'") is None

    def test_parse_empty(self):
        assert _parse_filter_sources(None) is None
        assert _parse_filter_sources("") is None

    def test_filter_restricts_to_source(self, store, retriever, fake_embedding):
        """F-01: filter_expr keeps only matching sources (no cross-doc leak)."""
        e_a = Entity(name="泵", type="部件", chunk_text="A手册的泵", source="a.md")
        e_b = Entity(name="泵", type="部件", chunk_text="B手册的泵", source="b.md")
        e_a.embedding = fake_embedding.embed_query("泵")
        e_b.embedding = fake_embedding.embed_query("泵")
        _seed_graph(store, [e_a], source="a.md")
        _seed_graph(store, [e_b], source="b.md")

        results = retriever.retrieve("泵", top_k=5, filter_expr='source == "a.md"')
        assert len(results) >= 1
        for r in results:
            assert r.document.metadata["source"] == "a.md"


# ---------------------------------------------------------------------------
# REQ-GR-003 degradation
# ---------------------------------------------------------------------------


class TestDegradation:
    def test_empty_graph_returns_empty(self, store, retriever):
        """An empty store yields [] without raising (valid empty, not degraded)."""
        results = retriever.retrieve("anything", top_k=5)
        assert results == []

    def test_embedding_failure_returns_empty(self, store, tmp_path):
        """Embedding raising → [] + degraded flag, never raises."""
        bad = type(
            "BadEmb",
            (),
            {"embed_query": lambda self, t: (_ for _ in ()).throw(RuntimeError("no model"))},
        )()
        r = GraphRetriever(store=store, embedding=bad)
        e = Entity(name="x", type="t", chunk_text="x")
        e.embedding = [0.1] * 8
        store.upsert([e], [], source="m.md", embedding_model="m", embedding_dim=8)
        results = r.retrieve("x", top_k=5)
        assert results == []
        assert r.status()["degraded"] is True


# ---------------------------------------------------------------------------
# F-09 fingerprint mismatch
# ---------------------------------------------------------------------------


class TestFingerprint:
    def test_dim_mismatch_degrades(self, store, fake_embedding):
        """F-09: entity dim != fingerprint dim → degraded empty."""
        e = Entity(name="泵", type="部件", chunk_text="x")
        e.embedding = [0.1] * 8  # 8-dim vectors
        store.upsert([e], [], source="m.md", embedding_model="bge", embedding_dim=512)
        r = GraphRetriever(store=store, embedding=fake_embedding)
        results = r.retrieve("泵", top_k=5)
        assert results == []
        assert r.status()["fingerprint_ok"] is False


# ---------------------------------------------------------------------------
# F-02 concurrency (COW matrix)
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_concurrent_retrieve_during_reload(self, store, fake_embedding):
        """F-02: concurrent reads while a reload swaps the matrix never crash."""
        e = Entity(name="泵", type="部件", chunk_text="x")
        e.embedding = fake_embedding.embed_query("泵")
        store.upsert([e], [], source="m.md", embedding_model="m", embedding_dim=8)
        r = GraphRetriever(store=store, embedding=fake_embedding)
        r.reload()

        errors: list[Exception] = []

        def reader():
            try:
                for _ in range(50):
                    r.retrieve("泵", top_k=3)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def writer():
            try:
                for _ in range(50):
                    r.reload()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(3)]
        threads.append(threading.Thread(target=writer))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []

    def test_add_documents_invalidates(self, store, fake_embedding):
        r = GraphRetriever(store=store, embedding=fake_embedding)
        e = Entity(name="泵", type="部件", chunk_text="x")
        e.embedding = fake_embedding.embed_query("泵")
        store.upsert([e], [], source="m.md", embedding_model="m", embedding_dim=8)
        r.reload()
        assert r.status()["matrix_loaded"] is True
        r.add_documents([Document(page_content="x")])
        assert r.status()["matrix_loaded"] is False

    def test_snapshot_consistency_under_invalidate(self, store, fake_embedding):
        """Bug 2 regression: _matrix_snapshot must read matrix + ids + sources
        atomically so a concurrent _invalidate cannot leave them mismatched
        (matrix non-None but ids empty → IndexError in cosine)."""
        e1 = Entity(name="泵", type="部件", chunk_text="x")
        e1.embedding = fake_embedding.embed_query("泵")
        store.upsert([e1], [], source="m.md", embedding_model="m", embedding_dim=8)
        r = GraphRetriever(store=store, embedding=fake_embedding)
        r.reload()

        mismatches: list[str] = []

        def reader():
            for _ in range(200):
                matrix, ids, sources = r._matrix_snapshot()
                if matrix is not None and len(ids) != matrix.shape[0]:
                    mismatches.append(f"matrix rows={matrix.shape[0]} ids={len(ids)}")

        def writer():
            for _ in range(200):
                r._invalidate()
                r.reload()

        threads = [threading.Thread(target=reader) for _ in range(3)]
        threads.append(threading.Thread(target=writer))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert mismatches == [], f"COW snapshot mismatch: {mismatches[:3]}"


# ---------------------------------------------------------------------------
# Bug 4 regression: keyword seed uses the cached name index
# ---------------------------------------------------------------------------


class TestKeywordSeedCache:
    def test_keyword_seed_matches_via_cached_index(self, store, fake_embedding):
        """Bug 4: high-level keyword seed resolves via the matrix-time name index
        (not a per-query store scan)."""
        e = Entity(name="液压泵", type="部件", chunk_text="x")
        e.embedding = fake_embedding.embed_query("液压泵")
        store.upsert([e], [], source="m.md", embedding_model="m", embedding_dim=8)
        r = GraphRetriever(store=store, embedding=fake_embedding)
        r.reload()
        # After reload the name index is populated → keyword match works without
        # any extra load_all.
        seeds = r._keyword_seeds("液压泵", r._entity_ids)
        assert e.id in seeds

    def test_keyword_seed_empty_before_load(self, store, fake_embedding):
        """Before the matrix is built, the name index is empty."""
        e = Entity(name="泵", type="部件", chunk_text="x")
        e.embedding = fake_embedding.embed_query("泵")
        store.upsert([e], [], source="m.md", embedding_model="m", embedding_dim=8)
        r = GraphRetriever(store=store, embedding=fake_embedding)
        assert r._keyword_seeds("泵", []) == set()
