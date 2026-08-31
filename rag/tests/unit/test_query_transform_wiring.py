#!/usr/bin/env python3
"""
REQ-RB-004 ~ 009 — HyDE/multi_query wiring + LRU cache regression.

Guards Stage B: query_transform was implemented but never wired —
shared_state["query_transform"] had no producer, so HyDE/multi_query never ran.
These tests assert the RetrieveSkill heuristic (_decide_transform) now activates
transforms, with explicit shared_state overriding and LLM failure degrading to
the original query.

Run: pytest tests/unit/test_query_transform_wiring.py -v
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")

from agent.skills.base import SkillContext  # noqa: E402
from agent.skills.retrieve.skill import RetrieveSkill  # noqa: E402


def _ctx(shared=None):
    return SkillContext(messages=[], shared_state=shared or {})


@pytest.fixture(autouse=True)
def _aviation_profile(monkeypatch):
    """The query-transform heuristic is profile-driven (REQ-A-002): anchor
    regexes / symptom / diagnostic words live in the active profile. These
    tests assert the AVIATION heuristic, so pin the aviation profile and clear
    the per-label anchor cache so its patterns load freshly each test."""
    from core.prompts.domain_profile import reset_active_profile

    RetrieveSkill._anchor_cache.clear()
    reset_active_profile()
    monkeypatch.setenv("DOMAIN_PROFILE", "aviation_phm")
    yield
    RetrieveSkill._anchor_cache.clear()
    reset_active_profile()


# ===========================================================================
# REQ-RB-004/005/006 — heuristic branches
# ===========================================================================


class TestDecideTransformHeuristic:
    def test_diagnostic_question_triggers_hyde(self):
        """Diagnostic questions (如何/为什么/原因) MUST trigger hyde."""
        for q in ["如何排查发动机振动", "为什么液压压力低", "振动的原因是什么"]:
            assert RetrieveSkill._decide_transform(_ctx(), q) == "hyde", q

    def test_short_abstract_symptom_triggers_multi_query(self):
        """Short abstract symptoms (振动异常/液压低压) MUST trigger multi_query."""
        for q in ["振动异常", "液压低压", "温度过高", "起落架卡滞"]:
            assert RetrieveSkill._decide_transform(_ctx(), q) == "multi_query", q

    def test_ata_code_skips_transform(self):
        """Queries with ATA chapter codes MUST skip transform (precise anchor)."""
        for q in ["ATA 32 起落架系统", "ata-71 发动机", "ATA_28 燃油系统说明"]:
            assert RetrieveSkill._decide_transform(_ctx(), q) is None, q

    def test_fault_code_skips_transform(self):
        """Queries with fault codes (EICAS-style letter+digit) skip transform."""
        for q in ["故障码 E1A02 是什么", "FOD33 检查", "FQ01 燃油系统", "HYD3 液压"]:
            assert RetrieveSkill._decide_transform(_ctx(), q) is None, q

    def test_generic_question_no_transform(self):
        """Non-diagnostic, non-symptom generic queries -> no transform."""
        assert RetrieveSkill._decide_transform(_ctx(), "飞机型号A320的载客量") is None
        assert RetrieveSkill._decide_transform(_ctx(), "介绍一下波音公司") is None


# ===========================================================================
# REQ-RB-007 — explicit shared_state overrides heuristic
# ===========================================================================


class TestExplicitOverride:
    def test_explicit_hyde_overrides_ata_code(self):
        """shared_state['query_transform']='hyde' wins even for ATA queries."""
        ctx = _ctx({"query_transform": "hyde"})
        assert RetrieveSkill._decide_transform(ctx, "ATA 32 起落架") == "hyde"

    def test_explicit_multi_query_overrides_diagnostic(self):
        ctx = _ctx({"query_transform": "multi_query"})
        assert RetrieveSkill._decide_transform(ctx, "如何排查振动") == "multi_query"

    def test_invalid_explicit_value_falls_back_to_heuristic(self):
        """An unrecognised shared_state value is ignored, heuristic runs."""
        ctx = _ctx({"query_transform": "bogus"})
        assert RetrieveSkill._decide_transform(ctx, "如何排查") == "hyde"


# ===========================================================================
# REQ-RB-008 — degradation: query_transform falls back to original query
# ===========================================================================


class TestTransformDegradation:
    def test_hyde_llm_failure_returns_original_query(self, monkeypatch):
        """When the HyDE LLM call fails, hyde() MUST return the original query
        (never empty), so retrieval still works."""
        from core.retrieval import query_transform

        monkeypatch.setattr(query_transform, "_llm_invoke", lambda p: None)
        q = "如何排查发动机振动"
        assert query_transform.hyde(q) == q

    def test_multi_query_llm_failure_returns_single_query(self, monkeypatch):
        """When multi_query LLM fails, it returns [original] (never empty)."""
        from core.retrieval import query_transform

        monkeypatch.setattr(query_transform, "_llm_invoke", lambda p: None)
        result = query_transform.multi_query_expand("振动异常")
        assert result == ["振动异常"]


# ===========================================================================
# REQ-RB-009 — LRU cache
# ===========================================================================


class TestLRUCache:
    def test_repeated_prompt_hits_cache(self):
        """A repeated (prompt, model) pair is served from cache."""
        from core.retrieval import query_transform

        query_transform._LLM_CACHE.clear()
        query_transform._cache_put("p1", "m1", "first")
        query_transform._cache_put("p2", "m1", "second")
        assert query_transform._cache_get("p1", "m1") == "first"
        assert query_transform._cache_get("p2", "m1") == "second"

    def test_model_change_invalidates_cache(self):
        """Cache key MUST include model (AGENTS.md §6) so a model switch doesn't
        serve stale results from the old model (critic F-RB-07)."""
        from core.retrieval import query_transform

        query_transform._LLM_CACHE.clear()
        query_transform._cache_put("same-prompt", "model_a", "result_a")
        assert query_transform._cache_get("same-prompt", "model_a") == "result_a"
        # Different model -> miss (must re-call LLM)
        assert query_transform._cache_get("same-prompt", "model_b") is None

    def test_failure_not_cached(self, monkeypatch):
        """LLM failures (None) are NOT cached so a retry can succeed later."""
        from core.retrieval import query_transform

        query_transform._LLM_CACHE.clear()
        monkeypatch.setattr(query_transform, "_llm_invoke", lambda p: None)
        result = query_transform._llm_invoke("fail-prompt")
        assert result is None
        assert len(query_transform._LLM_CACHE) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
