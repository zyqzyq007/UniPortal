from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from core.retrieval.hybrid_retriever import HybridRetrieverConfig
from scripts import run_benchmark


def test_latency_summary_uses_first_query_name_and_keeps_compatibility_alias():
    summary = run_benchmark._latency_summary([12.0, 3.0, 5.0, 4.0])

    assert summary["first_query_ms"] == 12.0
    assert summary["cold_ms"] == 12.0
    assert summary["warm_p50_ms"] == 4.0
    assert summary["warm_p95_ms"] == 5.0


def test_active_index_stages_do_not_charge_dense_index_to_bm25(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_DENSE_ENABLED", "false")
    monkeypatch.setenv("RETRIEVAL_SPARSE_ENABLED", "true")
    monkeypatch.setenv("MILVUS_SPARSE_INDEX", "false")
    monkeypatch.setenv("RETRIEVAL_MMR_ENABLED", "false")
    bm25_policy = HybridRetrieverConfig(
        enable_dense=False,
        enable_sparse=True,
        enable_native_sparse=False,
        enable_mmr=False,
    ).active_policy()
    assert run_benchmark._active_index_stages(bm25_policy) == ("bm25",)

    dense_policy = HybridRetrieverConfig(
        enable_dense=True,
        enable_sparse=False,
        enable_native_sparse=False,
        enable_mmr=False,
    ).active_policy()
    assert run_benchmark._active_index_stages(dense_policy) == ("milvus_dense",)


def test_configured_store_bytes_counts_only_existing_isolated_paths(tmp_path, monkeypatch):
    milvus = tmp_path / "milvus.db"
    registry = tmp_path / "registry.db"
    milvus.write_bytes(b"1234")
    registry.write_bytes(b"12")
    monkeypatch.setenv("MILVUS_DB_URI", str(milvus))
    monkeypatch.setenv("EMBEDDING_REGISTRY_DB", str(registry))
    monkeypatch.setenv("RAPTOR_DB_PATH", str(tmp_path / "missing.db"))
    monkeypatch.setenv("PDF_ASSET_DIR", str(tmp_path / "assets"))

    assert run_benchmark._configured_store_bytes() == 6


def test_effective_retrieval_config_reports_parsed_policy(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_WORKFLOW_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_DENSE_ENABLED", "false")
    monkeypatch.setenv("RETRIEVAL_SPARSE_ENABLED", "true")
    monkeypatch.setenv("MILVUS_SPARSE_INDEX", "false")
    monkeypatch.setenv("RERANKER_ENABLED", "false")
    monkeypatch.setenv("RETRIEVAL_MMR_ENABLED", "false")
    config = HybridRetrieverConfig(
        enable_dense=False,
        enable_sparse=True,
        enable_native_sparse=False,
        enable_reranker=False,
        enable_mmr=False,
    )

    effective = run_benchmark._effective_retrieval_config(config)

    assert effective["RETRIEVAL_WORKFLOW_ENABLED"] == "true"
    assert effective["RETRIEVAL_DENSE_ENABLED"] == "false"
    assert effective["RETRIEVAL_SPARSE_ENABLED"] == "true"
    assert effective["MILVUS_SPARSE_INDEX"] == "false"
    assert effective["RERANKER_ENABLED"] == "false"
    assert effective["RETRIEVAL_MMR_ENABLED"] == "false"
    assert not any("KEY" in key or "TOKEN" in key for key in effective)


def test_path_size_handles_directory_tree(tmp_path):
    root = tmp_path / "store"
    (root / "nested").mkdir(parents=True)
    (root / "a").write_bytes(b"123")
    (root / "nested" / "b").write_bytes(b"45")

    assert run_benchmark._path_size(Path(root)) == 5


def test_active_store_snapshot_validates_bm25_without_dense_store(monkeypatch):
    corpus = {
        "doc-b": {"text": "  beta   text "},
        "doc-a": {"text": "alpha text"},
    }
    expected = run_benchmark._corpus_snapshot(corpus)
    monkeypatch.setattr(run_benchmark, "_bm25_store_snapshot", lambda: expected)
    policy = SimpleNamespace(dense=False, sparse=True, sparse_backend="bm25")

    snapshot = run_benchmark._active_store_snapshot(policy, corpus, manager=None)

    assert snapshot["expected"] == expected
    assert snapshot["stores"] == {"bm25": expected}
    assert "milvus" not in snapshot["stores"]


def test_active_store_snapshot_rejects_partial_index(monkeypatch):
    corpus = {"doc-a": {"text": "alpha"}, "doc-b": {"text": "beta"}}
    monkeypatch.setattr(
        run_benchmark,
        "_bm25_store_snapshot",
        lambda: run_benchmark._snapshot_rows([("doc-a", "alpha")]),
    )
    policy = SimpleNamespace(dense=False, sparse=True, sparse_backend="bm25")

    try:
        run_benchmark._active_store_snapshot(policy, corpus, manager=None)
    except RuntimeError as exc:
        assert "BM25 corpus snapshot mismatch" in str(exc)
    else:
        raise AssertionError("partial BM25 index must fail benchmark verification")


def test_resource_probe_status_distinguishes_unavailable_from_zero():
    status = run_benchmark._resource_probe_status(
        peak_rss_mb=512.0,
        gpu_peak_mb=None,
        gpu_reserved_peak_mb=0.0,
        query_forwards=None,
    )

    assert status["peak_rss_mb"] == {"available": True, "reason": None}
    assert status["gpu_peak_mb"] == {
        "available": False,
        "reason": "cuda_unavailable_or_probe_failed",
    }
    assert status["gpu_reserved_peak_mb"] == {"available": True, "reason": None}
    assert status["query_embedding_forwards"] == {
        "available": False,
        "reason": "embedding_counter_unavailable",
    }
