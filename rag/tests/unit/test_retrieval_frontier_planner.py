from __future__ import annotations

import json
from pathlib import Path


def test_planner_matches_golden_contract():
    from core.retrieval.planner import RetrievalPlanner

    fixture = Path(__file__).parents[1] / "fixtures" / "retrieval_frontier_plans.json"
    cases = json.loads(fixture.read_text(encoding="utf-8"))
    planner = RetrievalPlanner()

    actual = {}
    for query in cases:
        plan = planner.plan(query)
        actual[query] = {
            "query_type": plan.query_type.value,
            "use_mmr": plan.use_mmr,
            "query_transform": plan.query_transform,
            "facets": list(plan.facets),
        }

    assert actual == cases


def test_exact_plan_prefers_sparse_and_keeps_diversity_off():
    from core.retrieval.planner import QueryType, RetrievalPlanner

    plan = RetrievalPlanner().plan("错误码 ERR-0x8007F001 的定义")

    assert plan.query_type is QueryType.EXACT
    assert plan.sparse_weight > plan.dense_weight
    assert plan.use_mmr is False
    assert plan.candidate_k > plan.final_k


def test_optional_routes_require_flag_and_health(monkeypatch):
    from core.retrieval.planner import RetrievalPlanner

    monkeypatch.setenv("RAPTOR_ENABLED", "true")
    monkeypatch.setenv("COLPALI_ENABLED", "true")
    planner = RetrievalPlanner()

    global_unhealthy = planner.plan("总结整份文档", channel_health={"raptor": False})
    global_healthy = planner.plan("总结整份文档", channel_health={"raptor": True})
    visual_unhealthy = planner.plan("图 3 的趋势", channel_health={"visual": False})
    visual_healthy = planner.plan("图 3 的趋势", channel_health={"visual": True})

    assert global_unhealthy.use_raptor is False
    assert global_healthy.use_raptor is True
    assert visual_unhealthy.use_visual is False
    assert visual_healthy.use_visual is True


def test_query_transform_is_explicitly_gated(monkeypatch):
    from core.retrieval.planner import RetrievalPlanner

    monkeypatch.setenv("QUERY_TRANSFORM_ENABLED", "true")

    assert RetrievalPlanner().plan("如何部署服务").query_transform == "hyde"


def test_quoted_natural_language_is_not_misclassified_as_identifier():
    from core.retrieval.planner import QueryType, RetrievalPlanner

    query = 'Who named the "The Simpsons" character Milhouse?'

    assert RetrievalPlanner().plan(query).query_type is QueryType.SEMANTIC


def test_planner_exception_returns_safe_default(monkeypatch):
    from core.retrieval.planner import QueryType, RetrievalPlanner

    planner = RetrievalPlanner()
    monkeypatch.setattr(planner, "_classify", lambda _query: (_ for _ in ()).throw(ValueError()))

    plan = planner.plan("anything")

    assert plan.query_type is QueryType.SEMANTIC
    assert plan.use_raptor is False
    assert plan.use_ppr is False
    assert plan.use_visual is False
    assert plan.degraded is True


def test_plan_metadata_is_redacted_and_stable():
    from core.retrieval.planner import RetrievalPlanner

    plan = RetrievalPlanner().plan("比较 A 和 B")
    metadata = plan.to_metadata()

    assert metadata["fingerprint"] == plan.fingerprint
    assert "query" not in metadata
    assert "vector" not in repr(metadata).lower()
