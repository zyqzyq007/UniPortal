"""
Grade Skill

Wraps the grading logic from graph/graph.py create_grade_function().
Evaluates whether retrieved documents are relevant to the user's question.

This skill acts as a conditional router in the graph:
- Relevant -> next_action = "generate"
- Not relevant -> next_action = "rewrite"
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from langchain_core.prompts import ChatPromptTemplate

from agent.context.state import Grade, get_last_human_message
from agent.skills.base import BaseSkill, SkillContext, SkillResult, SkillStatus
from agent.skills.grade.prompts import GRADE_HUMAN_PROMPT, GRADE_SYSTEM_PROMPT
from utils.log_utils import log

__all__ = ["GradeSkill", "GradeSkillConfig"]


@dataclass
class GradeSkillConfig:
    """Configuration for GradeSkill."""

    grade_system_prompt: str = GRADE_SYSTEM_PROMPT
    grade_human_prompt: str = GRADE_HUMAN_PROMPT
    max_retries: int = 2
    retry_delay: float = 1.0


class GradeSkill(BaseSkill):
    """
    Skill that grades retrieved documents for relevance.

    Wraps the grading logic from graph/graph.py:
    1. Extracts the question and retrieved context from messages
    2. Uses structured LLM output (Grade pydantic model) to classify
    3. Returns next_action: "generate" or "rewrite"

    This skill produces no new messages -- it only sets next_action
    for the orchestrator to route to the correct next node.
    """

    name = "grade"
    description = "Grade retrieved documents for relevance to the question"

    def __init__(
        self,
        config: GradeSkillConfig | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._skill_config = config or GradeSkillConfig()
        self._chain = None

    @property
    def chain(self):
        """Get the grading chain (lazy, cached)."""
        if self._chain is None:
            llm_with_structured = self.llm.with_structured_output(Grade, method="json_mode")
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", self._skill_config.grade_system_prompt),
                    ("human", self._skill_config.grade_human_prompt),
                ]
            )
            self._chain = prompt | llm_with_structured
        return self._chain

    def execute(self, context: SkillContext) -> SkillResult:
        """Grade documents synchronously."""
        start = time.perf_counter()
        messages = context.messages

        # Check rewrite limit first
        if context.is_rewrite_limit_reached:
            log.warning(
                f"GradeSkill: rewrite limit reached "
                f"({context.rewrite_count}/{context.max_rewrites}), forcing generate"
            )
            return SkillResult(
                status=SkillStatus.SUCCESS,
                next_action="generate",
                metadata={"forced": True},
            )

        try:
            question, context_text = self._extract_inputs(messages)
            is_relevant = self._grade(question, context_text)

            elapsed = (time.perf_counter() - start) * 1000
            next_action = "generate" if is_relevant else "rewrite"

            log.info(f"GradeSkill: relevant={is_relevant}, next={next_action}, {elapsed:.0f}ms")

            return SkillResult(
                status=SkillStatus.SUCCESS,
                next_action=next_action,
                metadata={
                    "is_relevant": is_relevant,
                    "elapsed_ms": elapsed,
                },
            )

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            log.error(f"GradeSkill failed ({elapsed:.0f}ms): {e}")

            # On failure, default to rewrite (unless limit reached)
            if context.is_rewrite_limit_reached:
                next_action = "generate"
            else:
                next_action = "rewrite"

            return SkillResult(
                status=SkillStatus.PARTIAL,
                next_action=next_action,
                error=str(e),
                metadata={"elapsed_ms": elapsed, "fallback": True},
            )

    async def aexecute(self, context: SkillContext) -> SkillResult:
        """Grade documents asynchronously."""
        start = time.perf_counter()
        messages = context.messages

        # Check rewrite limit
        if context.is_rewrite_limit_reached:
            return SkillResult(
                status=SkillStatus.SUCCESS,
                next_action="generate",
                metadata={"forced": True},
            )

        try:
            question, context_text = self._extract_inputs(messages)
            is_relevant = await self._agrade(question, context_text)

            elapsed = (time.perf_counter() - start) * 1000
            next_action = "generate" if is_relevant else "rewrite"

            log.info(
                f"GradeSkill (async): relevant={is_relevant}, next={next_action}, {elapsed:.0f}ms"
            )

            return SkillResult(
                status=SkillStatus.SUCCESS,
                next_action=next_action,
                metadata={
                    "is_relevant": is_relevant,
                    "elapsed_ms": elapsed,
                },
            )

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            log.error(f"GradeSkill async failed ({elapsed:.0f}ms): {e}")

            if context.is_rewrite_limit_reached:
                next_action = "generate"
            else:
                next_action = "rewrite"

            return SkillResult(
                status=SkillStatus.PARTIAL,
                next_action=next_action,
                error=str(e),
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _extract_inputs(self, messages: list) -> tuple:
        """Extract question and context from messages."""
        try:
            question = get_last_human_message(messages).content
        except Exception:
            question = messages[-1].content if messages else ""

        # Context is in the last message (from retriever / ToolNode)
        last_message = messages[-1] if messages else None
        context_text = ""
        if last_message is not None:
            content = last_message.content
            if isinstance(content, list):
                # Tool result format
                parts = []
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        parts.append(item["text"])
                    elif isinstance(item, str):
                        parts.append(item)
                context_text = "\n\n".join(parts)
            else:
                context_text = str(content)

        return question, context_text

    def _grade(self, question: str, context: str) -> bool:
        """
        Grade documents for relevance.

        Returns True if relevant, False otherwise.
        """
        for attempt in range(self._skill_config.max_retries + 1):
            try:
                from core.retrieval.evidence import render_untrusted_text

                result = self.chain.invoke(
                    {
                        "question": question,
                        "context": render_untrusted_text(context),
                    }
                )

                return self._parse_relevance(result)

            except Exception as e:
                log.warning(f"Grade attempt {attempt + 1} failed: {e}")
                if attempt < self._skill_config.max_retries:
                    time.sleep(self._skill_config.retry_delay * (attempt + 1))

        # Default to relevant on repeated failure (prefer generating over looping)
        return True

    async def _agrade(self, question: str, context: str) -> bool:
        """Grade documents asynchronously."""
        import asyncio

        for attempt in range(self._skill_config.max_retries + 1):
            try:
                from core.retrieval.evidence import render_untrusted_text

                result = await self.chain.ainvoke(
                    {
                        "question": question,
                        "context": render_untrusted_text(context),
                    }
                )
                return self._parse_relevance(result)

            except Exception as e:
                log.warning(f"Async grade attempt {attempt + 1} failed: {e}")
                if attempt < self._skill_config.max_retries:
                    await asyncio.sleep(self._skill_config.retry_delay * (attempt + 1))

        return True

    @staticmethod
    def _parse_relevance(result) -> bool:
        """
        Parse the grading result.

        Handles:
        - Grade pydantic model
        - dict (from non-standard JSON mode output)
        - Raw string

        Conservative default: when the LLM returns an unrecognised key, treat as
        NOT relevant (Grade.binary_score now defaults to "no") rather than the
        old yes-default that let irrelevant docs through to generate.
        """
        if isinstance(result, Grade):
            return result.is_relevant
        elif isinstance(result, dict):
            # Extract from known keys; do NOT whole-string substring-match
            # ("not relevant" contains "relevant" -> old false-positive bug).
            for key in ("binary_score", "score", "answer", "relevant", "relevance"):
                val = str(result.get(key, "")).strip().lower()
                if val in ("no", "false", "not relevant", "irrelevant", "0"):
                    return False
                if val in ("yes", "true", "relevant", "1"):
                    return True
            # No recognised key -> conservative not relevant (was yes-default).
            return False
        else:
            return "yes" in str(result).lower()
