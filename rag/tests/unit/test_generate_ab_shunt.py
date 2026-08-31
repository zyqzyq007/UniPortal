#!/usr/bin/env python3
"""
Layer ⑤ — GenerateSkill A/B shunt (v2: prob-gated, decoupled from rewrite_count).

Bug2 Layer ⑤: when retrieval yields only weak/unusable docs, the generate node
must distinguish two failures:
  - high-confidence RAG query, no usable docs -> KB genuinely missing -> REFUSE
  - low-confidence (misrouted general question), no usable docs -> FALLBACK to
    general_chat via a sentinel (chat.py takeover)

v1 bound the trigger to is_rewrite_limit_reached and judged via has_context —
both wrong (critic F-01/F-02): the real misroute trajectory is first-pass
grade=yes with rewrite_count=0, and has_context is always True after min-max.
v2 evaluates on EVERY generate entry using max_rerank_prob (shared ruler with
Layer ④), decoupled from rewrite_count.

Run: uv run --frozen python -m pytest tests/unit/test_generate_ab_shunt.py -v
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")


def _make_context(
    *,
    context_text: str,
    max_rerank_prob: float | None,
    intent_confidence: float | None,
    rewrite_count: int = 0,
    max_rewrites: int = 3,
):
    """Build a SkillContext with the shunt's required inputs."""
    from langchain_core.messages import AIMessage, HumanMessage

    from agent.skills.base import SkillContext

    messages = [
        HumanMessage(content="你能解决什么问题"),
        AIMessage(content=context_text),
    ]
    ctx = SkillContext(
        messages=messages,
        rewrite_count=rewrite_count,
        max_rewrites=max_rewrites,
        shared_state={},
    )
    if max_rerank_prob is not None:
        ctx.shared_state["max_rerank_prob"] = max_rerank_prob
    if intent_confidence is not None:
        ctx.shared_state["intent_confidence"] = intent_confidence
    return ctx


# ===========================================================================
# _should_fallback_or_refuse — the shunt decision
# ===========================================================================


class TestShouldFallbackOrRefuse:
    """[REQ-RG-013/013a] The shunt decision uses max_rerank_prob (not
    has_context) and fires on every generate entry (not just rewrite-exhausted)."""

    def _skill(self, monkeypatch, min_relevance_threshold=0.35):
        import utils.env_utils as env
        from agent.skills.generate.skill import GenerateSkill, GenerateSkillConfig

        monkeypatch.setattr(env, "LOW_INTENT_THRESHOLD", 0.5)
        return GenerateSkill(
            config=GenerateSkillConfig(min_relevance_threshold=min_relevance_threshold)
        )

    def test_degraded_no_shunt(self, monkeypatch):
        """[REQ-RG-013] max_rerank_prob=None (reranker degraded) -> no shunt;
        fall through to existing _should_refuse (degradation: prefer recall)."""
        skill = self._skill(monkeypatch)
        ctx = _make_context(context_text="some doc", max_rerank_prob=None, intent_confidence=0.4)
        assert skill._should_fallback_or_refuse(ctx) is None

    def test_strong_doc_no_shunt(self, monkeypatch):
        """max_rerank_prob >= min_relevance_threshold -> normal generation."""
        skill = self._skill(monkeypatch, min_relevance_threshold=0.35)
        ctx = _make_context(context_text="strong doc", max_rerank_prob=0.88, intent_confidence=0.4)
        assert skill._should_fallback_or_refuse(ctx) is None

    def test_failtrack1_weak_batch_low_confidence_fallback(self, monkeypatch):
        """[F-01/02/03 real path] Weak batch (max_rerank_prob≈0.047) +
        first-pass grade=yes (rewrite_count=0) + low intent_conf -> FALLBACK.
        This is the exact trajectory v1 missed."""
        skill = self._skill(monkeypatch, min_relevance_threshold=0.35)
        ctx = _make_context(
            context_text="weak doc",
            max_rerank_prob=0.047,
            intent_confidence=0.4,  # < LOW_INTENT_THRESHOLD 0.5
            rewrite_count=0,  # first-pass grade=yes, NOT rewrite-exhausted
        )
        assert skill._should_fallback_or_refuse(ctx) == "fallback_general_chat"

    def test_failtrack2_weak_batch_high_confidence_refuse(self, monkeypatch):
        """Weak batch + high intent_conf -> REFUSE (KB genuinely missing)."""
        skill = self._skill(monkeypatch, min_relevance_threshold=0.35)
        ctx = _make_context(
            context_text="weak doc",
            max_rerank_prob=0.047,
            intent_confidence=0.8,  # >= LOW_INTENT_THRESHOLD
            rewrite_count=3,  # rewrite exhausted
        )
        assert skill._should_fallback_or_refuse(ctx) == "refuse"

    def test_failtrack3_strong_doc_normal(self, monkeypatch):
        """Strong docs must NOT be mis-refused."""
        skill = self._skill(monkeypatch, min_relevance_threshold=0.35)
        ctx = _make_context(context_text="strong doc", max_rerank_prob=0.9, intent_confidence=0.4)
        assert skill._should_fallback_or_refuse(ctx) is None

    def test_shunt_fires_on_first_pass_not_only_rewrite_exhausted(self, monkeypatch):
        """[F-02] The shunt MUST fire at rewrite_count=0 (first-pass grade=yes),
        not only after rewrite exhaustion."""
        skill = self._skill(monkeypatch, min_relevance_threshold=0.35)
        ctx = _make_context(
            context_text="weak doc",
            max_rerank_prob=0.047,
            intent_confidence=0.4,
            rewrite_count=0,
            max_rewrites=3,
        )
        # rewrite_count(0) < max_rewrites(3) -> is_rewrite_limit_reached is False,
        # but v2 shunt still fires (decoupled).
        assert skill._should_fallback_or_refuse(ctx) == "fallback_general_chat"

    def test_missing_intent_confidence_defaults_to_refuse(self, monkeypatch):
        """[hot-path discipline] intent_confidence=None (unavailable) with weak
        docs -> refuse (conservative, don't fabricate). Unavailable != 0."""
        skill = self._skill(monkeypatch, min_relevance_threshold=0.35)
        ctx = _make_context(
            context_text="weak doc",
            max_rerank_prob=0.047,
            intent_confidence=None,  # not injected
        )
        assert skill._should_fallback_or_refuse(ctx) == "refuse"


# ===========================================================================
# execute/aexecute — the shunt branches
# ===========================================================================


class TestShuntExecution:
    """The shunt decision drives an early return in execute/aexecute."""

    def _skill(self, monkeypatch):
        import utils.env_utils as env
        from agent.skills.generate.skill import GenerateSkill

        monkeypatch.setattr(env, "LOW_INTENT_THRESHOLD", 0.5)
        return GenerateSkill()

    def test_fallback_branch_sets_sentinel(self, monkeypatch):
        """[REQ-RG-013b/F-04] The fallback branch MUST set
        shared_state['fallback_general_chat']=True as a SINGLE-KEY increment
        (not overwrite the whole shared_state)."""
        skill = self._skill(monkeypatch)
        ctx = _make_context(
            context_text="weak doc",
            max_rerank_prob=0.047,
            intent_confidence=0.4,
        )
        result = skill.execute(ctx)
        assert result.state_updates.get("shared_state", {}).get("fallback_general_chat") is True
        # Single-key increment: intent_confidence must NOT be clobbered.
        assert "intent_confidence" not in result.state_updates.get("shared_state", {})

    def test_refuse_branch_returns_refusal_message(self, monkeypatch):
        skill = self._skill(monkeypatch)
        ctx = _make_context(
            context_text="weak doc",
            max_rerank_prob=0.047,
            intent_confidence=0.8,
        )
        result = skill.execute(ctx)
        assert result.metadata.get("refused") is True
        assert result.messages[0].additional_kwargs.get("refused") is True

    def test_normal_generation_not_short_circuited(self, monkeypatch):
        """Strong docs must reach normal generation (the shunt returns None)."""
        skill = self._skill(monkeypatch)
        ctx = _make_context(
            context_text="strong relevant doc",
            max_rerank_prob=0.9,
            intent_confidence=0.4,
        )
        result = skill.execute(ctx)
        # Should NOT set the fallback sentinel.
        assert not result.state_updates.get("shared_state", {}).get("fallback_general_chat")
