from __future__ import annotations

import uuid
from types import SimpleNamespace

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage


def _document(text: str, source: str, score: float) -> Document:
    return Document(
        page_content=text,
        metadata={
            "source": source,
            "score": score,
            "rerank_probability": score,
        },
    )


def test_fast_thinking_mcp_share_filtered_pre_generation_evidence(monkeypatch):
    import core.retrieval.workflow as workflow_module
    from agent.mcp.retrieval_server import MCPRetrievalServer
    from agent.skills.base import SkillContext
    from agent.skills.retrieve.skill import RetrieveSkill, RetrieveSkillConfig
    from core.fast_mode import fast_generate
    from core.retrieval.workflow import RetrievalWorkflow

    filter_expr = 'source == "tenant-a.md"'

    class Retriever:
        def __init__(self):
            self.filters: list[str | None] = []

        def retrieve(self, query, top_k=None, filter_expr=None, **kwargs):
            self.filters.append(filter_expr)
            assert filter_expr == 'source == "tenant-a.md"'
            return [
                _document("first", "tenant-a.md", 0.9),
                _document("second", "tenant-a.md", 0.8),
            ][:top_k]

    retriever = Retriever()
    workflow = RetrievalWorkflow(retriever=retriever)
    monkeypatch.setattr(workflow_module, "_workflow", workflow)
    monkeypatch.setenv("RETRIEVAL_WORKFLOW_ENABLED", "true")
    monkeypatch.setattr("models.llm_models.get_llm", lambda: object())
    monkeypatch.setattr(
        "core.fast_mode._get_chain",
        lambda llm: SimpleNamespace(invoke=lambda payload: "answer"),
    )

    skill = RetrieveSkill(
        RetrieveSkillConfig(
            top_k=2,
            return_as_tool_message=False,
            min_rerank_score=0,
            min_rerank_prob=0,
        )
    )
    skill._workflow = workflow
    thinking = skill.execute(
        SkillContext(
            messages=[HumanMessage(content="question")],
            shared_state={"filter_expr": filter_expr},
        )
    )
    fast = fast_generate("question", top_k=2, filter_expr=filter_expr)
    mcp = MCPRetrievalServer()._hybrid_retrieve(
        "question",
        top_k=2,
        filter_expr=filter_expr,
    )

    thinking_sources = [
        item["source"] for item in thinking.state_updates["shared_state"]["retrieval_evidence"]
    ]
    assert thinking_sources == ["tenant-a.md", "tenant-a.md"]
    assert [item["source"] for item in fast.sources] == thinking_sources
    assert [item["source"] for item in mcp["documents"]] == thinking_sources
    assert retriever.filters == [filter_expr, filter_expr, filter_expr]


def test_invalid_filter_is_terminal_across_thinking_fast_and_mcp(monkeypatch):
    import core.retrieval.workflow as workflow_module
    from agent.mcp.retrieval_server import MCPRetrievalServer
    from agent.skills.base import SkillContext
    from agent.skills.retrieve.skill import RetrieveSkill, RetrieveSkillConfig
    from core.fast_mode import fast_generate
    from core.retrieval.workflow import RetrievalWorkflow

    class Retriever:
        def retrieve(self, *args, **kwargs):
            raise AssertionError("invalid filter must fail before retrieval")

    workflow = RetrievalWorkflow(retriever=Retriever())
    monkeypatch.setattr(workflow_module, "_workflow", workflow)
    monkeypatch.setenv("RETRIEVAL_WORKFLOW_ENABLED", "true")
    skill = RetrieveSkill(RetrieveSkillConfig(return_as_tool_message=False))
    skill._workflow = workflow

    thinking = skill.execute(
        SkillContext(
            messages=[HumanMessage(content="question")],
            shared_state={"filter_expr": "source =="},
        )
    )
    fast = fast_generate("question", filter_expr="source ==")
    mcp = MCPRetrievalServer()._hybrid_retrieve("question", filter_expr="source ==")

    diagnostics = thinking.state_updates["shared_state"]["retrieval_diagnostics"]
    assert diagnostics["state"] == "empty"
    assert diagnostics["should_generate"] is False
    assert fast.retrieval_count == 0
    assert fast.retrieval_diagnostics["filter_kind"] == "invalid"
    assert mcp["documents"] == []
    assert mcp["diagnostics"]["filter_kind"] == "invalid"


def test_documents_route_populates_dense_sparse_and_hybrid_with_cache_invalidation(
    client, monkeypatch
):
    import api.routers.documents as documents_router
    import core.retrieval.bm25_retriever as bm25_module
    import core.retrieval.hybrid_retriever as hybrid_module
    import documents.milvus_db as milvus_module
    from core.retrieval.bm25_retriever import BM25Retriever
    from core.retrieval.cache import get_retrieval_cache
    from core.retrieval.hybrid_retriever import HybridRetriever, HybridRetrieverConfig
    from documents.milvus_db import SearchResult

    class MemoryDenseManager:
        def __init__(self):
            self.documents = []

        def add_documents(self, documents):
            self.documents.extend(documents)
            return {"inserted": len(documents), "failed": 0, "total": len(documents)}

        def query(self, filter_expr, output_fields=None, limit=100):
            if not filter_expr:
                return []
            value = filter_expr.split('"')[1] if '"' in filter_expr else ""
            field = "file_hash" if "file_hash" in filter_expr else "source"
            return [
                {field: document.metadata.get(field, "")}
                for document in self.documents
                if document.metadata.get(field) == value
            ][:limit]

        def search(self, query, top_k=10, filter_expr=None):
            allowed_source = None
            if filter_expr and 'source == "' in filter_expr:
                allowed_source = filter_expr.split('"')[1]
            matches = [
                document
                for document in self.documents
                if query.lower() in document.page_content.lower()
                and (allowed_source is None or document.metadata.get("source") == allowed_source)
            ]
            return [
                SearchResult(
                    id=index + 1,
                    text=document.page_content,
                    score=0.95 - index * 0.01,
                    metadata={**document.metadata, "score": 0.95 - index * 0.01},
                )
                for index, document in enumerate(matches[:top_k])
            ]

        def close(self):
            return None

    token = f"ragbench{uuid.uuid4().hex[:10]}"
    filename = f"retrieval_{token}.md"
    manager = MemoryDenseManager()
    bm25 = BM25Retriever()
    config = HybridRetrieverConfig(
        enable_dense=True,
        enable_sparse=True,
        enable_native_sparse=False,
        enable_reranker=False,
        enable_mmr=False,
        enable_time_decay=False,
        enable_parallel=False,
    )
    retriever = HybridRetriever(dense_manager=manager, sparse_retriever=bm25, config=config)
    monkeypatch.setattr(documents_router, "GRAPH_RAG_ENABLED", False)
    monkeypatch.setenv("RAPTOR_ENABLED", "false")
    monkeypatch.setenv("CONTEXTUAL_INDEX_ENABLED", "false")
    monkeypatch.setattr(milvus_module, "get_milvus_manager", lambda: manager)
    monkeypatch.setattr(bm25_module, "_bm25_retriever", bm25)
    monkeypatch.setattr(hybrid_module, "get_hybrid_retriever", lambda: retriever)
    get_retrieval_cache().clear()
    try:
        before = client.post("/api/retrieval", json={"query": token, "top_k": 4})
        assert before.status_code == 200
        assert before.json()["results"] == []

        upload = client.post(
            "/api/documents/upload",
            files={
                "file": (
                    filename,
                    f"# Cache contract\n\n{token} is visible after indexing.".encode(),
                    "text/markdown",
                )
            },
        )
        assert upload.status_code == 200
        detail = client.get(f"/api/documents/{upload.json()['id']}")
        assert detail.status_code == 200
        assert detail.json()["status"] == "indexed"

        dense = client.post("/api/retrieval/dense", json={"query": token, "top_k": 4})
        sparse = client.post("/api/retrieval/sparse", json={"query": token, "top_k": 4})
        hybrid = client.post("/api/retrieval", json={"query": token, "top_k": 4})
        assert dense.status_code == sparse.status_code == hybrid.status_code == 200
        assert token in dense.json()["results"][0]["content"]
        assert token in sparse.json()["results"][0]["content"]
        assert token in hybrid.json()["results"][0]["content"]

        allowed = retriever.retrieve(token, top_k=4, filter_expr=f'source == "{filename}"')
        excluded = retriever.retrieve(token, top_k=4, filter_expr='source == "another-tenant.md"')
        assert allowed and all(doc.metadata["source"] == filename for doc in allowed)
        assert excluded == []
    finally:
        retriever.close()
        get_retrieval_cache().clear()


def test_both_primary_channels_disabled_is_terminal_across_all_surfaces(monkeypatch):
    import core.retrieval.workflow as workflow_module
    from agent.mcp.retrieval_server import MCPRetrievalServer
    from agent.skills.base import SkillContext
    from agent.skills.retrieve.skill import RetrieveSkill, RetrieveSkillConfig
    from core.fast_mode import fast_generate
    from core.retrieval.hybrid_retriever import HybridRetriever, HybridRetrieverConfig
    from core.retrieval.workflow import RetrievalWorkflow

    retriever = HybridRetriever(
        config=HybridRetrieverConfig(
            enable_dense=False,
            enable_sparse=False,
            enable_graph=False,
            enable_reranker=False,
            enable_mmr=False,
            enable_time_decay=False,
            enable_parallel=False,
        )
    )
    workflow = RetrievalWorkflow(retriever=retriever)
    monkeypatch.setattr(workflow_module, "_workflow", workflow)
    monkeypatch.setenv("RETRIEVAL_WORKFLOW_ENABLED", "true")
    skill = RetrieveSkill(RetrieveSkillConfig(return_as_tool_message=False))
    skill._workflow = workflow
    try:
        thinking = skill.execute(
            SkillContext(messages=[HumanMessage(content="question")], shared_state={})
        )
        fast = fast_generate("question")
        mcp = MCPRetrievalServer()._hybrid_retrieve("question")
    finally:
        retriever.close()

    diagnostics = thinking.state_updates["shared_state"]["retrieval_diagnostics"]
    assert diagnostics["should_generate"] is False
    assert diagnostics["primary_channel_status"]["dense"] == "disabled"
    assert diagnostics["primary_channel_status"]["sparse"] == "disabled"
    assert fast.retrieval_count == 0
    assert fast.retrieval_diagnostics["primary_channel_status"]["dense"] == "disabled"
    assert mcp["documents"] == []
    assert mcp["diagnostics"]["primary_channel_status"]["sparse"] == "disabled"
