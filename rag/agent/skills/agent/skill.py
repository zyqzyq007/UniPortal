"""
Agent Skill

Wraps the existing AgentNode logic as a skill.
Decides whether to call retrieval tools or respond directly.
Uses MCPClient for tool binding when available, falls back to
the existing get_retriever_tool().
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from agent.skills.agent.prompts import AGENT_SYSTEM_PROMPT
from agent.skills.base import BaseSkill, SkillContext, SkillResult, SkillStatus
from utils.log_utils import log

__all__ = ["AgentSkill", "AgentSkillConfig"]


@dataclass
class AgentSkillConfig:
    """Configuration for AgentSkill."""

    max_retries: int = 2
    retry_delay: float = 1.0
    system_prompt: str | None = None
    message_window: int = 10


class AgentSkill(BaseSkill):
    """
    Skill that wraps the agent decision node.

    Binds retrieval tools to the LLM and lets the model decide
    whether to call a tool or respond directly. This mirrors
    AgentNode from graph/agent_node.py.
    """

    name = "agent"
    description = "Agent decision node: decides tool usage vs direct response"

    def __init__(
        self,
        config: AgentSkillConfig | None = None,
        tools: list[BaseTool] | None = None,
        mcp_client: Any | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._skill_config = config or AgentSkillConfig()
        self._tools = tools
        self._mcp_client = mcp_client
        self._bound_model = None

    @property
    def tools(self) -> list[BaseTool]:
        """Get tools (lazy initialization)."""
        if self._tools is None:
            if self._mcp_client is not None:
                self._tools = self._mcp_client.get_all_tools_as_langchain()
            if not self._tools:
                # Fallback to existing retriever tool
                from agent.mcp.retriever_tools import get_retriever_tool

                self._tools = [get_retriever_tool()]
        return self._tools

    @property
    def bound_model(self):
        """Get model with tools bound (lazy, cached)."""
        if self._bound_model is None:
            self._bound_model = self.llm.bind_tools(self.tools)
        return self._bound_model

    def execute(self, context: SkillContext) -> SkillResult:
        """Execute the agent skill synchronously."""
        start = time.perf_counter()
        messages = context.messages

        rewrite_count = context.rewrite_count
        max_rewrites = context.max_rewrites

        last_message = messages[-1] if messages else None
        if last_message is None:
            return SkillResult(
                status=SkillStatus.FAILURE,
                skill_name=self.name,
                error="No messages in context",
                messages=[AIMessage(content="请输入您的问题。")],
            )

        log.info(f"AgentSkill: messages={len(messages)}, rewrites={rewrite_count}/{max_rewrites}")

        # Invoke with retry
        no_tool_call_retries = 0
        max_no_tool_call_retries = 1  # one nudge, then give up (avoid loops)
        for attempt in range(self._skill_config.max_retries + 1):
            try:
                response = self._invoke_model(messages)
                elapsed = (time.perf_counter() - start) * 1000

                # Guard (Stage C, REQ-RC-004): if the LLM answered directly
                # without a tool_call, the answer bypasses retrieval/grounding/
                # refusal (tools_condition routes straight to END, and the output
                # guardrail skips non-generate nodes). Nudge it to retrieve once.
                tool_calls = getattr(response, "tool_calls", None) or []
                content = (getattr(response, "content", "") or "").strip()
                if not tool_calls and content and no_tool_call_retries < max_no_tool_call_retries:
                    no_tool_call_retries += 1
                    log.warning(
                        "AgentSkill: LLM returned no tool_calls (direct answer); "
                        "nudging to retrieve (attempt %d)",
                        no_tool_call_retries,
                    )
                    messages = list(messages) + [
                        response,
                        HumanMessage(content="请使用检索工具(rag_retriever)查询相关文档后再回答。"),
                    ]
                    continue

                # Nudge exhausted but still no tool_call: do NOT pass through the
                # LLM's direct answer — it skipped retrieval/grounding/refusal and
                # the output guardrail won't catch it (non-generate node). Return a
                # safe nudge instead so the unverified answer is never shown as-is
                # (critic F-RC-02: was `return SUCCESS(response)`).
                if not tool_calls and content and no_tool_call_retries >= max_no_tool_call_retries:
                    log.warning(
                        "AgentSkill: no tool_calls after %d nudge(s); returning safe "
                        "nudge instead of an unverified direct answer",
                        no_tool_call_retries,
                    )
                    return SkillResult(
                        status=SkillStatus.SUCCESS,
                        messages=[
                            AIMessage(
                                content="我需要先检索相关文档才能准确回答您的问题。请稍候，正在为您检索知识库中的相关内容。"
                            )
                        ],
                        metadata={
                            "attempt": attempt,
                            "elapsed_ms": elapsed,
                            "no_tool_call_nudged": no_tool_call_retries,
                            "no_tool_call_unrecovered": True,
                        },
                    )

                return SkillResult(
                    status=SkillStatus.SUCCESS,
                    messages=[response],
                    metadata={
                        "attempt": attempt,
                        "elapsed_ms": elapsed,
                        "no_tool_call_nudged": no_tool_call_retries,
                    },
                )

            except Exception as e:
                error_str = str(e)
                log.warning(f"AgentSkill attempt {attempt + 1} failed: {e}")

                # Handle rate limiting (429)
                if "429" in error_str or "rate limit" in error_str.lower():
                    wait_match = re.search(r"wait[:\s]+(\d+)\s*seconds", error_str, re.IGNORECASE)
                    wait_time = int(wait_match.group(1)) if wait_match else 60

                    if attempt < self._skill_config.max_retries:
                        time.sleep(min(wait_time, 30))
                    else:
                        return SkillResult(
                            status=SkillStatus.FAILURE,
                            skill_name=self.name,
                            error=f"Rate limited: wait {wait_time}s",
                            messages=[
                                AIMessage(
                                    content=f"API请求频率受限，请等待约 {wait_time} 秒后再试。"
                                )
                            ],
                        )
                elif attempt < self._skill_config.max_retries:
                    time.sleep(self._skill_config.retry_delay * (attempt + 1))
                else:
                    return SkillResult(
                        status=SkillStatus.FAILURE,
                        skill_name=self.name,
                        error=str(e),
                        messages=[AIMessage(content="抱歉，处理您的请求时遇到问题，请稍后重试。")],
                    )

        return SkillResult(
            status=SkillStatus.FAILURE,
            skill_name=self.name,
            messages=[AIMessage(content="处理请求失败。")],
        )

    async def aexecute(self, context: SkillContext) -> SkillResult:
        """Execute the agent skill asynchronously."""
        start = time.perf_counter()
        messages = context.messages

        last_message = messages[-1] if messages else None
        if last_message is None:
            return SkillResult(
                status=SkillStatus.FAILURE,
                skill_name=self.name,
                error="No messages in context",
                messages=[AIMessage(content="请输入您的问题。")],
            )

        try:
            response = await self._ainvoke_model(messages)
            elapsed = (time.perf_counter() - start) * 1000

            # Guard (Stage C, REQ-RC-004): nudge once if the LLM answered
            # directly without a tool_call (bypasses retrieval/grounding).
            tool_calls = getattr(response, "tool_calls", None) or []
            content = (getattr(response, "content", "") or "").strip()
            nudged = False
            if not tool_calls and content:
                log.warning("AgentSkill async: no tool_calls; nudging to retrieve")
                nudged = True
                nudged_msgs = list(messages) + [
                    response,
                    HumanMessage(content="请使用检索工具(rag_retriever)查询相关文档后再回答。"),
                ]
                response = await self._ainvoke_model(nudged_msgs)
                elapsed = (time.perf_counter() - start) * 1000
                # After nudge, if STILL no tool_call, do not pass the direct answer
                # through (critic F-RC-02). Return a safe nudge instead.
                if not (getattr(response, "tool_calls", None) or []):
                    log.warning("AgentSkill async: no tool_calls after nudge; safe nudge")
                    return SkillResult(
                        status=SkillStatus.SUCCESS,
                        messages=[
                            AIMessage(
                                content="我需要先检索相关文档才能准确回答您的问题。请稍候，正在为您检索知识库中的相关内容。"
                            )
                        ],
                        metadata={
                            "elapsed_ms": elapsed,
                            "no_tool_call_nudged": nudged,
                            "no_tool_call_unrecovered": True,
                        },
                    )

            return SkillResult(
                status=SkillStatus.SUCCESS,
                messages=[response],
                metadata={"elapsed_ms": elapsed, "no_tool_call_nudged": nudged},
            )

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            log.error(f"AgentSkill async failed ({elapsed:.0f}ms): {e}")
            return SkillResult(
                status=SkillStatus.FAILURE,
                skill_name=self.name,
                error=str(e),
                messages=[AIMessage(content="抱歉，处理您的请求时遇到问题，请稍后重试。")],
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _invoke_model(self, messages: list[BaseMessage]) -> AIMessage:
        """Invoke the model with system prompt and message window."""
        window = self._skill_config.message_window
        recent = messages[-window:] if len(messages) > window else messages

        system_prompt = self._skill_config.system_prompt or AGENT_SYSTEM_PROMPT
        system_msg = SystemMessage(content=system_prompt)
        recent_with_system = [system_msg] + recent

        response = self.bound_model.invoke(recent_with_system)
        log.debug(f"AgentSkill response type: {type(response).__name__}")
        return response

    async def _ainvoke_model(self, messages: list[BaseMessage]) -> AIMessage:
        """Async model invocation."""
        window = self._skill_config.message_window
        recent = messages[-window:] if len(messages) > window else messages

        system_prompt = self._skill_config.system_prompt or AGENT_SYSTEM_PROMPT
        system_msg = SystemMessage(content=system_prompt)
        recent_with_system = [system_msg] + recent

        response = await self.bound_model.ainvoke(recent_with_system)
        return response
