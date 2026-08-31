#!/usr/bin/env python3
"""
REQ-RC-001/002/003/004 — grade yes-default + agent tool-call fallback regression.

Guards Stage C faithfulness fixes:
- Grade.binary_score defaults to "no" (was "yes" -> irrelevant docs passed through)
- _parse_relevance uses known keys, not whole-string substring match
- AgentSkill nudges a retry when the LLM returns no tool_calls (bypass fix)

Run: pytest tests/unit/test_grade_schema.py -v
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")


# ===========================================================================
# REQ-RC-001 — Grade defaults to "no" (conservative)
# ===========================================================================


class TestGradeYesDefault:
    def test_grade_defaults_conservative(self):
        """Grade() with no args MUST be conservative (not relevant), so an
        unrecognised LLM key biases toward rewrite, not hallucination.
        binary_score is None by default (F-05: lets the answer field work)."""
        from agent.context.state import Grade

        g = Grade()
        assert g.binary_score is None
        assert g.is_relevant is False

    def test_answer_field_works_when_binary_score_unset(self):
        """F-05 regression: Qwen3 may return only {'answer': 'yes'}; the answer
        field MUST be honoured when binary_score is unset (was short-circuited
        by a non-empty default)."""
        from agent.context.state import Grade

        assert Grade(answer="yes").is_relevant is True
        assert Grade(answer="no").is_relevant is False

    def test_explicit_yes_still_works(self):
        from agent.context.state import Grade

        assert Grade(binary_score="yes").is_relevant is True


# ===========================================================================
# REQ-RC-003 — _parse_relevance robust to unknown keys
# ===========================================================================


class TestParseRelevance:
    def test_unknown_key_dict_is_not_relevant(self):
        """A dict with an unrecognised key MUST be 'not relevant' (conservative),
        not fall through to a yes-default (old bug)."""
        from agent.skills.grade.skill import GradeSkill

        assert GradeSkill._parse_relevance({"unknown_key": "something"}) is False

    def test_score_no_is_not_relevant(self):
        from agent.skills.grade.skill import GradeSkill

        assert GradeSkill._parse_relevance({"score": "no"}) is False

    def test_not_relevant_not_mismatched_as_relevant(self):
        """Old bug: whole-string substring match let {"score":"not relevant"}
        through because it contains "relevant"."""
        from agent.skills.grade.skill import GradeSkill

        assert GradeSkill._parse_relevance({"score": "not relevant"}) is False
        assert GradeSkill._parse_relevance({"relevant": "false"}) is False

    def test_known_yes_keys_are_relevant(self):
        from agent.skills.grade.skill import GradeSkill

        assert GradeSkill._parse_relevance({"binary_score": "yes"}) is True
        assert GradeSkill._parse_relevance({"answer": "yes"}) is True
        assert GradeSkill._parse_relevance({"relevant": "true"}) is True


# ===========================================================================
# REQ-RC-004 — AgentSkill nudges on missing tool_calls
# ===========================================================================


class TestAgentNoToolCallFallback:
    def test_agent_nudges_when_no_tool_calls(self, monkeypatch):
        """When the LLM answers without a tool_call, AgentSkill MUST nudge a
        retry (the direct answer would bypass retrieval/grounding/refusal)."""
        from langchain_core.messages import HumanMessage

        from agent.skills.agent.skill import AgentSkill
        from agent.skills.base import SkillContext

        class _FakeResp:
            def __init__(self, content, tool_calls=None):
                self.content = content
                self.tool_calls = tool_calls or []

        state = {"calls": 0}

        def _fake_invoke(messages):
            state["calls"] += 1
            if state["calls"] == 1:
                return _FakeResp("我直接回答不检索")
            return _FakeResp("检索中", tool_calls=[{"name": "rag_retriever", "args": {}}])

        skill = AgentSkill()
        skill._invoke_model = _fake_invoke  # instance-level override

        ctx = SkillContext(messages=[HumanMessage(content="服务异常")], shared_state={})
        result = skill.execute(ctx)
        assert state["calls"] == 2, f"expected 2 invokes (nudge retry), got {state['calls']}"
        assert result.metadata.get("no_tool_call_nudged", 0) >= 1

    def test_agent_does_not_nudge_when_tool_calls_present(self, monkeypatch):
        from langchain_core.messages import HumanMessage

        from agent.skills.agent.skill import AgentSkill
        from agent.skills.base import SkillContext

        calls = []

        class _FakeResp:
            def __init__(self):
                self.content = "检索结果"
                self.tool_calls = [{"name": "rag_retriever", "args": {"query": "x"}}]

        def _fake_invoke(messages):
            calls.append(1)
            return _FakeResp()

        skill = AgentSkill()
        monkeypatch.setattr(skill, "_invoke_model", _fake_invoke)
        ctx = SkillContext(messages=[HumanMessage(content="x")], shared_state={})
        skill.execute(ctx)
        assert len(calls) == 1, "should not nudge when tool_calls present"
