#!/usr/bin/env python3
"""
Layer ① — Profile-driven capability/identity detection tests.

Bug2 root-cause layer 1: '你能解决什么问题' (what problems can you solve) is a
general capability question but bypassed the hardcoded identity regex
(api/routers/chat.py:340-356) because the regex only covered 你能做什么/你会什么.
The fix moves detection into the domain profile (capability_keywords +
capability_patterns), satisfying domain_profile.py:9 "源码不再出现领域字面量".

Also covers F-13 (yaml prompts.intent anti-drift): from_dict does prompt-key-
level shallow merge, so every shipped yaml's intent prompt must carry the
capability-rule marker or Layer ③ silently regresses.

Run: uv run --frozen python -m pytest tests/unit/test_capability_detection.py -v
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
# Profile field loading
# ===========================================================================


class TestProfileCapabilityFields:
    def test_general_defaults_define_capability_fields(self):
        """[REQ-RG-001] _general_defaults() MUST populate capability_keywords
        and capability_patterns so detection is profile-driven, not hardcoded."""
        from core.prompts.domain_profile import _general_defaults

        defaults = _general_defaults()
        assert "capability_keywords" in defaults
        assert "capability_patterns" in defaults
        assert isinstance(defaults["capability_keywords"], list)
        assert isinstance(defaults["capability_patterns"], list)
        assert len(defaults["capability_keywords"]) > 0
        assert len(defaults["capability_patterns"]) > 0

    def test_general_profile_carries_capability_fields(self):
        """[REQ-RG-001] The general DomainProfile exposes the new fields."""
        from core.prompts.domain_profile import DomainProfile

        profile = DomainProfile.general()
        assert hasattr(profile, "capability_keywords")
        assert hasattr(profile, "capability_patterns")
        assert len(profile.capability_keywords) > 0
        assert len(profile.capability_patterns) > 0

    def test_shipped_yaml_profiles_define_capability_fields(self):
        """[REQ-RG-001] Shipped profiles carry capability fields.

        Note: data/profiles/ is gitignored (runtime/local customization); the
        committed source of truth is _general_defaults(). Locally-present yamls
        (if any) are validated; when absent, defaults are asserted directly.
        """
        import glob

        yaml_files = glob.glob("data/profiles/*.yaml")
        if not yaml_files:
            # No local yamls — defaults ARE the shipped config.
            from core.prompts.domain_profile import _general_defaults

            d = _general_defaults()
            assert d["capability_keywords"], "defaults must define capability_keywords"
            assert d["capability_patterns"], "defaults must define capability_patterns"
            return
        # Local yamls present (dev/customization): each that defines the fields
        # must define them as non-empty lists.
        import os

        from core.prompts.domain_profile import load_domain_profile

        for path in yaml_files:
            assert os.path.exists(path)
            name = os.path.splitext(os.path.basename(path))[0]
            profile = load_domain_profile(name)
            assert profile.capability_keywords, f"{name}: capability_keywords empty"


# ===========================================================================
# Detection — _is_identity_capability_query reads profile
# ===========================================================================


class TestIdentityCapabilityDetection:
    """[REQ-RG-002] _is_identity_capability_query MUST read the active profile's
    capability_keywords + capability_patterns instead of a hardcoded regex list."""

    @pytest.mark.parametrize(
        "query",
        [
            "你是谁",
            "你能做什么",
            "你会什么",
            "你能解决什么问题",  # the exact bug trigger — NOT in v1 regex
            "你能帮我解决什么",
            "你能处理哪些任务",
            "介绍一下你自己",
            "who are you",
            "what can you do",
        ],
    )
    def test_capability_queries_detected(self, query):
        from api.routers.chat import _is_identity_capability_query

        assert _is_identity_capability_query(query) is True, (
            f"capability query {query!r} must be detected"
        )

    @pytest.mark.parametrize(
        "query",
        [
            "如何排查发动机故障",
            "什么是关系型数据库",
            "Git 合并冲突怎么解决",
            "请帮我查询昨天的订单",
        ],
    )
    def test_non_capability_queries_not_detected(self, query):
        """Genuine domain/RAG queries must NOT trip the capability shortcut."""
        from api.routers.chat import _is_identity_capability_query

        assert _is_identity_capability_query(query) is False, (
            f"non-capability query {query!r} must not be detected as capability"
        )

    def test_detection_source_is_profile_not_hardcoded(self):
        """[REQ-RG-002] Detection MUST be driven by the profile — switching the
        active profile's capability fields changes detection results."""
        import core.prompts.domain_profile as dp_mod
        from api.routers.chat import _is_identity_capability_query
        from core.prompts.domain_profile import DomainProfile

        # A profile with NO capability fields detects nothing.
        empty_profile = DomainProfile.general()
        empty_profile.capability_keywords = []
        empty_profile.capability_patterns = []
        original = dp_mod._active_profile
        dp_mod._active_profile = empty_profile
        try:
            assert _is_identity_capability_query("你能解决什么问题") is False
        finally:
            dp_mod._active_profile = original


# ===========================================================================
# F-13 — yaml prompts.intent anti-drift
# (Moved to tests/unit/test_intent_prompt_rules.py under Layer ③, since the
# rule text is added in Layer ③. Kept here as a marker for traceability.)
# ===========================================================================
