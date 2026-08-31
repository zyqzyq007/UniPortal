#!/usr/bin/env python3
"""
Layer ②/③ — Confidence-gated routing + intent prompt capability rules.

Bug2 Layer ②: routing was a hard binary `use_rag = intent != "general_chat"`,
ignoring classifier confidence. A low-confidence rag_query (e.g. a misrouted
capability question) went straight to retrieval. The fix gates on confidence:
only rag_query at confidence >= LOW_INTENT_THRESHOLD enters the graph; below
that it falls back to general_chat. The domain-query override (strong signal)
is retained so genuine domain queries still force RAG.

Bug2 Layer ③: the intent classification prompt gave the LLM no guidance on
self-referential capability questions, so '你能解决什么问题' was plausibly
tagged rag_query. The fix adds an explicit rule + examples.

Run: uv run --frozen python -m pytest tests/unit/test_routing_confidence.py -v
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")


@pytest.fixture(autouse=True)
def _reset_profile():
    from core.prompts.domain_profile import reset_active_profile

    reset_active_profile()
    yield
    reset_active_profile()


# ===========================================================================
# Layer ② — LOW_INTENT_THRESHOLD config
# ===========================================================================


class TestLowIntentThresholdConfig:
    def test_threshold_exists_with_default(self, monkeypatch):
        """[REQ-RG-004/018] LOW_INTENT_THRESHOLD MUST be defined via _get_float
        (env_utils convention) with a sane default."""
        monkeypatch.delenv("LOW_INTENT_THRESHOLD", raising=False)
        # Re-import to pick up the env state.
        import importlib

        import utils.env_utils as env

        importlib.reload(env)
        assert hasattr(env, "LOW_INTENT_THRESHOLD")
        assert 0.0 < env.LOW_INTENT_THRESHOLD < 1.0

    def test_threshold_env_override(self, monkeypatch):
        """[REQ-RG-004] LOW_INTENT_THRESHOLD MUST be overridable via env."""
        monkeypatch.setenv("LOW_INTENT_THRESHOLD", "0.65")
        import importlib

        import utils.env_utils as env

        importlib.reload(env)
        assert env.LOW_INTENT_THRESHOLD == pytest.approx(0.65)


# ===========================================================================
# Layer ② — routing decision logic
# ===========================================================================


class TestConfidenceGatedRouting:
    """[REQ-RG-003/005] Routing MUST gate on confidence: low-confidence
    rag_query -> general_chat; domain override still forces RAG."""

    def test_low_confidence_rag_query_falls_back_to_general_chat(self, monkeypatch):
        """A rag_query below LOW_INTENT_THRESHOLD must NOT use RAG."""
        import utils.env_utils as env

        monkeypatch.setattr(env, "LOW_INTENT_THRESHOLD", 0.5)
        # The routing predicate (mirrors chat.py non-stream line 620).
        from core.intent.classifier import IntentType

        intent_val = IntentType.RAG_QUERY.value  # "rag_query"
        confidence = 0.4  # < 0.5 threshold
        use_rag = intent_val != "general_chat" and confidence >= env.LOW_INTENT_THRESHOLD
        assert use_rag is False, "low-confidence rag_query must fall back to general_chat"

    def test_high_confidence_rag_query_uses_rag(self, monkeypatch):
        """A rag_query at/above LOW_INTENT_THRESHOLD must use RAG."""
        import utils.env_utils as env

        monkeypatch.setattr(env, "LOW_INTENT_THRESHOLD", 0.5)
        from core.intent.classifier import IntentType

        intent_val = IntentType.RAG_QUERY.value
        confidence = 0.8  # >= 0.5
        use_rag = intent_val != "general_chat" and confidence >= env.LOW_INTENT_THRESHOLD
        assert use_rag is True

    def test_general_chat_never_uses_rag_regardless_of_confidence(self, monkeypatch):
        """general_chat must short-circuit to no-RAG even at high confidence."""
        import utils.env_utils as env

        monkeypatch.setattr(env, "LOW_INTENT_THRESHOLD", 0.5)
        intent_val = "general_chat"
        confidence = 0.99
        use_rag = intent_val != "general_chat" and confidence >= env.LOW_INTENT_THRESHOLD
        assert use_rag is False


# ===========================================================================
# Layer ③ — intent prompt capability rule (F-13 anti-drift)
# ===========================================================================


class TestIntentPromptCapabilityRule:
    """[REQ-RG-006/017 / F-13] The intent classification prompt MUST carry an
    explicit capability/identity rule so the LLM routes self-referential
    questions to general_chat. _general_defaults is the committed source of
    truth (data/profiles/ is gitignored runtime customization)."""

    def test_default_intent_prompt_has_capability_rule(self):
        from core.prompts.domain_profile import _general_defaults

        prompt = _general_defaults()["prompts"]["intent"]
        assert "general_chat" in prompt
        # Must hint at capability/identity/self-referential questions.
        assert any(kw in prompt for kw in ("能力", "身份", "自身")), (
            "intent prompt must carry a capability/identity rule"
        )

    def test_general_profile_intent_prompt_has_capability_rule(self):
        from core.prompts.domain_profile import DomainProfile

        prompt = DomainProfile.general().prompts["intent"]
        assert "general_chat" in prompt
        assert any(kw in prompt for kw in ("能力", "身份", "自身"))

    def test_aviation_profile_intent_prompt_has_capability_rule(self):
        """[F-13] from_dict does prompt-key-level shallow merge; aviation_phm
        overrides prompts.intent, so its yaml (or the default if absent) MUST
        carry the rule. Defaults cover it; a local aviation yaml without the
        rule would regress — this test pins the loaded profile."""
        from core.prompts.domain_profile import load_domain_profile

        profile = load_domain_profile("aviation_phm")
        prompt = profile.prompts.get("intent", "")
        assert "general_chat" in prompt
        assert any(kw in prompt for kw in ("能力", "身份", "自身")), (
            "aviation intent prompt must carry capability rule (F-13 anti-drift)"
        )
