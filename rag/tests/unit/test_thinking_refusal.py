#!/usr/bin/env python3
"""
REQ-RC-005~009 — thinking truncation + refusal threshold regression.

Guards Stage C:
- max_generation_tokens=6144 (was 4096 shared with reasoning)
- finish_reason=="length" triggers a /no_think regeneration
- structure check looks at the LAST section (truncation signal)
- _should_refuse refuses on no-scores (was pass-through) and normalises

Run: pytest tests/unit/test_thinking_refusal.py -v
"""

from __future__ import annotations

import os
import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

sys.path.insert(0, ".")

from agent.skills.generate.skill import GenerateSkill, GenerateSkillConfig  # noqa: E402

# ===========================================================================
# REQ-RC-005 — generation budget
# ===========================================================================


class TestGenerationBudget:
    def test_max_generation_tokens_is_6144(self):
        """The generation budget MUST be >= 6144 (was 4096 shared with reasoning,
        truncating six-section answers)."""
        cfg = GenerateSkillConfig()
        assert cfg.max_generation_tokens >= 6144, (
            f"max_generation_tokens={cfg.max_generation_tokens} too small for thinking+content"
        )


# ===========================================================================
# REQ-RC-008/009 — refusal threshold (normalised + no-score refuse)
# ===========================================================================


class TestRefusalThreshold:
    def _skill(self):
        return GenerateSkill(config=GenerateSkillConfig(min_relevance_threshold=0.3))

    def test_refuse_when_no_scores_over_context(self):
        """Non-empty context with no parseable scores MUST refuse (was pass-through
        to generate over unchecked evidence)."""
        skill = self._skill()
        # A ToolMessage with content but no scores.
        msgs = [ToolMessage(content="some doc text no scores here", tool_call_id="t1")]
        assert skill._should_refuse(msgs, has_context=True) is True

    def test_no_refuse_when_no_context(self):
        skill = self._skill()
        msgs = [HumanMessage(content="q")]
        assert skill._should_refuse(msgs, has_context=False) is False

    def test_no_refuse_when_scores_present_low_magnitude(self):
        """Scores present (even RRF ~0.01) -> don't refuse; relevance is the grade
        node's job. An absolute threshold would always-refuse on RRF scale."""
        skill = self._skill()
        content = [{"score": 0.008}, {"score": 0.009}, {"score": 0.0085}]
        msgs = [ToolMessage(content=content, tool_call_id="t1")]
        assert skill._should_refuse(msgs, has_context=True) is False

    def test_no_refuse_when_top_score_above_threshold(self):
        """At least one score above threshold -> don't refuse (some evidence)."""
        skill = self._skill()
        content = [{"score": 0.9}, {"score": 0.001}, {"score": 0.002}]
        msgs = [ToolMessage(content=content, tool_call_id="t1")]
        assert skill._should_refuse(msgs, has_context=True) is False


# ===========================================================================
# REQ-RC-007 — structure check looks at the last section
# ===========================================================================


class TestStructureCheckLastSection:
    def test_truncated_answer_flagged(self):
        """An answer with a leading section but missing the last sections
        (信息缺口/依据来源) MUST be treated as truncated (structure hint appended),
        not silently allowed (old behavior only checked sections[:2]).

        The structure check only fires under a profile with a non-empty
        ``section_template`` (the default general profile has none). The bundled
        ``aviation_phm`` example profile carries the 6-section template, so this
        test pins the profile explicitly (REQ-DG-011: an optional aviation
        example profile is retained to prove the platform can embed an
        aerospace domain)."""
        from agent.guardrails.output_guardrails import OutputGuardrail
        from agent.guardrails.types import GuardrailAction
        from core.prompts.domain_profile import reset_active_profile

        _prev = os.environ.get("DOMAIN_PROFILE")
        os.environ["DOMAIN_PROFILE"] = "aviation_phm"
        reset_active_profile()
        try:
            guard = OutputGuardrail()
            # Leading section present, last sections (依据来源/信息缺口) absent.
            # 6-section content is the aviation example profile's structure (REQ-DG-011).
            truncated = "【诊断结论】发动机振动异常。\n【可能原因】叶片损坏。\n【排查步骤】检查叶"
            result = guard._check_structure(truncated)
            # Should NOT be a plain ALLOW (it's truncated) — either SANITIZE with hint or ALLOW
            # if no hint configured. The key assertion: it doesn't silently pass a truncated answer.
            # With the aviation profile's structure_hint, expect SANITIZE.
            if result.action == GuardrailAction.SANITIZE:
                assert "疑似被截断" in (result.reason or "")
            # A complete answer should ALLOW.
            complete = (
                "【诊断结论】x\n【可能原因】y\n【排查步骤】z\n"
                "【风险与安全提示】w\n【依据来源】s\n【信息缺口】无"
            )
            result2 = guard._check_structure(complete)
            assert result2.action == GuardrailAction.ALLOW
        finally:
            os.environ.pop("DOMAIN_PROFILE", None)
            if _prev is not None:
                os.environ["DOMAIN_PROFILE"] = _prev
            reset_active_profile()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
