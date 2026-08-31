"""
Agent Harness (Orchestrator)

Main orchestrator that:
- Registers skills
- Builds a LangGraph StateGraph with identical topology to the existing graph
- Provides invoke(), stream() for thinking mode
- Provides invoke_fast() for fast mode (retrieve -> generate)
- Handles SQLite checkpointing
- Integrates lifecycle hooks, observability, and planning
"""

from __future__ import annotations

import asyncio
import contextvars
import sqlite3
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import MemorySaver
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agent.context.state import AgentState
from agent.harness.lifecycle import LifecycleManager
from agent.harness.observability import TraceCollector
from agent.harness.planner import Planner, PlanType
from agent.skills.base import BaseSkill, SkillContext, SkillResult, SkillStatus
from agent.skills.registry import SkillRegistry
from utils.log_utils import log

__all__ = ["AgentHarness", "HarnessConfig"]


# Default on-disk path for session checkpoints. Exposed as a module-level
# attribute so tests/conftest.py tmp_data_dir can redirect it (AGENTS.md §10
# persistence contract); HarnessConfig.checkpoint_path reads it as its default.
DEFAULT_CHECKPOINT_PATH = "./data/checkpoints.db"


def _enable_strict_msgpack_deserialization() -> None:
    """Force langgraph-checkpoint into strict msgpack deserialization.

    Background: langgraph-checkpoint >= 3.0 fixed CVE-2025-64439 (json-mode
    deserialisation RCE) via a json allow-list and removal of the unsafe json
    mode. Separately, its ``JsonPlusSerializer`` exposes a *msgpack* deserialiser
    whose default is **permissive** (``allowed_msgpack_modules=True`` = any type
    instantiated) unless ``LANGGRAPH_STRICT_MSGPACK=true``. Because checkpoints
    land on disk as plaintext blobs, a permissive msgpack path is an RCE surface
    for anyone able to write the checkpoint DB. A security-fix PR must not ship
    with that path open, so we force strict here.

    The env var is read once at module import; to be robust against other
    modules importing langgraph.checkpoint before us, we also set the resolved
    flag directly on the internal module (idempotent). Strict mode only blocks
    *unregistered* custom types — normal graph state (dicts/messages/scalars)
    are SAFE_MSGPACK_TYPES and round-trip unaffected (verified in
    test_strict_msgpack_allows_normal_checkpoint_round_trip).
    """
    import os

    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
    try:
        from langgraph.checkpoint.serde import jsonplus as _jp

        _lg = getattr(_jp, "_lg_msgpack", None)
        if _lg is not None:
            _lg.STRICT_MSGPACK_ENABLED = True
    except ImportError:
        pass


_enable_strict_msgpack_deserialization()


# Sentinel SkillResult used by `_skill_to_conditional._assert_no_state_lost` to
# run the before-hook state-leak check without a real result yet (channel 2 is
# checked again after the skill executes with the actual result).
_EMPTY_SKILLRESULT = SkillResult()


# Per-run trace collector. Each invoke()/ainvoke() call installs a fresh
# TraceCollector here so that concurrent runs on the singleton harness never
# share/overwrite each other's traces (begin_run()/_traces.clear() isolation).
_run_trace_ctx: contextvars.ContextVar[TraceCollector | None] = contextvars.ContextVar(
    "agent_run_trace", default=None
)

_PRODUCER_OWNED_REQUEST_KEYS = frozenset(
    {
        "retrieval_evidence",
        "generation_evidence",
        "retrieval_relevance",
        "relevance_scores",
        "retrieved_contexts",
        "sources",
        "relevant_memories",
        "grounding_faithfulness",
        "max_rerank_prob",
        "fallback_general_chat",
        "conversation_history",
    }
)


def _build_request_shared_state(
    shared_state: dict[str, Any] | None = None,
    history: list | None = None,
) -> dict[str, Any]:
    """Build a fresh request scratchpad that overwrites stale checkpoint keys."""
    state: dict[str, Any] = {
        "retrieval_evidence": [],
        "generation_evidence": [],
        "retrieval_relevance": None,
        "relevance_scores": [],
        "retrieved_contexts": [],
        "sources": [],
        "relevant_memories": [],
        "conversation_history": [],
        "grounding_faithfulness": None,
        "max_rerank_prob": None,
        "filter_expr": None,
        "query_transform": None,
        "expand_parents": None,
        "intent": None,
        "intent_confidence": None,
        "fallback_general_chat": False,
    }
    for key, value in (shared_state or {}).items():
        if key not in _PRODUCER_OWNED_REQUEST_KEYS:
            state[key] = value
    if history is not None:
        state["conversation_history"] = list(history)
    return state


@dataclass
class HarnessConfig:
    """Configuration for AgentHarness."""

    # Session settings
    session_id: str | None = None
    thread_id: str | None = None

    # Execution mode
    default_mode: str = "thinking"
    enable_fast_mode: bool = True

    # Memory / checkpointing
    use_memory: bool = True
    # Resolved lazily via default_factory (evaluated at instantiation, not
    # class-definition) so monkeypatching the module-level DEFAULT_CHECKPOINT_PATH
    # (e.g. tests/conftest.py tmp_data_dir) takes effect for fresh instances.
    # The annotation stays ``str`` — no None sentinel leaks into downstream
    # sqlite3.connect/aiosqlite.connect call sites (AGENTS.md §10).
    checkpoint_path: str = field(default_factory=lambda: DEFAULT_CHECKPOINT_PATH)

    # Rewrites
    max_rewrites: int = 3

    def __post_init__(self):
        if self.session_id is None:
            self.session_id = str(uuid.uuid4())
        if self.thread_id is None:
            self.thread_id = str(uuid.uuid4())


class AgentHarness:
    """
    Agent orchestrator that builds and executes the RAG pipeline.

    The harness:
    1. Registers skills via register_skill()
    2. Builds a LangGraph StateGraph with the same topology as graph/graph.py
    3. Provides invoke() / stream() for thinking mode
    4. Provides invoke_fast() for fast mode
    5. Integrates lifecycle hooks and observability

    Graph topology (thinking mode, identical to existing):
        START -> agent -> [tools_condition]
                              |
                           retrieve -> grade -> [generate | rewrite]
                              |                       |
                           (end)                 rewrite -> agent (loop)

    Fast mode (no graph, direct):
        retrieve -> generate

    Example:
        >>> harness = AgentHarness()
        >>> harness.register_defaults()
        >>> result = harness.invoke("git 合并冲突如何解决?")
    """

    def __init__(
        self,
        llm: BaseChatModel | None = None,
        config: HarnessConfig | None = None,
    ):
        self._llm = llm
        self._config = config or HarnessConfig()
        self._registry = SkillRegistry()
        self._lifecycle = LifecycleManager()
        # Default collector for non-graph/legacy callers. Concurrent runs use
        # a per-run collector stored in _run_trace_ctx (a contextvar) so that
        # begin_run()/_traces.clear() on one run never interleaves with another.
        self._trace_collector = TraceCollector()
        self._planner = Planner(
            default_mode=self._config.default_mode,
            enable_fast_mode=self._config.enable_fast_mode,
        )

        # Built graph components
        self._graph = None
        self._memory = None
        self._checkpoint_conn = None
        self._async_checkpoint_conn = None
        # Guards the async checkpoint init (astart) so concurrent first-calls
        # do not double-build the graph.
        self._async_init_lock = asyncio.Lock()
        # Serializes the SYNC invoke()/stream() graph calls. The sync SQLite
        # checkpointer uses check_same_thread=False on a shared connection with
        # no internal locking, so concurrent sync invocations across threads
        # would raise/corrupt (LangGraph writes checkpoints via SqliteSaver on
        # every node). The async path (AsyncSqliteSaver via aiosqlite) is
        # connection-safe and does NOT take this lock. Production multi-worker
        # deployments should use the async path; this lock makes the sync path
        # correct for CLI/scripts.
        import threading

        self._sync_invoke_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def llm(self) -> BaseChatModel:
        if self._llm is None:
            from models.llm_models import get_llm

            self._llm = get_llm()
        return self._llm

    @property
    def registry(self) -> SkillRegistry:
        return self._registry

    @property
    def lifecycle(self) -> LifecycleManager:
        return self._lifecycle

    @property
    def traces(self) -> TraceCollector:
        """Trace collector for the current run, if any; else the default one.

        Concurrent invocations each get their own collector via the run
        contextvar, so traces from one run never bleed into another.
        """
        run_collector = _run_trace_ctx.get()
        return run_collector if run_collector is not None else self._trace_collector

    @property
    def graph(self):
        """Get the compiled graph (lazy build)."""
        if self._graph is None:
            self.build_graph()
        return self._graph

    # ------------------------------------------------------------------
    # Skill registration
    # ------------------------------------------------------------------

    def register_skill(self, skill: BaseSkill) -> AgentHarness:
        """Register a skill. Returns self for chaining."""
        self._registry.register(skill)
        return self

    def register_defaults(self) -> AgentHarness:
        """
        Register all default skills.

        Creates instances of all 5 skills with the current LLM. The AgentSkill
        is wired to an MCPClient aggregating all registered MCP servers (retrieval
        + any custom tools), so the agent can call multiple tools, not just
        retrieval.
        """
        from agent.skills.agent.skill import AgentSkill
        from agent.skills.generate.skill import GenerateSkill
        from agent.skills.grade.skill import GradeSkill
        from agent.skills.retrieve.skill import RetrieveSkill
        from agent.skills.rewrite.skill import RewriteSkill

        # Build the MCP tool client aggregating all available tool servers.
        mcp_client = self._build_mcp_client()

        self.register_skill(AgentSkill(llm=self.llm, mcp_client=mcp_client))
        self.register_skill(RetrieveSkill())
        self.register_skill(GradeSkill(llm=self.llm))
        self.register_skill(RewriteSkill(llm=self.llm))
        self.register_skill(GenerateSkill(llm=self.llm))

        # IntentSkill is intentionally NOT registered here: intent classification
        # lives in the chat router (api/routers/chat.py via
        # core/intent/classifier.py), which routes before the harness is invoked.
        log.info("AgentHarness: 5 default skills registered (MCP tools wired)")
        return self

    def _build_mcp_client(self):
        """
        Build the MCPClient aggregating all tool servers.

        Always includes the retrieval server; additional servers can be
        registered via the module-level ``register_mcp_server`` hook or
        environment configuration. Failures are non-fatal: if MCP assembly
        fails, the AgentSkill falls back to the standalone retriever tool.
        """
        try:
            from agent.mcp.client import MCPClient
            from agent.mcp.retrieval_server import MCPRetrievalServer

            client = MCPClient()
            client.add_server(MCPRetrievalServer())

            # Discover and register any extra tool servers (plugins).
            from agent.mcp.tools_registry import get_extra_servers

            for server in get_extra_servers():
                try:
                    client.add_server(server)
                except Exception as e:  # noqa: BLE001
                    log.warning(f"Failed to register MCP server {server}: {e}")

            return client
        except Exception as e:  # noqa: BLE001
            log.warning(f"MCP client assembly failed, agent falls back to retriever: {e}")
            return None

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def build_graph(self) -> StateGraph:
        """
        Build the LangGraph StateGraph from registered skills.

        Produces a graph with identical topology to graph/graph.py:
            START -> agent -> [tools_condition]
                                  |
                               retrieve -> grade -> [generate | rewrite]
                                  |                       |
                               END                   agent (loop)

        Returns:
            Compiled StateGraph
        """
        log.info("AgentHarness: building graph...")

        workflow = StateGraph(AgentState)

        # Get skills
        agent_skill = self._registry.get("agent")
        rewrite_skill = self._registry.get("rewrite")
        generate_skill = self._registry.get("generate")
        grade_skill = self._registry.get("grade")
        retrieve_skill = self._registry.get("retrieve")

        # Add skill-based nodes
        if agent_skill is not None:
            workflow.add_node("agent", self._skill_to_node("agent", agent_skill))

        if retrieve_skill is not None:
            workflow.add_node("retrieve", self._skill_to_node("retrieve", retrieve_skill))
        else:
            retrieve_tools = self._get_retrieve_tools()
            workflow.add_node("retrieve", ToolNode(retrieve_tools))

        if rewrite_skill is not None:
            workflow.add_node("rewrite", self._skill_to_node("rewrite", rewrite_skill))

        if generate_skill is not None:
            workflow.add_node("generate", self._skill_to_node("generate", generate_skill))

        # Edges (identical to existing graph.py)
        workflow.add_edge(START, "agent")

        # Conditional edge from agent: tools or END
        workflow.add_conditional_edges(
            "agent",
            tools_condition,
            {"tools": "retrieve", END: END},
        )

        # Conditional edge from retrieve: grade -> generate or rewrite
        if grade_skill is not None:
            grade_fn = self._skill_to_conditional("grade", grade_skill)
            workflow.add_conditional_edges(
                "retrieve",
                grade_fn,
                {"generate": "generate", "rewrite": "rewrite"},
            )

        # Rewrite loops back to agent
        workflow.add_edge("rewrite", "agent")

        # Generate ends the flow
        workflow.add_edge("generate", END)

        # Checkpointing
        if self._config.use_memory and self._memory is None:
            self._setup_checkpointing()

        # Compile
        if self._memory is not None:
            self._graph = workflow.compile(checkpointer=self._memory)
        else:
            self._graph = workflow.compile()

        log.info("AgentHarness: graph built successfully")
        return self._graph

    def _merge_state_update(
        self,
        result: SkillResult,
        before_increments: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Build the node's state-update dict from a SkillResult plus any
        ``shared_state`` increments returned by before-skill hooks.

        Before-hook increments are merged *under* the skill's own
        ``shared_state`` writes so a skill can never accidentally clobber a
        hook's contribution (and vice-versa) — per-key, the skill's explicit
        output wins, but untouched hook keys are preserved.
        """
        update = result.to_state_update()
        if before_increments:
            hook_shared = before_increments.get("shared_state")
            if isinstance(hook_shared, dict) and hook_shared:
                merged_shared = dict(hook_shared)
                skill_shared = update.get("shared_state")
                if isinstance(skill_shared, dict):
                    merged_shared.update(skill_shared)
                update["shared_state"] = merged_shared
            # Allow hooks to touch non-shared_state fields too.
            for key, value in before_increments.items():
                if key == "shared_state":
                    continue
                update.setdefault(key, value)
        return update

    def _skill_to_node(self, skill_name: str, skill: BaseSkill):
        harness = self

        def node_fn(state: AgentState) -> dict[str, Any]:
            context = SkillContext.from_agent_state(
                state,
                session_id=harness._config.session_id or "",
                thread_id=harness._config.thread_id or "",
            )

            # Fire before hooks (guardrails may raise GuardrailBlockError).
            # Hooks may return shared_state increments that must propagate to
            # downstream nodes; merge them into the node's state update.
            try:
                before_increments = harness._lifecycle.fire_before_skill(skill_name, context)
            except Exception as guardrail_err:
                from agent.skills.base import SkillResult, SkillStatus

                log.warning(f"Skill '{skill_name}' blocked: {guardrail_err}")
                return SkillResult(
                    status=SkillStatus.FAILURE,
                    skill_name=skill_name,
                    error=str(guardrail_err),
                    messages=[AIMessage(content="请求被安全策略拦截，请重新描述您的问题。")],
                ).to_state_update()

            # Execute with tracing
            trace = harness.traces.begin(skill_name)
            result = skill._timed_execute(context)

            trace.finish(
                status=result.status.value,
                error=result.error,
                metadata=result.metadata,
            )

            # Fire after hooks
            harness._lifecycle.fire_after_skill(skill_name, context, result)

            return harness._merge_state_update(result, before_increments)

        async def async_node_fn(state: AgentState) -> dict[str, Any]:
            context = SkillContext.from_agent_state(
                state,
                session_id=harness._config.session_id or "",
                thread_id=harness._config.thread_id or "",
            )

            try:
                before_increments = harness._lifecycle.fire_before_skill(skill_name, context)
            except Exception as guardrail_err:
                log.warning(f"Skill '{skill_name}' blocked: {guardrail_err}")
                return SkillResult(
                    status=SkillStatus.FAILURE,
                    skill_name=skill_name,
                    error=str(guardrail_err),
                    messages=[AIMessage(content="请求被安全策略拦截，请重新描述您的问题。")],
                ).to_state_update()

            trace = harness.traces.begin(skill_name)
            from core.tracing import trace_context

            with trace_context(
                f"agent.skill.{skill_name}",
                **{"agent.skill.name": skill_name},
            ) as span:
                result = await skill._timed_aexecute(context)
                span.set_attribute("agent.skill.status", result.status.value)
                for key, value in result.metadata.items():
                    if isinstance(value, (str, bool, int, float)):
                        span.set_attribute(f"agent.skill.{key}", value)
                if result.error:
                    span.record_exception(Exception(result.error))

            trace.finish(
                status=result.status.value,
                error=result.error,
                metadata=result.metadata,
            )
            harness._lifecycle.fire_after_skill(skill_name, context, result)
            return harness._merge_state_update(result, before_increments)

        return RunnableLambda(node_fn, afunc=async_node_fn)

    def _skill_to_conditional(self, skill_name: str, skill: BaseSkill):
        """
        Convert a skill to a LangGraph conditional edge function.

        Used for the grade skill which returns "generate" or "rewrite".

        Conditional-edge functions can only return a routing key — they cannot
        emit a state update. That means state writes are silently lost here along
        TWO channels: (1) any ``shared_state`` increment returned by a before-hook,
        and (2) the skill's own ``SkillResult.state_updates``/``shared_state``.
        ``_assert_no_state_lost`` guards both and logs an error (never raises) if
        either channel carries state — so a future developer who adds a grade
        before-hook or who puts ``state_updates`` on GradeSkill gets a loud signal
        instead of a silent drop. The real fix if grade ever needs to write state
        is to convert it from a conditional edge into a real node.
        """

        def _assert_no_state_lost(before_increments, result):
            leaked = []
            if before_increments:
                if before_increments.get("shared_state"):
                    leaked.append("before-hook shared_state")
                else:
                    leaked.append(f"before-hook fields: {list(before_increments)}")
            su = result.state_updates or {}
            if su.get("shared_state"):
                leaked.append("skill state_updates.shared_state")
            elif su:
                leaked.append(f"skill state_updates keys: {list(su)}")
            if leaked:
                log.error(
                    f"[conditional-edge-guard] skill '{skill_name}' is wired as a "
                    f"conditional edge and cannot persist state, but it produced: "
                    f"{leaked}. The state was dropped. If '{skill_name}' needs to "
                    f"write state, convert it from a conditional edge into a real node."
                )

        harness = self

        def conditional_fn(state: AgentState):
            context = SkillContext.from_agent_state(
                state,
                session_id=harness._config.session_id or "",
                thread_id=harness._config.thread_id or "",
            )

            before_increments = harness._lifecycle.fire_before_skill(skill_name, context)
            _assert_no_state_lost(before_increments, _EMPTY_SKILLRESULT)

            trace = harness.traces.begin(skill_name)
            result = skill._timed_execute(context)

            trace.finish(
                status=result.status.value,
                error=result.error,
                metadata=result.metadata,
            )

            harness._lifecycle.fire_after_skill(skill_name, context, result)
            _assert_no_state_lost(None, result)

            # Return the routing decision
            return result.next_action or "generate"

        async def async_conditional_fn(state: AgentState):
            context = SkillContext.from_agent_state(
                state,
                session_id=harness._config.session_id or "",
                thread_id=harness._config.thread_id or "",
            )
            before_increments = harness._lifecycle.fire_before_skill(skill_name, context)
            _assert_no_state_lost(before_increments, _EMPTY_SKILLRESULT)
            trace = harness.traces.begin(skill_name)

            from core.tracing import trace_context

            with trace_context(
                f"agent.skill.{skill_name}",
                **{"agent.skill.name": skill_name},
            ) as span:
                result = await skill._timed_aexecute(context)
                span.set_attribute("agent.skill.status", result.status.value)
                for key, value in result.metadata.items():
                    if isinstance(value, (str, bool, int, float)):
                        span.set_attribute(f"agent.skill.{key}", value)
                if result.error:
                    span.record_exception(Exception(result.error))

            trace.finish(
                status=result.status.value,
                error=result.error,
                metadata=result.metadata,
            )
            harness._lifecycle.fire_after_skill(skill_name, context, result)
            _assert_no_state_lost(None, result)
            return result.next_action or "generate"

        return RunnableLambda(conditional_fn, afunc=async_conditional_fn)

    def _get_retrieve_tools(self):
        """
        Get tools for the ToolNode.

        Tries to get tools from the agent skill, falls back to
        the existing retriever tool.
        """
        agent_skill = self._registry.get("agent")
        if agent_skill is not None and hasattr(agent_skill, "tools"):
            tools = agent_skill.tools
            if tools:
                return tools

        # Fallback: use the existing retriever tool
        from agent.mcp.retriever_tools import get_retriever_tool

        return [get_retriever_tool()]

    # ------------------------------------------------------------------
    # Per-run trace isolation
    # ------------------------------------------------------------------

    def _begin_run(self) -> TraceCollector:
        """Install a fresh per-run TraceCollector and start it.

        The collector is stored in a contextvar so that node functions (which
        may run as asyncio tasks spawned by LangGraph) inherit it via the
        standard contextvar copy-on-task semantics. This isolates traces and
        begin_run()/_traces.clear() across concurrent runs on the singleton
        harness.
        """
        collector = TraceCollector()
        _run_trace_ctx.set(collector)
        collector.begin_run()
        return collector

    def _end_run(self, collector: TraceCollector) -> None:
        """Finalise a run's trace and log the summary, then clear the var."""
        try:
            collector.end_run()
            collector.log_summary()
        finally:
            # Only reset if we still own the var (a nested run would have
            # replaced it; we must not clobber that).
            if _run_trace_ctx.get() is collector:
                _run_trace_ctx.set(None)

    def _setup_checkpointing(self) -> None:
        """Set up SQLite checkpointing for session persistence."""
        try:
            import os

            _ckpt_dir = os.path.dirname(self._config.checkpoint_path) or "."
            os.makedirs(_ckpt_dir, exist_ok=True)
            self._checkpoint_conn = sqlite3.connect(
                self._config.checkpoint_path,
                check_same_thread=False,
            )
            from langgraph.checkpoint.sqlite import SqliteSaver

            self._memory = SqliteSaver(self._checkpoint_conn)
            log.info("AgentHarness: SQLite checkpoint enabled")
        except ImportError:
            log.warning("langgraph-checkpoint-sqlite not installed, using MemorySaver")
            self._memory = MemorySaver()

    async def astart(self) -> None:
        """Initialize the native async SQLite checkpointer and rebuild the graph.

        Guarded by an asyncio lock with double-checked locking so that
        concurrent first async invocations do not double-build the graph or
        open multiple async checkpoint connections.
        """
        if not self._config.use_memory or self._async_checkpoint_conn is not None:
            return

        async with self._async_init_lock:
            # Re-check inside the lock: another task may have completed the
            # init while we were waiting.
            if self._async_checkpoint_conn is not None:
                return

            import os

            import aiosqlite
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            _ckpt_dir = os.path.dirname(self._config.checkpoint_path) or "."
            os.makedirs(_ckpt_dir, exist_ok=True)
            if self._checkpoint_conn is not None:
                self._checkpoint_conn.close()
                self._checkpoint_conn = None
            self._async_checkpoint_conn = await aiosqlite.connect(self._config.checkpoint_path)
            self._memory = AsyncSqliteSaver(self._async_checkpoint_conn)
            self._graph = None
            self.build_graph()
            log.info("AgentHarness: async SQLite checkpoint enabled")

    # ------------------------------------------------------------------
    # Invocation
    # ------------------------------------------------------------------

    def invoke(
        self,
        question: str,
        thread_id: str | None = None,
        max_rewrites: int | None = None,
        mode: str | None = None,
        shared_state: dict[str, Any] | None = None,
        history: list | None = None,
    ) -> dict[str, Any]:
        """
        Invoke the agent with a question (thinking mode by default).

        Args:
            question: User's question
            thread_id: Optional thread ID for session continuity
            max_rewrites: Max rewrite attempts (default from config)
            mode: Execution mode override ('thinking', 'fast')
            shared_state: Optional seed for the cross-node scratchpad (Bug2 Layer
                ②/⑤: chat router injects intent_confidence for the A/B shunt)

        Returns:
            Final agent state after execution
        """
        # Determine execution plan
        plan = self._planner.plan(query=question, mode=mode)

        if plan.plan_type == PlanType.FAST:
            return self.invoke_fast(question, thread_id=thread_id)

        # Thinking mode: use the full graph
        thread_id = thread_id or self._config.thread_id
        max_rewrites = max_rewrites or self._config.max_rewrites

        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }

        inputs = {
            "messages": [HumanMessage(content=question)],
            "rewrite_count": 0,
            "max_rewrites": max_rewrites,
            "shared_state": _build_request_shared_state(shared_state, history),
        }

        run_collector = self._begin_run()
        try:
            # Serialize sync graph invocations — the shared sync SQLite
            # checkpointer connection is not safe for concurrent writes.
            with self._sync_invoke_lock:
                result = self.graph.invoke(inputs, config=config)
        finally:
            self._end_run(run_collector)
        return result

    def stream(
        self,
        question: str,
        thread_id: str | None = None,
        stream_mode: Any = "values",
        max_rewrites: int | None = None,
        shared_state: dict[str, Any] | None = None,
        history: list | None = None,
    ):
        """
        Stream the graph execution.

        Args:
            question: User's question
            thread_id: Thread ID for session continuity
            stream_mode: "values" or "updates"
            max_rewrites: Max rewrite attempts
            shared_state: Request-scoped caller controls
            history: Conversation history; an explicit empty list clears stale history

        Yields:
            State updates during execution
        """
        thread_id = thread_id or self._config.thread_id
        max_rewrites = max_rewrites or self._config.max_rewrites

        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }

        inputs = {
            "messages": [HumanMessage(content=question)],
            "rewrite_count": 0,
            "max_rewrites": max_rewrites,
            "shared_state": _build_request_shared_state(shared_state, history),
        }

        run_collector = self._begin_run()
        try:
            # Serialize sync graph streams — checkpoints are written throughout
            # streaming, so the lock spans the whole generator.
            with self._sync_invoke_lock:
                yield from self.graph.stream(inputs, config=config, stream_mode=stream_mode)
        finally:
            self._end_run(run_collector)

    async def ainvoke(
        self,
        question: str,
        thread_id: str | None = None,
        max_rewrites: int | None = None,
        mode: str | None = None,
        shared_state: dict[str, Any] | None = None,
        history: list | None = None,
    ) -> dict[str, Any]:
        """Invoke the graph through its native asynchronous execution path.

        ``shared_state`` seeds the graph's cross-node scratchpad (merged via the
        ``merge_shared_state`` reducer). Bug2 Layer ②/⑤: the chat router injects
        ``intent_confidence`` here so GenerateSkill's A/B shunt can read it.

        ``history`` (REQ-CR-002): conversation history for multi-turn RAG. Injected
        into ``shared_state["conversation_history"]`` (read-only, harness-owned) so
        rewrite/generate skills can resolve coreferences — NOT into AgentState.messages
        (avoids add_messages reducer + checkpointer double-counting).
        """
        plan = self._planner.plan(query=question, mode=mode)
        if plan.plan_type == PlanType.FAST:
            from core.fast_mode import fast_generate_async

            result = await fast_generate_async(question, top_k=3)
            return {
                "messages": [
                    HumanMessage(content=question),
                    AIMessage(content=result.answer),
                ],
                "_fast_mode": True,
                "_sources": result.sources,
                "_retrieval_time_ms": result.retrieval_time_ms,
                "_generation_time_ms": result.generation_time_ms,
            }

        await self.astart()
        thread_id = thread_id or self._config.thread_id
        max_rewrites = max_rewrites or self._config.max_rewrites
        inputs: dict[str, Any] = {
            "messages": [HumanMessage(content=question)],
            "rewrite_count": 0,
            "max_rewrites": max_rewrites,
            "shared_state": _build_request_shared_state(shared_state, history),
        }
        config = {"configurable": {"thread_id": thread_id}}

        run_collector = self._begin_run()
        try:
            result = await self.graph.ainvoke(inputs, config=config)
        finally:
            self._end_run(run_collector)
        return result

    async def astream(
        self,
        question: str,
        thread_id: str | None = None,
        stream_mode: Any = "values",
        max_rewrites: int | None = None,
        shared_state: dict[str, Any] | None = None,
        history: list | None = None,
    ) -> AsyncIterator[Any]:
        """Stream graph updates and custom token events natively through asyncio.

        ``shared_state`` seeds the cross-node scratchpad (Bug2 Layer ②/⑤).
        ``history`` (REQ-CR-002): conversation history for multi-turn RAG."""
        await self.astart()
        thread_id = thread_id or self._config.thread_id
        max_rewrites = max_rewrites or self._config.max_rewrites
        inputs = {
            "messages": [HumanMessage(content=question)],
            "rewrite_count": 0,
            "max_rewrites": max_rewrites,
            "shared_state": _build_request_shared_state(shared_state, history),
        }
        config = {"configurable": {"thread_id": thread_id}}

        run_collector = self._begin_run()
        try:
            async for event in self.graph.astream(
                inputs,
                config=config,
                stream_mode=stream_mode,
            ):
                yield event
        finally:
            # Align with invoke/ainvoke/invoke_fast: reset the per-run
            # contextvar (so traces never bleed into a subsequent run on the
            # same task) and emit the run summary. The prior code only called
            # end_run() directly, leaving _run_trace_ctx pointing at the
            # finished collector and skipping log_summary() — see B1.
            self._end_run(run_collector)

    def invoke_fast(self, query: str, thread_id: str | None = None) -> dict[str, Any]:
        """
        Fast mode: direct retrieve + generate without the full graph.

        Skips agent, grade, and rewrite. Uses /no_think for Qwen3
        to suppress reasoning and minimize latency.

        Args:
            query: User's question
            thread_id: Unused in fast mode (no checkpointing)

        Returns:
            Dict with answer, sources, and timing
        """
        from core.fast_mode import fast_generate

        run_collector = self._begin_run()
        try:
            result = fast_generate(query, top_k=3)
        finally:
            self._end_run(run_collector)

        # Convert FastModeResult to a state-like dict
        ai_message = AIMessage(content=result.answer)
        return {
            "messages": [HumanMessage(content=query), ai_message],
            "rewrite_count": 0,
            "max_rewrites": self._config.max_rewrites,
            "_fast_mode": True,
            "_sources": result.sources,
            "_retrieval_time_ms": result.retrieval_time_ms,
            "_generation_time_ms": result.generation_time_ms,
        }

    async def ainvoke_fast(self, query: str, top_k: int = 3) -> AsyncIterator[dict[str, Any]]:
        """
        Fast mode with streaming.

        Yields SSE-style event dicts for real-time output.
        """
        from core.fast_mode import fast_generate_stream

        run_collector = self._begin_run()
        try:
            async for event in fast_generate_stream(query, top_k=top_k):
                yield event
        finally:
            self._end_run(run_collector)

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def new_session(self) -> str:
        """Start a new session with fresh thread ID."""
        self._config.thread_id = str(uuid.uuid4())
        self._config.session_id = str(uuid.uuid4())
        return self._config.thread_id

    def get_config(self) -> dict[str, Any]:
        """Get current harness configuration."""
        return {
            "session_id": self._config.session_id,
            "thread_id": self._config.thread_id,
            "default_mode": self._config.default_mode,
            "use_memory": self._config.use_memory,
            "skills": self._registry.list_skills(),
        }

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close checkpoint DB connection and release resources."""
        if self._checkpoint_conn is not None:
            try:
                self._checkpoint_conn.close()
            except Exception:
                pass
            self._checkpoint_conn = None

    async def aclose(self) -> None:
        """Close synchronous and asynchronous checkpoint resources."""
        self.close()
        if self._async_checkpoint_conn is not None:
            await self._async_checkpoint_conn.close()
            self._async_checkpoint_conn = None

    def __enter__(self) -> AgentHarness:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
