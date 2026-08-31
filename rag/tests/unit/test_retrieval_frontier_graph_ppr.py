from __future__ import annotations

import json
from pathlib import Path


def _fixture():
    path = Path(__file__).parents[1] / "fixtures" / "retrieval_frontier_graph_ppr.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_personalized_pagerank_matches_golden_and_is_bounded():
    from core.retrieval.graph_ppr import personalized_pagerank

    fixture = _fixture()
    result = personalized_pagerank(
        fixture["adjacency"],
        set(fixture["seeds"]),
        max_iterations=100,
        tolerance=1e-6,
        max_nodes=10,
    )

    order = [node for node, _score in sorted(result.scores.items(), key=lambda item: -item[1])]
    assert order[:3] == fixture["expected_rank_prefix"]
    assert result.iterations <= 100
    assert result.converged is True
    assert abs(sum(result.scores.values()) - 1.0) < 1e-6
    assert result.scores.get("distractor", 0.0) == 0.0


def test_personalized_pagerank_nonconvergence_returns_finite_partial_result():
    from core.retrieval.graph_ppr import personalized_pagerank

    result = personalized_pagerank(
        _fixture()["adjacency"],
        {"alpha"},
        max_iterations=1,
        tolerance=0.0,
        max_nodes=3,
    )

    assert result.converged is False
    assert result.iterations == 1
    assert result.degraded is True
    assert result.scores
    assert all(score >= 0 for score in result.scores.values())


def test_bounded_shortest_paths_matches_golden():
    from core.retrieval.graph_ppr import bounded_shortest_paths

    fixture = _fixture()
    paths = bounded_shortest_paths(
        fixture["adjacency"],
        {"alpha", "gamma"},
        max_depth=3,
        max_paths=4,
    )

    assert fixture["expected_path"] in paths
    assert all(len(path) <= 4 for path in paths)


def test_graph_ppr_retrieval_is_source_isolated_and_maps_to_raw_chunks(tmp_path):
    from core.retrieval.graph_retriever import GraphRetriever
    from documents.graph_store import Entity, GraphStore, Relation

    store = GraphStore(str(tmp_path / "graph.db"))
    alpha = Entity(
        "Alpha",
        "concept",
        embedding=[1.0, 0.0],
        source="a.md",
        chunk_text="alpha raw",
        parent_id="a1",
    )
    beta = Entity(
        "Beta",
        "concept",
        embedding=[0.8, 0.2],
        source="a.md",
        chunk_text="beta raw",
        parent_id="a2",
    )
    gamma = Entity(
        "Gamma",
        "concept",
        embedding=[0.6, 0.4],
        source="a.md",
        chunk_text="gamma raw",
        parent_id="a3",
    )
    store.upsert(
        [alpha, beta, gamma],
        [
            Relation(alpha.id, beta.id, "links", source="a.md"),
            Relation(beta.id, gamma.id, "links", source="a.md"),
        ],
        source="a.md",
        embedding_model="fake",
        embedding_dim=2,
    )
    other = Entity(
        "Gamma",
        "concept",
        embedding=[1.0, 0.0],
        source="b.md",
        chunk_text="cross tenant raw",
        parent_id="b1",
    )
    store.upsert(
        [other],
        [],
        source="b.md",
        embedding_model="fake",
        embedding_dim=2,
    )

    retriever = GraphRetriever(store=store, embedding=None)
    results = retriever.retrieve(
        "Alpha Gamma multi-hop",
        top_k=3,
        filter_expr='source == "a.md"',
        query_dense=[1.0, 0.0],
        use_ppr=True,
        facets=("Alpha", "Gamma"),
    )

    assert results
    assert {result.document.metadata["source"] for result in results} == {"a.md"}
    assert all(result.document.metadata["graph_mode"] == "ppr" for result in results)
    assert "cross tenant raw" not in {result.document.page_content for result in results}
    assert any(result.document.metadata.get("graph_path") for result in results)
    store.close()


def test_graph_ppr_sql_failure_degrades_to_empty(monkeypatch):
    from core.retrieval.graph_retriever import GraphRetriever

    class Store:
        def load_all(self):
            return []

        def meta(self, key, default=""):
            return default

        def source_graph(self, allowed_sources=None):
            raise RuntimeError("sqlite unavailable")

    retriever = GraphRetriever(store=Store(), embedding=None)
    retriever._loaded = True
    retriever._name_index = {"alpha": {"a"}}

    results = retriever.retrieve(
        "Alpha multi-hop",
        use_ppr=True,
        query_dense=[1.0, 0.0],
    )

    assert results == []
    assert retriever.status()["degraded"] is True
