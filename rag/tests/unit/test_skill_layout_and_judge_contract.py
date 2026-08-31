#!/usr/bin/env python3
"""
F15 — legacy skill shim files are gone; skills are directory-only.

Regression guard so the deleted flat `agent/skills/*_skill.py` shims do not get
reintroduced (they only re-exported the directory skills and were a source of
confusion). Also verifies the harness builds from the directory layout.

F17 — LLMJudge exposes a public entail/aentail contract (the grounding guardrail
no longer reaches into the underscore-private methods).

Run: pytest tests/unit/test_skill_layout_and_judge_contract.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")


# ===========================================================================
# F15
# ===========================================================================

_LEGACY_SHIMS = [
    "agent_skill.py",
    "retrieve_skill.py",
    "grade_skill.py",
    "rewrite_skill.py",
    "generate_skill.py",
    "intent_skill.py",
]


class TestNoLegacySkillShims:
    def test_legacy_shim_files_absent(self):
        skills_dir = Path("agent/skills")
        for shim in _LEGACY_SHIMS:
            assert not (skills_dir / shim).exists(), (
                f"legacy shim {shim} should be deleted; use the directory form"
            )

    def test_directory_skill_modules_exist(self):
        # IntentSkill is intentionally absent: intent classification lives in
        # the chat router (api/routers/chat.py via core/intent/classifier.py),
        # so it is not a graph skill. The remaining five are real graph skills.
        for name in ("agent", "retrieve", "grade", "rewrite", "generate"):
            assert (Path("agent/skills") / name / "skill.py").exists(), (
                f"directory skill agent/skills/{name}/skill.py missing"
            )

    def test_harness_builds_from_directory_layout(self):
        from agent.harness import get_agent_harness

        h = get_agent_harness()
        nodes = set(h.graph.nodes.keys())
        for expected in ("agent", "retrieve", "rewrite", "generate"):
            assert expected in nodes
        h.close()


# ===========================================================================
# F17
# ===========================================================================


class TestJudgePublicEntailmentContract:
    def test_public_entail_and_aentail_exist(self):
        from agent.eval.judge import LLMJudge

        assert callable(getattr(LLMJudge, "entail", None))
        assert callable(getattr(LLMJudge, "aentail", None))

    def test_grounding_guardrail_uses_public_contract(self):
        """The guardrail source must NOT call the underscore-private methods."""
        src = Path("agent/guardrails/grounding_guardrail.py").read_text(encoding="utf-8")
        assert "judge._entail(" not in src and "judge._aentail(" not in src, (
            "grounding guardrail must use judge.entail/aentail (public), not _entail/_aentail"
        )
        assert "judge.entail(" in src or "judge.aentail(" in src


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
