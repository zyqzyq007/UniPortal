#!/usr/bin/env python3
"""
Unit tests for the P0 generation-time trustworthiness features:
  - online grounding guardrail (NLI hallucination check)
  - output guardrail integration with grounding
  - answer confidence computation
  - refuse-to-answer on weak retrieval

These do NOT call the real LLM — the judge is stubbed where needed.

Run: pytest tests/unit/test_grounding_guardrail.py -v
"""

from __future__ import annotations

import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

sys.path.insert(0, ".")


# ===========================================================================
# GroundingGuardrail
# ===========================================================================


class TestGroundingGuardrail:
    def _make_guardrail(self, monkeypatch, entail_responses):
        """Build a GroundingGuardrail with a stubbed judge."""
        from agent.guardrails.grounding_guardrail import GroundingGuardrail

        responses = list(entail_responses)

        class _StubVerdict:
            def __init__(self, supported):
                self.supported = supported
                self.rationale = ""

        class _StubJudge:
            available = True

            def entail(self, claim, context_blob):
                if responses:
                    return _StubVerdict(responses.pop(0))
                return _StubVerdict(True)

            # Back-compat alias for any caller still on the private name.
            def _entail(self, claim, context_blob):
                return self.entail(claim, context_blob)

        return GroundingGuardrail(judge=_StubJudge())

    def test_all_hard_claims_grounded(self, monkeypatch):
        # One hard claim, supported -> faithfulness 1.0
        g = self._make_guardrail(monkeypatch, [True])
        result = g.check("超时应为 30 秒。", ["文档写明超时 30 秒。"])
        assert result.available
        assert result.faithfulness == 1.0

    def test_hard_claim_unsupported(self, monkeypatch):
        g = self._make_guardrail(monkeypatch, [False])
        result = g.check("超时应为 30 秒。", ["文档未提及超时。"])
        assert result.faithfulness == 0.0
        assert len(result.unsupported_claims) == 1

    def test_no_hard_claims_is_fully_grounded(self, monkeypatch):
        # Soft answer (no values/steps/conclusions) => faithfulness 1.0
        g = self._make_guardrail(monkeypatch, [])
        result = g.check("请进一步检查该系统。", ["context"])
        assert result.faithfulness == 1.0

    def test_degraded_when_judge_unavailable(self, monkeypatch):
        from agent.guardrails.grounding_guardrail import GroundingGuardrail

        class _DeadJudge:
            available = False

        g = GroundingGuardrail(judge=_DeadJudge())
        result = g.check("超时阈值 30。", ["ctx"])
        assert not result.available
        assert result.degraded
        assert result.faithfulness is None

    def test_never_raises_on_error(self, monkeypatch):
        from agent.guardrails.grounding_guardrail import GroundingGuardrail

        class _ExplodingJudge:
            available = True

            def entail(self, *a, **k):
                raise RuntimeError("boom")

            def _entail(self, *a, **k):
                return self.entail(*a, **k)

        g = GroundingGuardrail(judge=_ExplodingJudge())
        result = g.check("超时阈值 30。", ["ctx"])
        assert not result.available  # degraded, not raised


# ===========================================================================
# OutputGuardrail grounding integration
# ===========================================================================


class TestOutputGuardrailGrounding:
    def _patch_check(self, monkeypatch, fake):
        # check_grounding is imported locally inside _check_hallucination, so
        # patch it on its source module (grounding_guardrail).
        from agent.guardrails import grounding_guardrail as gg_mod

        monkeypatch.setattr(gg_mod, "check_grounding", fake)

    def test_grounding_allows_well_grounded(self, monkeypatch):
        class _FakeResult:
            available = True
            faithfulness = 0.9
            supported = 9
            total = 10
            unsupported_claims = []
            degraded = False
            reason = "ok"

            def to_dict(self):
                return {"faithfulness": 0.9}

        self._patch_check(monkeypatch, lambda a, c: _FakeResult())

        from agent.guardrails.output_guardrails import OutputGuardrail

        og = OutputGuardrail()
        # answer with safety disclaimer so only hallucination matters
        result = og.validate(
            "【结论】测试。仅供参考。",
            sources=["doc"],
            contexts=["context"],
        )
        assert result.action.value == "allow"

    def test_grounding_sanitizes_partial(self, monkeypatch):
        class _FakeResult:
            available = True
            faithfulness = 0.3
            supported = 3
            total = 10
            unsupported_claims = ["c1"]
            degraded = False
            reason = "low"

            def to_dict(self):
                return {"faithfulness": 0.3}

        self._patch_check(monkeypatch, lambda a, c: _FakeResult())

        from agent.guardrails.output_guardrails import OutputGuardrail

        og = OutputGuardrail()
        result = og.validate(
            "【结论】测试。仅供参考。",
            sources=["doc"],
            contexts=["context"],
        )
        assert result.action.value == "sanitize"
        assert "⚠️" in (result.sanitized_content or "")

    def test_grounding_escalates_fully_unsupported(self, monkeypatch):
        class _FakeResult:
            available = True
            faithfulness = 0.0
            supported = 0
            total = 5
            unsupported_claims = ["c1", "c2"]
            degraded = False
            reason = "none"

            def to_dict(self):
                return {"faithfulness": 0.0}

        self._patch_check(monkeypatch, lambda a, c: _FakeResult())

        from agent.guardrails.output_guardrails import OutputGuardrail

        og = OutputGuardrail()
        result = og.validate(
            "【结论】测试。仅供参考。",
            sources=["doc"],
            contexts=["context"],
        )
        assert result.action.value == "escalate"

    def test_falls_back_to_regex_when_grounding_degraded(self, monkeypatch):
        class _DegradedResult:
            available = False
            faithfulness = None
            degraded = True

            def to_dict(self):
                return {}

        self._patch_check(monkeypatch, lambda a, c: _DegradedResult())

        from agent.guardrails.output_guardrails import OutputGuardrail

        og = OutputGuardrail()
        # Grounding degraded + no sources => regex allows; the only possible
        # action now is a safety-disclaimer SANITIZE (not an ESCALATE/BLOCK).
        # Include a disclaimer so we isolate the hallucination path.
        result = og.validate("测试答案，仅供参考注意安全风险。", sources=None, contexts=["ctx"])
        # Must NOT escalate or block on degraded grounding.
        assert result.action.value in ("allow", "sanitize")


class TestCachedFaithReuse:
    """The generate skill publishes grounding_faithfulness; the output guardrail
    should reuse it (cached_faith) instead of re-invoking the judge."""

    def _guardrail(self):
        from agent.guardrails.output_guardrails import OutputGuardrail
        from agent.guardrails.types import GuardrailConfig

        # Disable safety/structure so only the grounding path is exercised.
        return OutputGuardrail(
            GuardrailConfig(
                enable_grounding_check=True,
                enable_hallucination_check=True,
                enable_safety_check=False,
                enable_structure_check=False,
                grounding_escalate_threshold=0.0,
                grounding_threshold=0.5,
            )
        )

    def test_cached_faith_zero_escalates_without_judge(self, monkeypatch):
        # If the cached path works, the judge is never called. Prove it by
        # making any judge call explode.
        from agent.guardrails import grounding_guardrail as gg_mod

        def _explode(*a, **k):
            raise AssertionError("judge should not be called when cached_faith given")

        monkeypatch.setattr(gg_mod, "check_grounding", _explode)

        og = self._guardrail()
        result = og.validate("结论。", sources=["s"], contexts=["ctx"], cached_faith=0.0)
        assert result.action.value == "escalate"

    def test_cached_faith_low_sanitizes_without_judge(self, monkeypatch):
        from agent.guardrails import grounding_guardrail as gg_mod

        monkeypatch.setattr(
            gg_mod,
            "check_grounding",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("no judge")),
        )
        og = self._guardrail()
        result = og.validate("结论。", sources=["s"], contexts=["ctx"], cached_faith=0.3)
        assert result.action.value == "sanitize"
        assert "⚠️" in (result.sanitized_content or "")

    def test_cached_faith_high_allows_without_judge(self, monkeypatch):
        from agent.guardrails import grounding_guardrail as gg_mod

        monkeypatch.setattr(
            gg_mod,
            "check_grounding",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("no judge")),
        )
        og = self._guardrail()
        result = og.validate("结论。", sources=["s"], contexts=["ctx"], cached_faith=0.9)
        assert result.action.value == "allow"

    def test_cached_faith_works_even_without_contexts(self, monkeypatch):
        # cached_faith alone is enough to enter the NLI branch.
        from agent.guardrails import grounding_guardrail as gg_mod

        monkeypatch.setattr(
            gg_mod,
            "check_grounding",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("no judge")),
        )
        og = self._guardrail()
        result = og.validate("结论。", cached_faith=0.9)
        assert result.action.value == "allow"


class TestGuardrailManagerCachedFaith:
    def test_manager_passes_cached_faith_to_output(self):
        from agent.guardrails import grounding_guardrail as gg_mod
        from agent.guardrails.manager import GuardrailManager

        captured = {}

        class _FakeResult:
            available = True
            faithfulness = 0.9
            supported = 9
            total = 10
            unsupported_claims = []
            degraded = False
            reason = "ok"

            def to_dict(self):
                return {"faithfulness": 0.9}

        def _spy_check(answer, sources=None, contexts=None, cached_faith=None):
            captured["cached_faith"] = cached_faith
            from agent.guardrails.types import GuardrailAction, GuardrailResult

            return GuardrailResult(action=GuardrailAction.ALLOW)

        gm = GuardrailManager()
        # Monkeypatch the underlying OutputGuardrail.validate to spy on args.
        gm._output.validate = _spy_check  # type: ignore[assignment]
        gm.check_output("ans", sources=["s"], contexts=["c"], cached_faith=0.42)
        assert captured["cached_faith"] == 0.42


# ===========================================================================
# GenerateSkill: refuse-to-answer + confidence
# ===========================================================================


class TestGenerateRefusal:
    def test_does_not_refuse_when_scores_present(self):
        # Stage C: scores parseable -> generation proceeds (relevance is the grade
        # node's job; raw scores have no universal magnitude). Was: refuse when
        # all below 0.3, which always-refused on RRF ~0.01 scale.
        from agent.skills.generate.skill import GenerateSkill

        messages = [
            HumanMessage(content="某个知识库外的问题"),
            ToolMessage(
                content=[
                    {"text": "无关片段A", "score": 0.1},
                    {"text": "无关片段B", "score": 0.15},
                ],
                tool_call_id="c1",
            ),
        ]
        skill = GenerateSkill()
        assert skill._should_refuse(messages, has_context=True) is False

    def test_does_not_refuse_when_some_relevant(self):
        from agent.skills.generate.skill import GenerateSkill

        messages = [
            HumanMessage(content="q"),
            ToolMessage(
                content=[
                    {"text": "高度相关", "score": 0.85},
                    {"text": "无关", "score": 0.1},
                ],
                tool_call_id="c1",
            ),
        ]
        skill = GenerateSkill()
        assert skill._should_refuse(messages, has_context=True) is False

    def test_does_not_refuse_without_context(self):
        from agent.skills.generate.skill import GenerateSkill

        skill = GenerateSkill()
        assert skill._should_refuse([], has_context=False) is False

    def test_refuses_when_no_scores_over_context(self):
        # Stage C REQ-RC-008: no parseable scores over a non-empty context ->
        # refuse (was a silent pass-through to generate over unchecked evidence).
        from agent.skills.generate.skill import GenerateSkill

        messages = [
            HumanMessage(content="q"),
            ToolMessage(content="no scores here", tool_call_id="c1"),
        ]
        skill = GenerateSkill()
        assert skill._should_refuse(messages, has_context=True) is True


class TestGenerateConfidence:
    def test_confidence_blends_signals(self):
        from agent.skills.generate.skill import GenerateSkill

        skill = GenerateSkill()
        # retrieval=0.8, grounding=0.9, intent=1.0
        # weights 0.4/0.4/0.2 => 0.32+0.36+0.20 = 0.88
        shared = {"retrieval_relevance": 0.8, "intent_confidence": 1.0}
        conf, degraded = skill._compute_confidence(shared, 0.9)
        assert conf == pytest.approx(0.88, abs=0.01)
        assert degraded is False

    def test_confidence_degraded_without_grounding(self):
        from agent.skills.generate.skill import GenerateSkill

        skill = GenerateSkill()
        shared = {"retrieval_relevance": 0.8, "intent_confidence": 1.0}
        # grounding None => weight redistributed to retrieval (0.8/1.0)
        conf, degraded = skill._compute_confidence(shared, None)
        assert degraded is True
        # 0.8*(0.8)+1.0*(0.2) / 1.0 = 0.84
        assert conf == pytest.approx(0.84, abs=0.01)

    def test_confidence_uses_relevance_scores_fallback(self):
        from agent.skills.generate.skill import GenerateSkill

        skill = GenerateSkill()
        # No retrieval_relevance, but relevance_scores list present.
        shared = {"relevance_scores": [0.6, 0.8], "intent_confidence": 1.0}
        conf, degraded = skill._compute_confidence(shared, None)
        # retrieval fallback = 0.7; degraded (no grounding)
        assert degraded is True
        assert 0.0 <= conf <= 1.0

    def test_confidence_zero_when_no_signals(self):
        from agent.skills.generate.skill import GenerateSkill

        skill = GenerateSkill()
        conf, degraded = skill._compute_confidence({}, None)
        assert conf == 0.0
        assert degraded is True

    def test_extract_relevance_scores_from_string(self):
        from agent.skills.generate.skill import GenerateSkill

        messages = [
            HumanMessage(content="q"),
            ToolMessage(
                content="[证据1] 相关度=0.8500\n文本\n\n[证据2] 相关度=0.3000\n文本",
                tool_call_id="c1",
            ),
        ]
        scores = GenerateSkill._extract_relevance_scores(messages)
        assert scores == [0.85, 0.3]


# ===========================================================================
# GuardrailConfig env wiring
# ===========================================================================


class TestGuardrailConfigEnv:
    def test_grounding_config_defaults(self):
        from agent.guardrails.types import GuardrailConfig

        cfg = GuardrailConfig()
        assert cfg.enable_grounding_check is True
        assert cfg.grounding_threshold == 0.5

    def test_grounding_config_from_env(self, monkeypatch):
        monkeypatch.setenv("GROUNDING_CHECK_ENABLED", "false")
        monkeypatch.setenv("GROUNDING_THRESHOLD", "0.7")
        # Re-import to pick up env (module-level _env helpers read at class def).
        import importlib

        import agent.guardrails.types as types_mod

        importlib.reload(types_mod)
        cfg = types_mod.GuardrailConfig()
        assert cfg.enable_grounding_check is False
        assert cfg.grounding_threshold == 0.7


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
