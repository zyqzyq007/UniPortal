from __future__ import annotations

import asyncio

from langchain_core.documents import Document

from core.retrieval.hybrid_retriever import (
    HybridRetriever,
    HybridRetrieverConfig,
    RetrievalBudgets,
    RetrievalResult,
)


def _result(source: str = "sparse") -> RetrievalResult:
    return RetrievalResult(
        document=Document(
            page_content=f"{source} evidence",
            metadata={"source": source, "retrieval_source": source, "score": 0.8},
        ),
        score=0.8,
        source=source,
        rank=1,
    )


def _config(**overrides) -> HybridRetrieverConfig:
    values = {
        "enable_parallel": False,
        "enable_reranker": False,
        "enable_native_sparse": False,
        "enable_graph": False,
    }
    values.update(overrides)
    return HybridRetrieverConfig(**values)


def test_active_channel_policy_defaults_and_identity_are_explicit(monkeypatch):
    for key in (
        "RETRIEVAL_DENSE_ENABLED",
        "RETRIEVAL_SPARSE_ENABLED",
        "RETRIEVAL_MMR_ENABLED",
        "RETRIEVAL_TIME_DECAY_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)

    default = _config()
    assert hasattr(default, "active_policy")
    policy = default.active_policy()
    assert policy.dense is True
    assert policy.sparse is True
    assert policy.mmr is True
    assert policy.time_decay is True

    dense_off = _config(enable_dense=False).active_policy()
    assert dense_off.dense is False
    assert dense_off.fingerprint != policy.fingerprint


def test_sync_sequential_disabled_dense_is_never_called(monkeypatch):
    retriever = HybridRetriever(
        config=_config(
            enable_dense=False,
            enable_sparse=True,
            enable_mmr=False,
            enable_time_decay=False,
        )
    )
    calls = {"dense": 0, "sparse": 0, "representation": 0}

    def dense(*_args, **_kwargs):
        calls["dense"] += 1
        raise AssertionError("disabled dense leg executed")

    def sparse(*_args, **_kwargs):
        calls["sparse"] += 1
        return [_result()]

    def representation(*_args, **_kwargs):
        calls["representation"] += 1
        raise AssertionError("BM25-only baseline encoded a dense query")

    monkeypatch.setattr(retriever, "_dense_retrieve", dense)
    monkeypatch.setattr(retriever, "_sparse_retrieve", sparse)
    monkeypatch.setattr(retriever, "_prepare_query_representation", representation)
    try:
        documents = retriever.retrieve("exact lexical query", top_k=1)
    finally:
        retriever.close()

    assert [document.page_content for document in documents] == ["sparse evidence"]
    assert calls == {"dense": 0, "sparse": 1, "representation": 0}


def test_sync_exception_fallback_does_not_resurrect_disabled_dense(monkeypatch):
    retriever = HybridRetriever(
        config=_config(
            enable_dense=False,
            enable_sparse=True,
            enable_mmr=False,
            enable_time_decay=False,
        )
    )
    calls = {"dense": 0, "sparse": 0}

    def dense(*_args, **_kwargs):
        calls["dense"] += 1
        raise AssertionError("disabled dense fallback executed")

    def sparse(*_args, **_kwargs):
        calls["sparse"] += 1
        return [_result()]

    monkeypatch.setattr(retriever, "_dense_retrieve", dense)
    monkeypatch.setattr(retriever, "_sparse_retrieve", sparse)
    monkeypatch.setattr(
        retriever, "_rrf_fusion", lambda *_args: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    try:
        documents = retriever.retrieve("fallback query", top_k=1)
    finally:
        retriever.close()

    assert calls["dense"] == 0
    assert calls["sparse"] >= 1
    assert isinstance(documents, list)


def test_parallel_and_async_paths_return_immutable_execution_info(monkeypatch):
    retriever = HybridRetriever(
        config=_config(
            enable_parallel=True,
            enable_dense=False,
            enable_sparse=True,
            enable_mmr=False,
            enable_time_decay=False,
        )
    )
    calls = {"dense": 0, "sparse": 0}

    def dense(*_args, **_kwargs):
        calls["dense"] += 1
        raise AssertionError("disabled dense leg executed")

    def sparse(*_args, **_kwargs):
        calls["sparse"] += 1
        return [_result()]

    monkeypatch.setattr(retriever, "_dense_retrieve", dense)
    monkeypatch.setattr(retriever, "_sparse_retrieve", sparse)
    try:
        sync_outcome = retriever.retrieve_with_info("parallel query", top_k=1)
        async_outcome = asyncio.run(retriever.aretrieve_with_info("async query", top_k=1))
    finally:
        retriever.close()

    assert sync_outcome.execution.channel_status["dense"] == "disabled"
    assert sync_outcome.execution.channel_status["sparse"] == "contributed"
    assert async_outcome.execution.channel_status["dense"] == "disabled"
    assert async_outcome.execution.channel_status["sparse"] == "contributed"
    assert calls["dense"] == 0
    assert calls["sparse"] == 2


def test_both_primary_channels_disabled_is_safe_and_not_scored_zero(monkeypatch):
    retriever = HybridRetriever(
        config=_config(
            enable_dense=False,
            enable_sparse=False,
            enable_mmr=False,
            enable_time_decay=False,
        )
    )
    monkeypatch.setattr(
        retriever,
        "_dense_retrieve",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("dense called")),
    )
    monkeypatch.setattr(
        retriever,
        "_sparse_retrieve",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("sparse called")),
    )
    try:
        outcome = retriever.retrieve_with_info("no primary channels", top_k=2)
    finally:
        retriever.close()

    assert outcome.documents == []
    assert outcome.execution.degraded is True
    assert outcome.execution.relevance_score is None
    assert outcome.execution.channel_status == {
        "dense": "disabled",
        "sparse": "disabled",
        "graph": "disabled",
    }


def test_cache_key_changes_with_active_policy(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_CACHE_NAMESPACE", "channel-policy-test")
    budgets = RetrievalBudgets(10, 5, 5, 5)
    enabled = HybridRetriever(config=_config(enable_dense=True, enable_sparse=True))
    dense_off = HybridRetriever(config=_config(enable_dense=False, enable_sparse=True))
    try:
        left = enabled._cache_key_for("q", None, budgets)
        right = dense_off._cache_key_for("q", None, budgets)
    finally:
        enabled.close()
        dense_off.close()
    assert left != right


def test_planner_channel_health_survives_retry():
    from core.retrieval.planner import apply_channel_health, safe_default_plan

    health = {
        "dense": False,
        "sparse": True,
        "graph": False,
        "mmr": False,
        "time_decay": False,
    }
    plan = apply_channel_health(safe_default_plan(final_k=4), health)
    retry = apply_channel_health(plan.for_retry("increase_sparse_budget"), health)

    assert plan.dense_weight == 0.0
    assert retry.dense_weight == 0.0
    assert retry.sparse_weight > 0.0
    assert retry.use_mmr is False
    assert retry.use_time_decay is False


def test_rrf_preserves_duplicate_text_with_stable_chunk_ids_and_tie_order():
    retriever = HybridRetriever(
        config=_config(
            enable_dense=True,
            enable_sparse=True,
            dense_weight=0.5,
            sparse_weight=0.5,
            enable_mmr=False,
            enable_time_decay=False,
        )
    )
    dense = RetrievalResult(
        document=Document(page_content="duplicate body", metadata={"chunk_id": "b"}),
        score=0.5,
        source="dense",
        rank=1,
    )
    sparse = RetrievalResult(
        document=Document(page_content="duplicate body", metadata={"chunk_id": "a"}),
        score=0.5,
        source="sparse",
        rank=1,
    )
    try:
        fused = retriever._rrf_fusion([dense], [sparse])
    finally:
        retriever.close()

    assert [result.document.metadata["chunk_id"] for result in fused] == ["a", "b"]
