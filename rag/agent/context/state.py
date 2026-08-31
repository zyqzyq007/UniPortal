"""
Agent State Definitions and Message Utilities

Consolidates graph state types and message helpers previously in
graph/graph_state.py and graph/get_human_message.py.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, TypedDict, TypeVar

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import add_messages
from pydantic import BaseModel, ConfigDict, Field

from agent.skills.base import SkillContext, SkillResult, SkillStatus

__all__ = [
    # From skills.base (re-exported)
    "SkillContext",
    "SkillResult",
    "SkillStatus",
    # Graph state
    "AgentState",
    "NodeType",
    "RouteDecision",
    "GraphMetadata",
    "StateManager",
    "merge_shared_state",
    # Pydantic models
    "Grade",
    "RewrittenQuery",
    "GeneratedAnswer",
    # Message utilities
    "get_last_human_message",
    "get_last_ai_message",
    "MessageExtractor",
]


# =============================================================================
# Graph State
# =============================================================================


class NodeType(str, Enum):
    AGENT = "agent"
    RETRIEVE = "retrieve"
    REWRITE = "rewrite"
    GENERATE = "generate"
    GRADE = "grade"


class RouteDecision(str, Enum):
    GENERATE = "generate"
    REWRITE = "rewrite"
    TOOLS = "tools"
    END = "END"


def merge_shared_state(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """
    Reducer for the cross-node ``shared_state`` field on ``AgentState``.

    LangGraph invokes this whenever a node returns a ``shared_state`` update:
    it shallow-merges the incoming dict on top of the accumulated one (later
    writes win per-key). This is what finally lets a ``before_skill`` hook
    (e.g. memory enrichment) or a producing node (e.g. GenerateSkill writing
    ``retrieved_contexts``) propagate state to a downstream consumer node.

    Both sides default to ``{}`` so the field is always present after the first
    reduction, and missing values are treated as empty (back-compatible with
    checkpoints written before the field existed).
    """
    merged: dict[str, Any] = dict(left or {})
    merged.update(right or {})
    return merged


class AgentState(TypedDict):
    """
    Main state for the RAG agent graph.

    Fields:
        messages: List of conversation messages (add_messages reducer)
        rewrite_count: Number of query rewrites attempted
        max_rewrites: Maximum allowed rewrites before forcing generation
        shared_state: Cross-node scratchpad for producer/consumer data such as
            ``retrieved_contexts``, ``sources``, ``relevant_memories``,
            ``relevance_scores`` and ``grounding_faithfulness``. Merged across
            nodes via :func:`merge_shared_state`.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    rewrite_count: int
    max_rewrites: int
    shared_state: Annotated[dict[str, Any], merge_shared_state]


class GraphMetadata(TypedDict, total=False):
    session_id: str
    user_id: str | None
    start_time: float
    node_visits: dict[str, int]


# =============================================================================
# Pydantic Models for Structured Output
# =============================================================================


class Grade(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    binary_score: str | None = Field(
        default=None,
        description="相关性评分: 'yes'/'no'。None 表示未设置(保守→not relevant)。"
        "默认 None 而非 'yes':json_mode 下 LLM 返回未知 key 时,字段保持 None,"
        "is_relevant 回落 False(偏向 rewrite 而非幻觉)。",
    )
    answer: str | None = Field(
        default=None, description="备选字段，部分模型（如Qwen3）可能使用此字段返回yes/no"
    )

    @property
    def is_relevant(self) -> bool:
        # Both fields may carry the verdict (Qwen3 sometimes uses only `answer`).
        # An explicit "yes"/"true" in EITHER field wins; otherwise fall to
        # binary_score (default "no" -> conservative not-relevant).
        for val in (self.binary_score, self.answer):
            if val:
                v = val.strip().lower()
                if v in ("yes", "true", "relevant"):
                    return True
                if v in ("no", "false", "not relevant", "irrelevant"):
                    return False
        return False


class RewrittenQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    original_query: str = Field(description="原始用户查询")
    rewritten_query: str = Field(description="改进后的查询")
    reasoning: str | None = Field(default=None, description="重写推理过程")


class GeneratedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    answer: str = Field(description="生成的回答内容")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    sources: list[str] | None = Field(default=None, description="引用来源")


# =============================================================================
# State Manager
# =============================================================================


class StateManager:
    @staticmethod
    def get_message_count(state: AgentState) -> int:
        return len(state.get("messages", []))

    @staticmethod
    def get_last_message(state: AgentState) -> BaseMessage | None:
        messages = state.get("messages", [])
        return messages[-1] if messages else None

    @staticmethod
    def create_initial_state(message: str, max_rewrites: int = 3) -> AgentState:
        return {
            "messages": [("user", message)],
            "rewrite_count": 0,
            "max_rewrites": max_rewrites,
            "shared_state": {},
        }

    @staticmethod
    def increment_rewrite_count(state: AgentState) -> AgentState:
        current = state.get("rewrite_count", 0)
        return {
            "rewrite_count": current + 1,
            "max_rewrites": state.get("max_rewrites", 3),
        }

    @staticmethod
    def is_rewrite_limit_reached(state: AgentState) -> bool:
        count = state.get("rewrite_count", 0)
        max_count = state.get("max_rewrites", 3)
        return count >= max_count

    @staticmethod
    def append_message(state: AgentState, message: BaseMessage) -> AgentState:
        return {"messages": [message]}


# =============================================================================
# Message Utilities
# =============================================================================


class MessageNotFoundError(Exception):
    pass


def get_last_human_message(messages: list[BaseMessage]) -> HumanMessage:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message
    raise MessageNotFoundError("No HumanMessage found in the messages list")


def get_last_ai_message(messages: list[BaseMessage]) -> AIMessage | None:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message
    return None


T = TypeVar("T", bound=BaseMessage)


class MessageExtractor:
    def __init__(self, messages: list[BaseMessage]):
        self.messages = messages

    def get_last_human_message(self) -> HumanMessage:
        return get_last_human_message(self.messages)

    def get_last_ai_message(self) -> AIMessage | None:
        return get_last_ai_message(self.messages)
