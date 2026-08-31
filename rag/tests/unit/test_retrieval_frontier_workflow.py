from __future__ import annotations

from langchain_core.documents import Document


def _doc(text, **metadata):
    return Document(page_content=text, metadata=metadata)


def test_corrective_unavailable_scores_are_weak_not_zero_or_empty():
    from core.retrieval.corrective import EvidenceState, evaluate_evidence
    from core.retrieval.planner import RetrievalPlanner

    plan = RetrievalPlanner().plan("解释事务隔离")
    decision = evaluate_evidence([_doc("evidence", source="a.md")], plan, retry_index=0)

    assert decision.state is EvidenceState.WEAK
    assert decision.degraded is True
    assert decision.retry_action is not None
    assert decision.should_generate is False
    assert decision.max_relevance is None


def test_corrective_empty_stops_at_retry_bound():
    from core.retrieval.corrective import EvidenceState, evaluate_evidence
    from core.retrieval.planner import RetrievalPlanner

    plan = RetrievalPlanner().plan("RFC-9110")
    first = evaluate_evidence([], plan, retry_index=0)
    terminal = evaluate_evidence([], plan, retry_index=plan.retry_budget)

    assert first.state is EvidenceState.EMPTY
    assert first.retry_action == "increase_sparse_budget"
    assert terminal.state is EvidenceState.EMPTY
    assert terminal.retry_action is None
    assert terminal.should_generate is False


def test_corrective_conflict_requires_structured_same_family_metadata():
    from core.retrieval.corrective import EvidenceState, evaluate_evidence
    from core.retrieval.planner import RetrievalPlanner

    plan = RetrievalPlanner().plan("当前生效版本")
    documents = [
        _doc(
            "revision A",
            source="a.md",
            document_family="manual",
            status="active",
            revision="A",
            authority=5,
            rerank_probability=0.9,
        ),
        _doc(
            "revision B",
            source="b.md",
            document_family="manual",
            status="active",
            revision="B",
            authority=5,
            rerank_probability=0.9,
        ),
    ]

    decision = evaluate_evidence(documents, plan, retry_index=plan.retry_budget)

    assert decision.state is EvidenceState.CONFLICT
    assert decision.should_generate is False


def test_different_sources_alone_do_not_create_conflict():
    from core.retrieval.corrective import EvidenceState, evaluate_evidence
    from core.retrieval.planner import RetrievalPlanner

    plan = RetrievalPlanner().plan("普通语义问题")
    documents = [
        _doc("same fact", source="a.md", rerank_probability=0.8),
        _doc("same fact", source="b.md", rerank_probability=0.7),
    ]

    decision = evaluate_evidence(documents, plan, retry_index=0)

    assert decision.state is EvidenceState.ACCEPT


def test_authority_ranking_prefers_active_revision_without_penalizing_missing():
    from core.retrieval.authority import rank_by_authority

    documents = [
        _doc("obsolete", status="obsolete", authority=5, revision="9", score=0.99),
        _doc("active", status="active", authority=5, revision="10", score=0.60),
        _doc("missing metadata", score=0.70),
    ]

    ranked = rank_by_authority(documents)

    assert [doc.page_content for doc in ranked] == ["active", "missing metadata", "obsolete"]


def test_authority_ranking_preserves_cross_encoder_order_when_metadata_is_equal():
    from core.retrieval.authority import rank_by_authority

    documents = [
        _doc("rrf-first", score=0.99, rerank_score=-1.0),
        _doc("reranker-first", score=0.01, rerank_score=4.0),
    ]

    ranked = rank_by_authority(documents)

    assert [doc.page_content for doc in ranked] == ["reranker-first", "rrf-first"]


def test_workflow_singleton_reset_closes_previous_instance(monkeypatch):
    import core.retrieval.workflow as workflow_module

    class Workflow:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    previous = Workflow()
    monkeypatch.setattr(workflow_module, "_workflow", previous)

    workflow_module.reset_retrieval_workflow()

    assert previous.closed is True
    assert workflow_module._workflow is None


def test_promoted_workflow_defaults_on_but_explicit_off_restores_legacy(monkeypatch):
    from core.retrieval.workflow import retrieval_workflow_enabled

    monkeypatch.delenv("RETRIEVAL_WORKFLOW_ENABLED", raising=False)
    assert retrieval_workflow_enabled() is True

    monkeypatch.setenv("RETRIEVAL_WORKFLOW_ENABLED", "false")
    assert retrieval_workflow_enabled() is False


def test_all_frontier_flags_off_keep_optional_channels_out_of_compatibility_plan(monkeypatch):
    from core.retrieval.planner import RetrievalPlanner
    from core.retrieval.workflow import RetrievalWorkflow

    for name in (
        "COLBERT_RERANK_ENABLED",
        "RAPTOR_ENABLED",
        "GRAPH_PPR_ENABLED",
        "COLPALI_ENABLED",
    ):
        monkeypatch.setenv(name, "false")

    class Retriever:
        def __init__(self):
            self.calls = 0

        def retrieve(self, query, top_k=None, filter_expr=None, **kwargs):
            self.calls += 1
            return [_doc("compatibility", source="a.md", rerank_probability=0.9)]

    retriever = Retriever()
    result = RetrievalWorkflow(retriever=retriever).retrieve(
        "summarize this multi-hop diagram",
        final_k=1,
        channel_health={"raptor": True, "ppr": True, "visual": True},
    )
    plan = RetrievalPlanner().plan(
        "summarize this multi-hop diagram",
        final_k=1,
        channel_health={"raptor": True, "ppr": True, "visual": True},
    )

    assert retriever.calls == 1
    assert [doc.page_content for doc in result.documents] == ["compatibility"]
    assert plan.use_colbert is False
    assert plan.use_raptor is False
    assert plan.use_ppr is False
    assert plan.use_visual is False


def test_workflow_retry_changes_identity_and_redacts_filter():
    from core.retrieval.planner import RetrievalPlanner
    from core.retrieval.workflow import RetrievalWorkflow

    class Retriever:
        def __init__(self):
            self.calls = []

        def retrieve(self, query, top_k=None, filter_expr=None, plan=None, retry_identity=None):
            self.calls.append((plan.fingerprint, retry_identity, plan.candidate_k))
            if len(self.calls) == 1:
                return [_doc("weak", source="a.md")]
            return [_doc("good", source="a.md", rerank_probability=0.9)]

    retriever = Retriever()
    workflow = RetrievalWorkflow(retriever=retriever, planner=RetrievalPlanner())

    result = workflow.retrieve("RFC-9110", filter_expr='source == "a.md"')

    assert len(retriever.calls) == 2
    assert retriever.calls[0][1] != retriever.calls[1][1]
    assert retriever.calls[1][2] > retriever.calls[0][2]
    assert result.state.value == "accept"
    assert result.should_generate is True
    assert result.retry_action == "increase_sparse_budget"
    assert 'source == "a.md"' not in repr(result.diagnostics)
    assert result.diagnostics["filter_kind"] == "source_set"


def test_workflow_filter_invalid_is_terminal_without_calling_retriever():
    from core.retrieval.workflow import RetrievalWorkflow

    class Retriever:
        def retrieve(self, *args, **kwargs):
            raise AssertionError("invalid filter must not reach a channel")

    result = RetrievalWorkflow(retriever=Retriever()).retrieve("q", filter_expr="source ==")

    assert result.documents == []
    assert result.state.value == "empty"
    assert result.degraded is True
    assert result.should_generate is False


def test_retrieve_skill_is_unique_diagnostics_owner(monkeypatch):
    from types import SimpleNamespace

    from langchain_core.messages import HumanMessage

    from agent.skills.base import SkillContext
    from agent.skills.retrieve.skill import RetrieveSkill

    monkeypatch.setenv("RETRIEVAL_WORKFLOW_ENABLED", "true")
    diagnostics = {
        "state": "accept",
        "should_generate": True,
        "filter_kind": "none",
        "degraded": False,
    }
    skill = RetrieveSkill()
    skill._workflow = SimpleNamespace(
        retrieve=lambda *args, **kwargs: SimpleNamespace(
            documents=[_doc("evidence", source="a.md", rerank_probability=0.9)],
            diagnostics=diagnostics,
        )
    )
    context = SkillContext(messages=[HumanMessage(content="question")], shared_state={})

    result = skill.execute(context)

    assert result.state_updates["shared_state"]["retrieval_diagnostics"] == diagnostics
    assert context.shared_state["retrieval_diagnostics"] == diagnostics


def test_generate_terminal_weak_does_not_call_llm():
    from langchain_core.messages import HumanMessage

    from agent.skills.base import SkillContext
    from agent.skills.generate.skill import GenerateSkill

    context = SkillContext(
        messages=[HumanMessage(content="question")],
        shared_state={
            "retrieval_diagnostics": {
                "state": "weak",
                "should_generate": False,
                "uncovered_facets": ["B"],
            }
        },
    )
    skill = GenerateSkill()

    result = skill.execute(context)

    assert result.metadata["refused"] is True
    assert result.metadata["retrieval_state"] == "weak"
    assert "缺少：B" in result.messages[0].content


def test_fast_and_mcp_consume_same_workflow_terminal(monkeypatch):
    from types import SimpleNamespace

    import core.retrieval.workflow as workflow_module
    from agent.mcp.retrieval_server import MCPRetrievalServer
    from core.fast_mode import fast_generate

    monkeypatch.setenv("RETRIEVAL_WORKFLOW_ENABLED", "true")
    diagnostics = {
        "state": "conflict",
        "should_generate": False,
        "filter_kind": "none",
        "degraded": False,
    }
    workflow_result = SimpleNamespace(
        documents=[_doc("revision A", source="a.md")],
        diagnostics=diagnostics,
        should_generate=False,
        state=SimpleNamespace(value="conflict"),
    )
    fake_workflow = SimpleNamespace(retrieve=lambda *args, **kwargs: workflow_result)
    monkeypatch.setattr(workflow_module, "_workflow", fake_workflow)

    fast = fast_generate("current revision", top_k=2)
    mcp = MCPRetrievalServer()._hybrid_retrieve("current revision", top_k=2)

    assert fast.retrieval_diagnostics == diagnostics
    assert fast.generation_time_ms == 0
    assert mcp["diagnostics"] == diagnostics
    assert [item["content"] for item in mcp["documents"]] == ["revision A"]


def test_workflow_does_not_retry_when_all_evidence_channels_are_disabled(monkeypatch):
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
    calls = 0
    original = retriever.retrieve

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(retriever, "retrieve", counted)
    monkeypatch.setattr(
        "core.retrieval.query_transform.multi_query_expand",
        lambda _query: (_ for _ in ()).throw(AssertionError("retry transform executed")),
    )
    try:
        result = RetrievalWorkflow(retriever=retriever).retrieve("plain question")
    finally:
        retriever.close()

    assert calls == 1
    assert result.documents == []
    assert result.retry_action is None
    assert result.diagnostics["primary_channel_status"] == {
        "dense": "disabled",
        "sparse": "disabled",
        "graph": "disabled",
    }
