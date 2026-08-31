"""
Planner

Determines the execution plan for an agent run based on the caller-provided
``mode`` override (set by the chat router from the user's depth/fast toggle):
- Thinking mode: full graph (agent -> retrieve -> grade -> generate/rewrite)
- Fast mode: direct (retrieve -> generate) skipping agent, grade, rewrite
- Direct mode: LLM-only, no retrieval

NOTE on intent routing: intent classification lives in the chat router
(``api/routers/chat.py`` via ``core/intent/classifier.py``), which routes
``general_chat`` to a direct LLM call and ``rag_query`` to the harness BEFORE
the harness is ever invoked. The harness is therefore only reached for RAG
queries, and the router never passes ``intent`` into it. Accordingly this
Planner routes purely on ``mode``; the previously-stubbed intent branches were
unreachable at runtime and have been removed to avoid misleading readers.
"""

from __future__ import annotations

from dataclasses import dataclass

from utils.log_utils import log

__all__ = [
    "ExecutionPlan",
    "PlanType",
    "Planner",
]


class PlanType:
    """Execution plan types."""

    THINKING = "thinking"
    FAST = "fast"
    DIRECT = "direct"  # General chat, no retrieval needed


@dataclass
class ExecutionPlan:
    """
    Describes how the agent should execute a query.

    Attributes:
        plan_type: One of 'thinking', 'fast', 'direct'
        skills: Ordered list of skill names to execute
        mode: Human-readable description
    """

    plan_type: str
    skills: list[str]
    mode: str = ""

    # Pre-built plans for common paths
    @classmethod
    def thinking_plan(cls) -> ExecutionPlan:
        """Full thinking mode: agent -> retrieve -> grade -> generate/rewrite."""
        return cls(
            plan_type=PlanType.THINKING,
            skills=["agent", "retrieve", "grade", "generate", "rewrite"],
            mode="thinking",
        )

    @classmethod
    def fast_plan(cls) -> ExecutionPlan:
        """Fast mode: retrieve -> generate (no agent/grade/rewrite)."""
        return cls(
            plan_type=PlanType.FAST,
            skills=["retrieve", "generate"],
            mode="fast",
        )

    @classmethod
    def direct_plan(cls) -> ExecutionPlan:
        """Direct response (no retrieval, just LLM)."""
        return cls(
            plan_type=PlanType.DIRECT,
            skills=["agent"],
            mode="direct",
        )


class Planner:
    """
    Determines the execution plan from the caller-provided ``mode``.

    The chat router performs intent classification and routes general_chat to a
    direct LLM call without touching the harness; only RAG queries (and the
    explicit fast/direct mode overrides) reach here. This planner therefore maps
    ``mode`` to an :class:`ExecutionPlan`:

    Decision logic:
    1. If mode is explicitly "fast" (and fast mode enabled) -> fast plan
    2. If mode is explicitly "direct" -> direct plan
    3. Otherwise -> default plan (thinking, or fast if configured as default)
    """

    def __init__(
        self,
        default_mode: str = "thinking",
        enable_fast_mode: bool = True,
    ):
        self._default_mode = default_mode
        self._enable_fast_mode = enable_fast_mode

    def plan(
        self,
        query: str = "",
        mode: str | None = None,
        **kwargs,
    ) -> ExecutionPlan:
        """
        Determine the execution plan from ``mode``.

        Args:
            query: User's query (unused for routing; retained for API stability).
            mode: Explicit mode override ('thinking', 'fast', 'direct').

        Returns:
            ExecutionPlan describing the skill chain.
        """
        # Explicit mode override
        if mode == "fast" and self._enable_fast_mode:
            log.info("Planner: fast mode (explicit)")
            return ExecutionPlan.fast_plan()

        if mode == "direct":
            log.info("Planner: direct mode (explicit)")
            return ExecutionPlan.direct_plan()

        # Default plan
        if self._default_mode == "fast" and self._enable_fast_mode:
            log.info("Planner: fast mode (default)")
            return ExecutionPlan.fast_plan()

        log.info("Planner: thinking mode (default)")
        return ExecutionPlan.thinking_plan()
