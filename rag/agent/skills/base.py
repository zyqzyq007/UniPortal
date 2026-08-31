"""
Skill Base Classes and Types

Defines the core abstractions for the Skill system:
- BaseSkill: Abstract base class for all agent skills
- SkillContext: Rich context passed to every skill execution
- SkillResult: Standardized result from any skill execution
- SkillStatus: Status enum for skill execution outcomes
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage

from utils.log_utils import log

__all__ = [
    "BaseSkill",
    "SkillContext",
    "SkillResult",
    "SkillStatus",
]


class SkillStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    PARTIAL = "partial"


@dataclass
class SkillContext:
    """
    Rich context passed to every skill execution.

    Wraps the graph state with convenience accessors and metadata.
    Converts to/from LangGraph AgentState for compatibility.
    """

    messages: list[BaseMessage] = field(default_factory=list)
    session_id: str = ""
    thread_id: str = ""
    mode: str = "thinking"
    shared_state: dict[str, Any] = field(default_factory=dict)
    rewrite_count: int = 0
    max_rewrites: int = 3
    trace_id: str | None = None

    @property
    def last_human_message(self) -> HumanMessage | None:
        for msg in reversed(self.messages):
            if isinstance(msg, HumanMessage):
                return msg
        return None

    @property
    def question(self) -> str:
        msg = self.last_human_message
        return msg.content if msg else ""

    @property
    def is_rewrite_limit_reached(self) -> bool:
        return self.rewrite_count >= self.max_rewrites

    @property
    def last_message(self) -> BaseMessage | None:
        return self.messages[-1] if self.messages else None

    def to_agent_state(self) -> dict[str, Any]:
        return {
            "messages": self.messages,
            "rewrite_count": self.rewrite_count,
            "max_rewrites": self.max_rewrites,
            "shared_state": dict(self.shared_state),
        }

    @classmethod
    def from_agent_state(
        cls,
        state: dict[str, Any],
        session_id: str = "",
        thread_id: str = "",
        mode: str = "thinking",
        trace_id: str | None = None,
    ) -> SkillContext:
        return cls(
            messages=state.get("messages", []),
            session_id=session_id,
            thread_id=thread_id,
            mode=mode,
            shared_state=dict(state.get("shared_state", {}) or {}),
            rewrite_count=state.get("rewrite_count", 0),
            max_rewrites=state.get("max_rewrites", 3),
            trace_id=trace_id,
        )


@dataclass
class SkillResult:
    """
    Standardized result from any skill execution.
    """

    status: SkillStatus = SkillStatus.SUCCESS
    messages: list[BaseMessage] = field(default_factory=list)
    state_updates: dict[str, Any] = field(default_factory=dict)
    next_action: str | None = None
    skill_name: str = ""
    execution_time_ms: float = 0.0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_state_update(self) -> dict[str, Any]:
        update = {}
        if self.messages:
            update["messages"] = self.messages
        update.update(self.state_updates)
        return update


class BaseSkill(ABC):
    """
    Abstract base class for all agent skills.

    Each skill encapsulates a single capability with a standard interface.
    Skills are stateless -- all state flows through SkillContext/SkillResult.
    """

    name: str = ""
    description: str = ""

    def __init__(
        self,
        llm: BaseChatModel | None = None,
        config: Any | None = None,
    ):
        self._llm = llm
        self._config = config

    @property
    def llm(self) -> BaseChatModel:
        if self._llm is None:
            from models.llm_models import get_llm

            self._llm = get_llm()
        return self._llm

    @abstractmethod
    def execute(self, context: SkillContext) -> SkillResult: ...

    @abstractmethod
    async def aexecute(self, context: SkillContext) -> SkillResult: ...

    def _timed_execute(self, context: SkillContext) -> SkillResult:
        start = time.perf_counter()
        try:
            result = self.execute(context)
        except Exception as e:
            result = SkillResult(
                status=SkillStatus.FAILURE,
                skill_name=self.name,
                error=str(e),
            )
        result.execution_time_ms = (time.perf_counter() - start) * 1000
        result.skill_name = self.name
        log.debug(f"Skill '{self.name}' executed in {result.execution_time_ms:.1f}ms")
        return result

    async def _timed_aexecute(self, context: SkillContext) -> SkillResult:
        start = time.perf_counter()
        try:
            result = await self.aexecute(context)
        except Exception as e:
            result = SkillResult(
                status=SkillStatus.FAILURE,
                skill_name=self.name,
                error=str(e),
            )
        result.execution_time_ms = (time.perf_counter() - start) * 1000
        result.skill_name = self.name
        return result

    def health_check(self) -> dict[str, Any]:
        return {"name": self.name, "healthy": True}
