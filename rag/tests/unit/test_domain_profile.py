#!/usr/bin/env python3
"""
DomainProfile unit tests — verify the domain-adaptive configuration layer:
loading, env selection, fallback, and field completeness for both the default
aviation_phm profile and the domain-agnostic general profile.

Run: uv run --frozen python -m pytest tests/unit/test_domain_profile.py -v
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, ".")


@pytest.fixture(autouse=True)
def _reset_profile():
    """Ensure each test starts with a clean active-profile cache."""
    from core.prompts.domain_profile import reset_active_profile

    reset_active_profile()
    yield
    reset_active_profile()


# ===========================================================================
# Loading & fallback
# ===========================================================================


class TestProfileLoading:
    def test_load_general_default(self, monkeypatch):
        """[REQ-A-001] With no DOMAIN_PROFILE env, the default profile is the
        domain-agnostic general profile (BREAKING: was aviation_phm)."""
        from core.prompts.domain_profile import load_domain_profile

        monkeypatch.delenv("DOMAIN_PROFILE", raising=False)
        profile = load_domain_profile()
        assert profile.name == "general"
        assert profile.profile_label == "general"

    def test_load_aviation_phm_explicit(self, monkeypatch):
        """Aviation is now opt-in via DOMAIN_PROFILE=aviation_phm."""
        from core.prompts.domain_profile import load_domain_profile

        profile = load_domain_profile("aviation_phm")
        assert profile.name == "aviation_phm"
        assert profile.profile_label == "phm"

    def test_load_general_explicit(self, monkeypatch):
        from core.prompts.domain_profile import load_domain_profile

        profile = load_domain_profile("general")
        assert profile.name == "general"
        assert profile.profile_label == "general"

    def test_load_unknown_falls_back_to_general(self, monkeypatch):
        from core.prompts.domain_profile import load_domain_profile

        profile = load_domain_profile("does-not-exist")
        # Fallback never raises; returns the general defaults.
        assert profile.name == "general"

    def test_env_selects_profile(self, monkeypatch):
        from core.prompts.domain_profile import get_active_profile

        monkeypatch.setenv("DOMAIN_PROFILE", "general")
        assert get_active_profile().name == "general"

        from core.prompts.domain_profile import reset_active_profile

        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", "aviation_phm")
        assert get_active_profile().name == "aviation_phm"

    def test_get_active_profile_caches(self, monkeypatch):
        from core.prompts.domain_profile import get_active_profile

        monkeypatch.setenv("DOMAIN_PROFILE", "general")
        first = get_active_profile()
        second = get_active_profile()
        assert first is second  # cached


# ===========================================================================
# Aviation profile field completeness (backward-compat contract)
# ===========================================================================


class TestAviationProfile:
    def test_has_phm_sections(self, monkeypatch):
        from core.prompts.domain_profile import load_domain_profile

        profile = load_domain_profile("aviation_phm")
        assert "诊断结论" in profile.section_template
        assert "排查步骤" in profile.section_template

    def test_prompt_profile_labels_backward_compat(self, monkeypatch):
        from core.prompts.domain_profile import load_domain_profile

        profile = load_domain_profile("aviation_phm")
        # profile_label=phm preserves the historical phm_*_v1 strings.
        assert profile.prompt_profile_generate == "phm_diagnosis_v1"
        assert profile.prompt_profile_general == "phm_general_v1"
        assert profile.prompt_profile_fast == "phm_fast_v1"
        assert profile.prompt_profile_identity == "phm_identity_v1"

    def test_has_domain_keywords_without_generic_question_words(self, monkeypatch):
        from core.prompts.domain_profile import load_domain_profile

        profile = load_domain_profile("aviation_phm")
        # domain_keywords (routing fast-path) must NOT contain generic
        # question words, else every query routes to RAG.
        assert "振动" in profile.domain_keywords
        assert "什么" not in profile.domain_keywords
        assert "如何" not in profile.domain_keywords

    def test_prompts_populated(self, monkeypatch):
        from core.prompts.domain_profile import load_domain_profile

        profile = load_domain_profile("aviation_phm")
        for key in (
            "generate_system",
            "generate_human",
            "general_chat_system",
            "rewrite",
            "grade_system",
            "grade_human",
            "intent",
            "agent_system",
            "hyde",
            "entail",
        ):
            assert profile.prompts[key], f"prompt {key} empty"


# ===========================================================================
# General profile is domain-agnostic
# ===========================================================================


class TestGeneralProfile:
    def test_no_domain_sections(self, monkeypatch):
        from core.prompts.domain_profile import load_domain_profile

        profile = load_domain_profile("general")
        assert profile.section_template == []
        assert profile.structure_hint == ""

    def test_no_domain_keywords(self, monkeypatch):
        from core.prompts.domain_profile import load_domain_profile

        profile = load_domain_profile("general")
        # No domain-specific routing keywords -> intent classification goes
        # to the LLM instead of a domain keyword fast-path.
        assert profile.rag_keywords == []
        assert profile.domain_keywords == []

    def test_prompts_neutral(self, monkeypatch):
        from core.prompts.domain_profile import load_domain_profile

        profile = load_domain_profile("general")
        gen = profile.prompts["generate_system"]
        # Must not mention aviation-specific terms.
        assert "飞机" not in gen
        assert "PHM" not in gen
        assert "ATA" not in gen

    def test_prompt_profile_labels_general(self, monkeypatch):
        """[REQ-A-005] General profile uses a domain-neutral suffix: general_v1
        (was general_diagnosis_v1 when the suffix was hardcoded)."""
        from core.prompts.domain_profile import load_domain_profile

        profile = load_domain_profile("general")
        assert profile.prompt_profile_generate == "general_v1"


# ===========================================================================
# Routing/structure behaviour is profile-driven
# ===========================================================================


class TestProfileDrivenBehaviour:
    def test_looks_like_domain_query_aviation(self, monkeypatch):
        from api.routers.chat import _looks_like_domain_query
        from core.prompts.domain_profile import reset_active_profile

        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", "aviation_phm")
        assert _looks_like_domain_query("发动机振动异常") is True
        # A non-aviation query under the aviation profile is NOT force-routed.
        assert _looks_like_domain_query("光合作用的化学方程式") is False

    def test_looks_like_domain_query_general_never_forces(self, monkeypatch):
        from api.routers.chat import _looks_like_domain_query
        from core.prompts.domain_profile import reset_active_profile

        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", "general")
        # General profile has no domain keywords -> never force-routes.
        assert _looks_like_domain_query("发动机振动异常") is False
        assert _looks_like_domain_query("光合作用") is False

    def test_extract_diagnosis_aviation(self, monkeypatch):
        from api.routers.chat import _extract_structured_answer
        from core.prompts.domain_profile import reset_active_profile

        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", "aviation_phm")
        answer = "【诊断结论】振动偏高\n【排查步骤】1. 频谱分析"
        diag = _extract_structured_answer(answer)
        assert diag is not None
        # Field renamed conclusion->summary (domain-generalization REQ-DG-004).
        assert "振动" in diag.summary
        # The old diagnosis-leaning field names must no longer exist.
        assert not hasattr(diag, "conclusion")
        assert not hasattr(diag, "safety_risks")

    def test_extract_diagnosis_general_returns_none(self, monkeypatch):
        from api.routers.chat import _extract_structured_answer
        from core.prompts.domain_profile import reset_active_profile

        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", "general")
        # No section template -> free-form answers, returns None.
        assert _extract_structured_answer("任意自由文本回答") is None

    def test_input_guardrail_aviation_allows_domain(self, monkeypatch):
        from agent.guardrails.input_guardrails import InputGuardrail

        # Under aviation profile, a domain query is allowed.
        ig = InputGuardrail()
        assert ig._check_topic("发动机振动异常").action.value == "allow"

    def test_input_guardrail_general_allows_everything(self, monkeypatch):
        from agent.guardrails.input_guardrails import InputGuardrail
        from core.prompts.domain_profile import reset_active_profile

        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", "general")
        ig = InputGuardrail()
        # Under general profile, even an off-domain query is allowed (no
        # domain vocabulary to gate on).
        assert ig._check_topic("光合作用的化学方程式").action.value == "allow"


# ===========================================================================
# Residual consumers are domain-agnostic under the general profile (D-residual)
# ===========================================================================


class TestResidualConsumersGeneral:
    """The lower-priority consumers (judge / memory / query-transform /
    retrieval-server tool desc / bm25 normalize / pii operational) must not
    leak aviation content under the general profile."""

    def test_judge_entail_prompt_neutral_under_general(self, monkeypatch):
        from agent.eval.judge import LLMJudge
        from core.prompts.domain_profile import reset_active_profile

        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", "general")
        prompt = LLMJudge._entail_prompt("claim-x", "context-y")
        assert "航空" not in prompt
        assert "排故" not in prompt
        # Injection-hardening fencing is domain-neutral and always present.
        assert "<<<检索内容>>>" in prompt

    def test_memory_extractor_no_facts_under_general(self, monkeypatch):
        from agent.memory.extractor import MemoryExtractor
        from core.prompts.domain_profile import reset_active_profile

        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", "general")
        # No section template -> free-form answers yield no section-keyed facts.
        entries = MemoryExtractor().extract_facts(
            "q",
            "【诊断结论】振动偏高",  # aviation markers ignored under general
        )
        assert entries == []

    def test_memory_extractor_facts_under_aviation(self, monkeypatch):
        from agent.memory.extractor import MemoryExtractor
        from core.prompts.domain_profile import reset_active_profile

        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", "aviation_phm")
        entries = MemoryExtractor().extract_facts("q", "【诊断结论】振动偏高\n【可能原因】不平衡")
        assert any("诊断结论" in e.content for e in entries)

    def test_hyde_prompt_neutral_under_general(self, monkeypatch):
        from core.prompts.domain_profile import reset_active_profile
        from core.retrieval.query_transform import _hyde_prompt_template

        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", "general")
        tmpl = _hyde_prompt_template()
        assert "排故" not in tmpl
        assert "诊断" not in tmpl

    def test_multi_query_prompt_neutral_under_general(self, monkeypatch):
        from core.prompts.domain_profile import reset_active_profile
        from core.retrieval.query_transform import _multi_query_prompt_template

        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", "general")
        tmpl = _multi_query_prompt_template()
        assert "维修手册" not in tmpl

    def test_retriever_tool_desc_neutral_under_general(self, monkeypatch):
        from agent.mcp.retrieval_server import MCPRetrievalServer
        from core.prompts.domain_profile import reset_active_profile

        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", "general")
        srv = MCPRetrievalServer()
        tools = srv.list_tools()
        retrieve = next(t for t in tools if t["name"] == "rag_retrieve")
        assert "飞机" not in retrieve["description"]
        assert "排故" not in retrieve["description"]

    def test_bm25_normalize_ata_only_under_aviation(self, monkeypatch):
        from core.prompts.domain_profile import reset_active_profile
        from core.retrieval.bm25_retriever import BM25Retriever

        reset_active_profile()
        # Aviation: ATA forms unified.
        monkeypatch.setenv("DOMAIN_PROFILE", "aviation_phm")
        bm25 = BM25Retriever()
        assert bm25._normalize_text("ATA 32 振动") == "ata32 振动"

        # General: no ATA pattern -> ATA token left untouched.
        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", "general")
        bm25g = BM25Retriever()
        assert bm25g._normalize_text("ATA 32 振动") == "ata 32 振动"

    def test_pii_operational_patterns_from_profile(self, monkeypatch):
        from agent.guardrails.pii import _operational_patterns_from_profile
        from core.prompts.domain_profile import reset_active_profile

        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", "aviation_phm")
        kinds = {k for k, _ in _operational_patterns_from_profile()}
        assert "tail_number" in kinds
        assert "msn" in kinds

        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", "general")
        # [REQ-A-002] General profile EXPLICITLY declares an empty operational
        # list -> NO aviation tail_number/MSN fallback leaks. (Detection is still
        # gated behind PII_DETECT_OPERATIONAL_IDS, off by default; this asserts
        # the pattern set itself is clean.)
        kinds_g = {k for k, _ in _operational_patterns_from_profile()}
        assert "tail_number" not in kinds_g
        assert "msn" not in kinds_g
        assert kinds_g == set()


# ===========================================================================
# Retrieve-skill heuristic is profile-driven (REQ-A-002)
# ===========================================================================


class TestRetrieveHeuristicProfileDriven:
    """``RetrieveSkill._decide_transform`` must read anchor/symptom/diagnostic
    lists from the active profile — no aviation literals in source. Aviation
    behaviour is preserved byte-for-byte; general never triggers aviation regex."""

    def _decide(self, query, monkeypatch, profile_name):
        from agent.skills.retrieve.skill import RetrieveSkill, SkillContext

        # Clear the per-label anchor cache so the new profile's patterns load.
        RetrieveSkill._anchor_cache.clear()
        from core.prompts.domain_profile import reset_active_profile

        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", profile_name)
        ctx = SkillContext(messages=[], shared_state={})
        return RetrieveSkill._decide_transform(ctx, query)

    def test_aviation_anchor_skips_transform(self, monkeypatch):
        # ATA / fault code present -> None (precise anchor, direct retrieval).
        assert self._decide("ATA 32 振动", monkeypatch, "aviation_phm") is None
        assert self._decide("故障码 E1A02", monkeypatch, "aviation_phm") is None

    def test_aviation_diagnostic_verb_triggers_hyde(self, monkeypatch):
        assert self._decide("发动机为什么振动偏高", monkeypatch, "aviation_phm") == "hyde"

    def test_aviation_short_symptom_triggers_multi_query(self, monkeypatch):
        assert self._decide("液压低压", monkeypatch, "aviation_phm") == "multi_query"

    def test_general_never_matches_aviation_anchors(self, monkeypatch):
        # Under general, ATA/fault-code/symptom patterns are empty -> these
        # queries fall through to direct retrieval (None), proving no aviation
        # regex leaks into a non-aviation deployment.
        assert self._decide("ATA 32 振动", monkeypatch, "general") is None
        assert self._decide("故障码 E1A02", monkeypatch, "general") is None
        assert self._decide("液压低压", monkeypatch, "general") is None

    def test_general_diagnostic_verb_still_triggers_hyde(self, monkeypatch):
        # Domain-neutral diagnostic verbs (如何/为什么) are general defaults,
        # so hyde still fires for a genuinely diagnostic question.
        assert self._decide("为什么会这样", monkeypatch, "general") == "hyde"


# ===========================================================================
# fast_mode empty-context fallback is profile-driven (REQ-A-002)
# ===========================================================================


class TestFastModeFallbackProfileDriven:
    def test_fallback_uses_profile_message(self, monkeypatch):
        import core.fast_mode as fm
        import core.retrieval.hybrid_retriever as hr
        from core.prompts.domain_profile import reset_active_profile

        reset_active_profile()
        monkeypatch.setenv("DOMAIN_PROFILE", "aviation_phm")

        # Stub the retriever to return no documents. fast_generate imports
        # get_hybrid_retriever locally from core.retrieval.hybrid_retriever.
        class _Empty:
            def retrieve(self, *a, **k):
                return []

        monkeypatch.setattr(hr, "get_hybrid_retriever", lambda: _Empty())
        result = fm.fast_generate("任何问题")
        from core.prompts.domain_profile import get_active_profile

        assert result.answer == get_active_profile().empty_context_message
        # Aviation empty-context message contains the historical phrasing.
        assert "手册" in result.answer


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
