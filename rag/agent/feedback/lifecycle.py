from __future__ import annotations

from collections.abc import Callable

from agent.feedback.escalation import get_escalation_manager
from agent.feedback.types import EscalationLevel
from agent.skills.base import SkillContext, SkillResult
from utils.log_utils import log


def create_escalation_hook() -> Callable:
    def after_generate(skill_name: str, context: SkillContext, result: SkillResult):
        if skill_name != "generate":
            return
        try:
            answer = ""
            if result.messages:
                answer = result.messages[-1].content if result.messages else ""

            metadata = {
                "has_reasoning": result.metadata.get("has_reasoning", True),
                "answer_length": len(answer),
                "has_sources": result.metadata.get("has_sources", True),
                "hallucination_flag": result.metadata.get("hallucination_flag", False),
            }

            manager = get_escalation_manager()
            level = manager.assess_confidence(metadata)

            if level in (EscalationLevel.HIGH, EscalationLevel.CRITICAL):
                manager.create_escalation(
                    level=level,
                    session_id=context.session_id,
                    answer=answer,
                    context=result.metadata,
                )
                warning = f"\n\n[系统提示: 回答置信度较低({level.value})，已记录待人工审核]"
                if result.messages:
                    from langchain_core.messages import AIMessage

                    last_msg = result.messages[-1]
                    if isinstance(last_msg, AIMessage):
                        result.messages[-1] = AIMessage(content=last_msg.content + warning)
        except Exception as e:
            log.warning(f"Escalation hook failed: {e}")

    return after_generate
