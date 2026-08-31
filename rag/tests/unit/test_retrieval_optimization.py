"""Tests for the optional reranking stage and async harness bridge."""

from __future__ import annotations

import asyncio

import pytest
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, ToolMessage


def test_reranker_preserves_retrieval_score_and_updates_final_score():
    from core.retrieval.reranker import Reranker

    class FakeCrossEncoder:
        def predict(self, pairs, batch_size, show_progress_bar=False):
            assert batch_size > 0
            assert show_progress_bar is False
            return [0.2, 0.9]

    documents = [
        Document(page_content="first", metadata={"score": 0.8}),
        Document(page_content="second", metadata={"score": 0.3}),
    ]
    reranker = Reranker()
    reranker._model = FakeCrossEncoder()

    results = reranker.rerank("query", documents, top_k=1)

    assert results[0].page_content == "second"
    assert results[0].metadata["retrieval_score"] == 0.3
    assert results[0].metadata["rerank_score"] == 0.9
    assert results[0].metadata["rerank_applied"] is True
    # The reranker must NOT overwrite the upstream retrieval score with its raw
    # logit — that would corrupt MMR's score-blending downstream. The original
    # RRF/retrieval score is preserved under "score".
    assert results[0].metadata["score"] == 0.3


def test_reranker_load_failure_is_not_retried(monkeypatch):
    import builtins

    from core.retrieval.reranker import Reranker

    attempts = 0
    original_import = builtins.__import__

    def failing_import(name, *args, **kwargs):
        nonlocal attempts
        if name == "sentence_transformers":
            attempts += 1
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing_import)
    reranker = Reranker()
    documents = [Document(page_content="first", metadata={"score": 0.1})]

    first = reranker.rerank("query", documents)
    second = reranker.rerank("query", documents)

    assert attempts == 1
    assert first[0].metadata["rerank_applied"] is False
    assert second[0].metadata["rerank_applied"] is False
    assert reranker.status()["load_attempted"] is True
    assert reranker.status()["loaded"] is False


def test_reranker_cache_scan_is_reused_and_uses_configured_model(monkeypatch):
    from core.retrieval import reranker as reranker_module

    scans = 0

    class FakeRepo:
        repo_id = "custom/reranker"

    class FakeCache:
        repos = [FakeRepo()]

    def fake_scan_cache_dir():
        nonlocal scans
        scans += 1
        return FakeCache()

    reranker_module._cache_status.clear()
    monkeypatch.setattr("huggingface_hub.scan_cache_dir", fake_scan_cache_dir)
    reranker = reranker_module.Reranker(
        reranker_module.RerankerConfig(model_name="custom/reranker")
    )

    assert reranker.status()["cached"] is True
    assert reranker.status()["cached"] is True
    assert scans == 1


def test_hybrid_reranker_is_controlled_by_feature_flag(monkeypatch):
    from core.retrieval import reranker as reranker_module
    from core.retrieval.hybrid_retriever import HybridRetriever, HybridRetrieverConfig

    documents = [
        Document(page_content="first"),
        Document(page_content="second"),
    ]

    disabled = HybridRetriever(config=HybridRetrieverConfig(enable_reranker=False))
    assert disabled._rerank("query", documents, top_k=1)[0].page_content == "first"

    class FakeReranker:
        def rerank(self, query, candidates, top_k):
            return list(reversed(candidates))[:top_k]

    monkeypatch.setattr(reranker_module, "get_reranker", lambda: FakeReranker())
    enabled = HybridRetriever(config=HybridRetrieverConfig(enable_reranker=True))
    assert enabled._rerank("query", documents, top_k=1)[0].page_content == "second"


def test_rrf_score_is_exposed_in_document_metadata():
    from core.retrieval.hybrid_retriever import (
        HybridRetriever,
        HybridRetrieverConfig,
        RetrievalResult,
    )

    document = Document(page_content="shared evidence", metadata={"source": "manual"})
    retriever = HybridRetriever(
        config=HybridRetrieverConfig(
            dense_weight=0.5,
            sparse_weight=0.5,
            rrf_k=60,
        )
    )

    results = retriever._rrf_fusion(
        [RetrievalResult(document=document, score=0.8, source="dense", rank=1)],
        [RetrievalResult(document=document, score=2.0, source="sparse", rank=1)],
    )

    expected = 1.0 / 61
    assert results[0].document.metadata["retrieval_score"] == pytest.approx(expected)
    assert results[0].document.metadata["score"] == pytest.approx(expected)
    assert results[0].document.metadata["retrieval_source"] == "hybrid"


def test_retrieval_api_exposes_reranker_scores():
    from api.routers.retrieval import _build_response

    response = _build_response(
        "query",
        [
            Document(
                page_content="evidence",
                metadata={
                    "source": "manual.md",
                    "score": 0.9,
                    "retrieval_score": 0.1,
                    "rerank_score": 0.9,
                    "rerank_applied": True,
                },
            )
        ],
        12.0,
    )

    result = response.results[0]
    assert result.retrieval_score == 0.1
    assert result.rerank_score == 0.9
    assert result.rerank_applied is True


def test_harness_uses_native_async_graph_methods():
    from agent.harness.orchestrator import AgentHarness, HarnessConfig

    harness = AgentHarness(config=HarnessConfig(use_memory=False))

    class FakeAsyncGraph:
        async def ainvoke(self, inputs, config):
            return {"question": inputs["messages"][0].content}

        async def astream(self, inputs, config, stream_mode):
            yield {"agent": {}}
            yield {"generate": {}}

    harness._graph = FakeAsyncGraph()

    async def exercise():
        result = await harness.ainvoke("async question")
        assert result == {"question": "async question"}

        events = [event async for event in harness.astream("stream question")]
        assert events == [{"agent": {}}, {"generate": {}}]

    asyncio.run(exercise())


def test_generate_skill_publishes_custom_token_events():
    from langgraph.constants import END, START
    from langgraph.graph import StateGraph

    from agent.context.state import AgentState
    from agent.skills.base import SkillContext
    from agent.skills.generate.skill import GenerateSkill

    class FakeChain:
        async def astream(self, values):
            for token in ["first ", "second"]:
                yield token

    skill = GenerateSkill()
    skill._chain = FakeChain()

    async def generate_node(state):
        result = await skill.aexecute(SkillContext.from_agent_state(state))
        return result.to_state_update()

    workflow = StateGraph(AgentState)
    workflow.add_node("generate", generate_node)
    workflow.add_edge(START, "generate")
    workflow.add_edge("generate", END)
    graph = workflow.compile()

    async def exercise():
        events = [
            event
            async for event in graph.astream(
                {
                    "messages": [
                        HumanMessage(content="question"),
                        ToolMessage(
                            # Provide scores so _should_refuse (Stage C: no-scores
                            # now refuses) lets generation proceed.
                            content=[{"text": "context", "score": 0.9}],
                            tool_call_id="call-1",
                        ),
                    ],
                    "rewrite_count": 0,
                    "max_rewrites": 0,
                },
                stream_mode=["custom", "updates"],
            )
        ]
        custom = [event[1] for event in events if event[0] == "custom"]
        assert [event["content"] for event in custom] == ["first ", "second"]

    asyncio.run(exercise())
