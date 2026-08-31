#!/usr/bin/env python3
"""
F02 — grade conditional-edge two-channel state-leak guard.

``grade`` is wired as a LangGraph conditional edge, which can only return a
routing key — it cannot emit a state update. State is silently lost along TWO
channels: (1) a before-hook returning a ``shared_state`` increment for grade;
(2) GradeSkill putting ``state_updates``/``shared_state`` on its SkillResult.

The guard in ``AgentHarness._skill_to_conditional`` logs an error (never raises)
when either channel carries state, so the silent drop becomes a loud signal.

Run: pytest tests/unit/test_lifecycle_grade_guard.py -v
"""

from __future__ import annotations

import sys

import pytest
from loguru import logger

sys.path.insert(0, ".")


@pytest.fixture
def captured_logs():
    """Capture loguru records (loguru bypasses stdlib logging, so pytest's
    caplog cannot see it). We add an in-memory sink and yield the records."""
    records: list[str] = []

    def _sink(message):
        records.append(str(message))

    handler_id = logger.add(_sink, level="ERROR", format="{message}")
    try:
        yield records
    finally:
        logger.remove(handler_id)


def _grade_guard_message_present(records: list[str]) -> bool:
    return any("conditional-edge-guard" in r and "grade" in r for r in records)


def _build_grade_conditional():
    """Build the conditional function the orchestrator wires for grade, without
    needing the full LangGraph build. Returns (cond_fn, harness)."""
    from agent.harness.orchestrator import AgentHarness
    from agent.skills.base import BaseSkill, SkillContext, SkillResult, SkillStatus

    class _GradeStub(BaseSkill):
        name = "grade"
        description = "stub"

        def execute(self, context: SkillContext) -> SkillResult:
            return SkillResult(status=SkillStatus.SUCCESS, next_action="generate")

        async def aexecute(self, context: SkillContext) -> SkillResult:
            return SkillResult(status=SkillStatus.SUCCESS, next_action="generate")

    harness = AgentHarness()
    cond = harness._skill_to_conditional("grade", _GradeStub())
    # cond is a RunnableLambda; .func is the sync callable.
    return cond.func, harness


def _minimal_state():
    return {
        "messages": [],
        "rewrite_count": 0,
        "max_rewrites": 3,
        "shared_state": {},
    }


# ===========================================================================
# Channel 1 — before-hook returning shared_state for grade
# ===========================================================================


class TestGradeBeforeHookChannel:
    def test_before_hook_shared_state_is_logged_not_persisted(self, captured_logs):
        cond_fn, harness = _build_grade_conditional()

        def _leaky_hook(skill_name, context):
            if skill_name == "grade":
                return {"shared_state": {"relevance_scores": [0.1, 0.2]}}
            return None

        harness.lifecycle.on_before_skill(_leaky_hook, name="leaky")

        # The conditional fn returns only a routing key; the leaked increment
        # must NOT be in any returned structure, but it MUST be logged.
        routing = cond_fn(_minimal_state())

        assert routing == "generate"
        assert _grade_guard_message_present(captured_logs), (
            "before-hook shared_state leak must be logged"
        )


# ===========================================================================
# Channel 2 — GradeSkill returning state_updates/shared_state on its result
# ===========================================================================


class TestGradeSkillStateUpdatesChannel:
    def test_skill_state_updates_is_logged_not_persisted(self, captured_logs):
        from agent.harness.orchestrator import AgentHarness
        from agent.skills.base import (
            BaseSkill,
            SkillContext,
            SkillResult,
            SkillStatus,
        )

        class _LeakyGrade(BaseSkill):
            name = "grade"
            description = "stub that wrongly writes state"

            def execute(self, context: SkillContext) -> SkillResult:
                return SkillResult(
                    status=SkillStatus.SUCCESS,
                    next_action="generate",
                    state_updates={"shared_state": {"relevance_scores": [0.9]}},
                )

            async def aexecute(self, context: SkillContext) -> SkillResult:
                return self.execute(context)

        harness = AgentHarness()
        cond = harness._skill_to_conditional("grade", _LeakyGrade())
        cond_fn = cond.func

        routing = cond_fn(_minimal_state())

        assert routing == "generate"
        assert any("conditional-edge-guard" in r and "state_updates" in r for r in captured_logs), (
            "skill state_updates leak must be logged"
        )


# ===========================================================================
# Negative — a clean grade skill (no state on either channel) logs nothing
# ===========================================================================


class TestGradeGuardNoFalsePositive:
    def test_clean_grade_skill_logs_nothing(self, captured_logs):
        cond_fn, _ = _build_grade_conditional()
        routing = cond_fn(_minimal_state())
        assert routing == "generate"
        assert not _grade_guard_message_present(captured_logs)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
