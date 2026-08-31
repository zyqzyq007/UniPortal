"""
Rewrite Skill

Wraps the existing RewriteNode logic as a skill.
Rewrites the user's question for better retrieval results,
then routes back to the agent node for another attempt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from agent.context.state import get_last_human_message
from agent.skills.base import BaseSkill, SkillContext, SkillResult, SkillStatus
from agent.skills.rewrite.prompts import REWRITE_PROMPT
from utils.log_utils import log
from utils.think_tag_utils import strip_think_tags

__all__ = ["RewriteSkill", "RewriteSkillConfig"]


@dataclass
class RewriteSkillConfig:
    """Configuration for RewriteSkill."""

    max_retries: int = 2
    retry_delay: float = 1.0
    rewrite_prompt: str = REWRITE_PROMPT
    preserve_original_on_failure: bool = True


class RewriteSkill(BaseSkill):
    """
    Skill that rewrites the user's question for better retrieval.

    Wraps RewriteNode from graph/rewrite_node.py:
    1. Extracts the original question from messages
    2. Uses the LLM to rewrite it for better search
    3. Returns the rewritten question and increments rewrite_count

    After rewriting, the orchestrator routes back to the agent node
    for another retrieval attempt.
    """

    name = "rewrite"
    description = "Rewrite the user's question for better retrieval"

    def __init__(
        self,
        config: RewriteSkillConfig | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._skill_config = config or RewriteSkillConfig()
        self._chain = None

    @property
    def chain(self):
        """Get the rewrite chain (lazy, cached)."""
        if self._chain is None:
            prompt = ChatPromptTemplate.from_template(self._skill_config.rewrite_prompt)
            self._chain = prompt | self.llm | StrOutputParser()
        return self._chain

    def execute(self, context: SkillContext) -> SkillResult:
        """Execute the rewrite skill synchronously."""
        start = time.perf_counter()
        messages = context.messages

        rewrite_count = context.rewrite_count
        max_rewrites = context.max_rewrites

        log.info(f"RewriteSkill: rewrite ({rewrite_count + 1}/{max_rewrites})")

        # Safety: check if we've exceeded max rewrites
        if rewrite_count >= max_rewrites:
            log.warning(f"RewriteSkill: max rewrites reached ({rewrite_count}/{max_rewrites})")
            return SkillResult(
                status=SkillStatus.SKIPPED,
                next_action="generate",
                state_updates={"rewrite_count": rewrite_count},
            )

        # Extract original question
        original_question = self._extract_question(messages)

        # REQ-CR-003: resolve coreferences using conversation history before rewrite.
        # E.g. "那第二条呢？" + history → "分析振动频率的具体步骤". No-op when no
        # history or no coreference markers (avoids extra LLM call).
        history = (context.shared_state or {}).get("conversation_history") or []
        if history:
            try:
                from core.retrieval.query_transform import condense_query

                original_question = condense_query(original_question, history)
            except Exception:  # noqa: BLE001 — degrade to original question
                pass

        # Rewrite with retry
        for attempt in range(self._skill_config.max_retries + 1):
            try:
                rewritten = self.chain.invoke({"original_question": original_question})
                rewritten = strip_think_tags(rewritten)

                elapsed = (time.perf_counter() - start) * 1000
                log.info(
                    f"RewriteSkill: '{original_question[:50]}...' -> "
                    f"'{rewritten[:50]}...', {elapsed:.0f}ms"
                )

                return SkillResult(
                    status=SkillStatus.SUCCESS,
                    messages=[HumanMessage(content=rewritten)],
                    state_updates={"rewrite_count": rewrite_count + 1},
                    next_action="agent",
                    metadata={
                        "original": original_question,
                        "rewritten": rewritten,
                        "elapsed_ms": elapsed,
                    },
                )

            except Exception as e:
                log.warning(f"Rewrite attempt {attempt + 1} failed: {e}")
                if attempt < self._skill_config.max_retries:
                    time.sleep(self._skill_config.retry_delay * (attempt + 1))
                else:
                    log.error(
                        f"RewriteSkill failed after {self._skill_config.max_retries + 1} attempts"
                    )

                    if self._skill_config.preserve_original_on_failure:
                        return SkillResult(
                            status=SkillStatus.PARTIAL,
                            messages=[HumanMessage(content=original_question)],
                            state_updates={"rewrite_count": rewrite_count + 1},
                            next_action="agent",
                            error=str(e),
                        )

                    return SkillResult(
                        status=SkillStatus.FAILURE,
                        messages=[AIMessage(content="查询重写失败，请重新提问。")],
                        state_updates={"rewrite_count": rewrite_count + 1},
                        next_action="generate",
                        error=str(e),
                    )

        # Should not reach here, but just in case
        return SkillResult(
            status=SkillStatus.PARTIAL,
            messages=[HumanMessage(content=original_question)],
            state_updates={"rewrite_count": rewrite_count + 1},
            next_action="agent",
        )

    async def aexecute(self, context: SkillContext) -> SkillResult:
        """Execute the rewrite skill asynchronously."""
        start = time.perf_counter()
        messages = context.messages

        rewrite_count = context.rewrite_count
        max_rewrites = context.max_rewrites

        if rewrite_count >= max_rewrites:
            return SkillResult(
                status=SkillStatus.SKIPPED,
                next_action="generate",
                state_updates={"rewrite_count": rewrite_count},
            )

        original_question = self._extract_question(messages)

        import asyncio

        for attempt in range(self._skill_config.max_retries + 1):
            try:
                rewritten = await self.chain.ainvoke({"original_question": original_question})
                rewritten = strip_think_tags(rewritten)

                elapsed = (time.perf_counter() - start) * 1000
                log.info(
                    f"RewriteSkill (async): '{original_question[:50]}...' -> "
                    f"'{rewritten[:50]}...', {elapsed:.0f}ms"
                )

                return SkillResult(
                    status=SkillStatus.SUCCESS,
                    messages=[HumanMessage(content=rewritten)],
                    state_updates={"rewrite_count": rewrite_count + 1},
                    next_action="agent",
                    metadata={
                        "original": original_question,
                        "rewritten": rewritten,
                        "elapsed_ms": elapsed,
                    },
                )

            except Exception as e:
                log.warning(f"Async rewrite attempt {attempt + 1} failed: {e}")
                if attempt < self._skill_config.max_retries:
                    await asyncio.sleep(self._skill_config.retry_delay * (attempt + 1))
                else:
                    if self._skill_config.preserve_original_on_failure:
                        return SkillResult(
                            status=SkillStatus.PARTIAL,
                            messages=[HumanMessage(content=original_question)],
                            state_updates={"rewrite_count": rewrite_count + 1},
                            next_action="agent",
                            error=str(e),
                        )
                    return SkillResult(
                        status=SkillStatus.FAILURE,
                        messages=[AIMessage(content="查询重写失败，请重新提问。")],
                        state_updates={"rewrite_count": rewrite_count + 1},
                        next_action="generate",
                        error=str(e),
                    )

        return SkillResult(
            status=SkillStatus.PARTIAL,
            messages=[HumanMessage(content=original_question)],
            state_updates={"rewrite_count": rewrite_count + 1},
            next_action="agent",
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_question(messages: list[BaseMessage]) -> str:
        """Extract the original question from messages."""
        try:
            return get_last_human_message(messages).content
        except Exception:
            return messages[-1].content if messages else ""
