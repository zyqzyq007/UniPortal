#!/usr/bin/env python3
"""
F-03 — GraphRAG entity embedding dimension migration regression guards.

Covers docs/specs/retrieval-backend-modernization §3.4 (F-03):
- graph_store entity embeddings are persisted BLOBs (512d old → 1024d new).
- graph_retriever's _build_matrix_locked detects dim mismatch → degraded empty
  (NOT auto re-embed — this is the safety net, migration is explicit).
- GraphStore.update_embeddings re-embeds + updates BLOBs + graph_meta.
- After migration, no stale-dim BLOBs remain.

Run: pytest tests/unit/test_graph_m3_migration.py -v
"""

from __future__ import annotations

import numpy as np
import pytest

from documents.graph_store import Entity, GraphStore, make_entity_id


@pytest.fixture
def store(tmp_path):
    s = GraphStore(str(tmp_path / "g_migrate.db"))
    yield s
    s.close()


def _make_entity(name: str, dim: int, source: str = "s1") -> Entity:
    """Entity with a fake embedding of the given dimension."""
    vec = np.ones(dim, dtype=np.float32).tolist()
    return Entity(
        name=name,
        type="TYPE",
        description=f"desc {name}",
        embedding=vec,
        source=source,
    )


class TestDimMismatchGuard:
    """F-03: graph_retriever degrades to empty (not crash, not auto-re-embed)
    when persisted BLOBs have a different dim than the expected query dim."""

    def test_old_dim_blobs_cause_degraded_empty(self, store, tmp_path):
        """Entities persisted with 512d; retriever expects 1024d → degraded."""
        from core.retrieval.graph_retriever import GraphRetriever

        # Persist entities with 512d embeddings (old BGE-small).
        store.upsert(
            source="s1",
            entities=[_make_entity("alpha", 512), _make_entity("beta", 512)],
            relations=[],
            embedding_model="BAAI/bge-small-zh-v1.5",
            embedding_dim=512,
        )

        class FakeEmbedding1024:
            def embed_query(self, text):
                return np.ones(1024, dtype=np.float32).tolist()

            def embed_documents(self, texts):
                return [self.embed_query(t) for t in texts]

        # Retriever expects 1024d (new BGE-M3) but store has 512d.
        retriever = GraphRetriever(store=store, embedding=FakeEmbedding1024())
        results = retriever.retrieve("alpha", top_k=5)
        assert results == [], "Dim mismatch should degrade to empty, not crash"
        assert retriever._degraded is True or retriever._matrix is None

    def test_matching_dim_does_not_degrade(self, store, tmp_path):
        """Sanity: when dims match, the matrix builds and _degraded stays False.
        (Result count depends on query-entity similarity which is orthogonal to
        the dim-mismatch guard being tested here.)"""
        from core.retrieval.graph_retriever import GraphRetriever

        class HashEmbedding8:
            def embed_query(self, text):
                v = np.zeros(8, dtype=np.float32)
                for i, ch in enumerate(text):
                    v[i % 8] += ord(ch) % 7
                n = np.linalg.norm(v)
                return (v / (n + 1e-9)).tolist()

            def embed_documents(self, texts):
                return [self.embed_query(t) for t in texts]

        emb = HashEmbedding8()
        store.upsert(
            source="s1",
            entities=[
                Entity(
                    name="alpha", type="TYPE", description="d", embedding=emb.embed_query("alpha")
                ),
                Entity(
                    name="beta", type="TYPE", description="d", embedding=emb.embed_query("beta")
                ),
            ],
            relations=[],
            embedding_dim=8,
        )

        retriever = GraphRetriever(store=store, embedding=emb)
        retriever.retrieve("alpha", top_k=5)
        # The key F-03 invariant: matching dims → matrix built, not degraded.
        assert retriever._degraded is False
        assert retriever._matrix is not None


class TestUpdateEmbeddingsMigration:
    """F-03: GraphStore.update_embeddings re-embeds BLOBs + updates graph_meta."""

    def test_update_embeddings_replaces_blobs(self, store):
        """Persist 512d, update to 1024d, verify BLOBs are 1024d."""
        store.upsert(
            source="s1",
            entities=[_make_entity("alpha", 512), _make_entity("beta", 512)],
            relations=[],
            embedding_dim=512,
        )

        new_vecs = {
            make_entity_id("alpha", "TYPE"): np.ones(1024, dtype=np.float32).tolist(),
            make_entity_id("beta", "TYPE"): np.ones(1024, dtype=np.float32).tolist(),
        }
        updated = store.update_embeddings(new_vecs, embedding_model="bge-m3", embedding_dim=1024)
        assert updated == 2

        # Verify BLOBs are now 1024d (1024 * 4 bytes).
        rows = store.all_entity_names()
        for eid, _name in rows:
            with store._lock:  # noqa: SLF001
                cur = store._conn.execute("SELECT embedding FROM entities WHERE id = ?", (eid,))
                blob = cur.fetchone()["embedding"]
            assert len(blob) == 1024 * 4, f"entity {eid} BLOB still {len(blob) // 4}d"

        assert store.get_meta("embedding_dim") == "1024"
        assert store.get_meta("embedding_model") == "bge-m3"

    def test_no_stale_blobs_after_migration(self, store):
        """F-03 REQ-RBM-006: after migration, zero 512d BLOBs remain."""
        store.upsert(
            source="s1",
            entities=[_make_entity("a", 512), _make_entity("b", 512), _make_entity("c", 512)],
            relations=[],
            embedding_dim=512,
        )
        entities = store.all_entity_names()
        new_vecs = {eid: np.ones(1024, dtype=np.float32).tolist() for eid, _ in entities}
        store.update_embeddings(new_vecs, embedding_dim=1024)

        # Count stale (non-1024d) BLOBs.
        stale = 0
        for eid, _ in entities:
            with store._lock:  # noqa: SLF001
                cur = store._conn.execute("SELECT embedding FROM entities WHERE id = ?", (eid,))
                blob = cur.fetchone()["embedding"]
            if blob and len(blob) // 4 != 1024:
                stale += 1
        assert stale == 0, f"{stale} entities still have stale-dim BLOBs"

    def test_update_embeddings_empty_dict_noop(self, store):
        """Empty embeddings dict is a safe no-op."""
        store.upsert(
            source="s1",
            entities=[_make_entity("a", 512)],
            relations=[],
            embedding_dim=512,
        )
        result = store.update_embeddings({})
        assert result == 0

    def test_all_entity_names_returns_pairs(self, store):
        """all_entity_names returns (id, name) for migration batching."""
        store.upsert(
            source="s1",
            entities=[_make_entity("alpha", 512), _make_entity("beta", 512)],
            relations=[],
            embedding_dim=512,
        )
        pairs = store.all_entity_names()
        assert len(pairs) == 2
        ids = [p[0] for p in pairs]
        assert make_entity_id("alpha", "TYPE") in ids
        assert make_entity_id("beta", "TYPE") in ids


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
