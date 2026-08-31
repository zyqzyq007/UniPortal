"""
Retrieve Skill

Uses the shared adaptive/corrective RetrievalWorkflow by default, with the
legacy HybridRetriever path retained behind RETRIEVAL_WORKFLOW_ENABLED=false.

This skill is used in both:
- The full graph (as the ToolNode replacement / direct retriever)
- Fast mode (retrieve -> generate without agent/grade/rewrite)
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from agent.skills.base import BaseSkill, SkillContext, SkillResult, SkillStatus
from utils.log_utils import log

__all__ = ["RetrieveSkill", "RetrieveSkillConfig"]


def _per_doc_scoring_enabled() -> bool:
    """Whether F3 per-document continuous scoring is enabled (env, default false)."""
    import os

    return os.getenv("PER_DOC_SCORING_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass
class RetrieveSkillConfig:
    """Configuration for RetrieveSkill."""

    top_k: int = 4
    use_hybrid: bool = True
    max_context_length: int = 2500
    # When True, returns results as ToolMessage (for graph compat)
    return_as_tool_message: bool = True
    # Bug2 Layer ④ — rerank score dual sieve. rerank_score is a raw
    # cross-encoder logit (unbounded, can be negative; see
    # core/retrieval/reranker.py:204). min_rerank_prob is the SIGMOID ABSOLUTE
    # floor: sigmoid(score) < this -> dropped (cuts all-weak batches that pure
    # min-max cannot filter, since min-max forces the batch-top to 1.0). The
    # min-max-relative min_rerank_score is a batch-internal secondary filter.
    # Both default off-effect when <= 0. Reranker-degraded docs (rerank_applied
    # is not True) bypass filtering; empty-set handling is delegated to Layer ⑤.
    min_rerank_score: float = 0.3
    min_rerank_prob: float = 0.35


def _sigmoid(s: float) -> float:
    from core.retrieval.scoring import stable_sigmoid

    return stable_sigmoid(s)


class RetrieveSkill(BaseSkill):
    """
    Skill that retrieves documents from the knowledge base.

    Shares planner, corrective states and diagnostics with Fast mode and MCP.
    Can operate standalone or as part of the LangGraph pipeline.
    """

    name = "retrieve"
    description = "Retrieve documents from the knowledge base"

    def __init__(
        self,
        config: RetrieveSkillConfig | None = None,
        mcp_client: Any | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._skill_config = config or RetrieveSkillConfig()
        self._mcp_client = mcp_client
        self._retriever = None
        self._workflow = None

    @property
    def retriever(self):
        """Lazy-load the hybrid retriever."""
        if self._retriever is None:
            from core.retrieval.hybrid_retriever import get_hybrid_retriever

            self._retriever = get_hybrid_retriever()
        return self._retriever

    @property
    def workflow(self):
        if self._workflow is None:
            from core.retrieval.workflow import RetrievalWorkflow

            self._workflow = RetrievalWorkflow(retriever=self.retriever)
        return self._workflow

    def execute(self, context: SkillContext) -> SkillResult:
        """
        Retrieve documents synchronously.

        Expects the context to contain a question in the last human message
        or a tool_call from the agent.
        """
        start = time.perf_counter()
        messages = context.messages
        cleared_updates = self._retrieval_shared_updates([])
        context.shared_state.update(cleared_updates)

        try:
            query = self._extract_query(context)
            if not query:
                return SkillResult(
                    status=SkillStatus.SKIPPED,
                    skill_name=self.name,
                    error="No query found in context",
                    state_updates={"shared_state": self._retrieval_shared_updates([])},
                )

            # Retrieve documents (optional metadata filter + transform from shared_state)
            filter_expr = self._extract_filter(context)
            from core.retrieval.workflow import retrieval_workflow_enabled

            workflow_result = None
            if retrieval_workflow_enabled():
                workflow_result = self.workflow.retrieve(
                    query,
                    filter_expr=filter_expr,
                    final_k=self._skill_config.top_k,
                )
                documents = workflow_result.documents
            else:
                transform = self._decide_transform(context, query)
                documents = self._retrieve(query, filter_expr=filter_expr, transform=transform)
            documents = self._maybe_expand_parents(context, documents)
            documents = self._inject_memories(context, documents)
            # Bug2 Layer ④: drop docs below the rerank relevance floor (cuts
            # weak batches before grading). Empty result is delegated to Layer ⑤.
            documents = self._filter_by_rerank_score(documents)
            # F3: optional per-document continuous scoring (LLM grade + rerank +
            # embed sim fusion) for finer-grained filtering + re-ranking.
            documents = self._maybe_score_per_doc(query, documents, context)

            # Build result messages
            result_messages = self._build_result_messages(documents, messages, context)

            elapsed = (time.perf_counter() - start) * 1000
            log.info(f"RetrieveSkill: {len(documents)} docs, {elapsed:.0f}ms")

            # Publish mean retrieval relevance + per-doc scores into shared_state
            # so the generate node's composite confidence can consume them
            # cross-node (previously this write was lost between nodes).
            shared_updates = self._retrieval_shared_updates(
                documents,
                workflow_result.diagnostics if workflow_result is not None else None,
            )
            context.shared_state.update(shared_updates)

            return SkillResult(
                status=SkillStatus.SUCCESS if documents else SkillStatus.PARTIAL,
                messages=result_messages,
                next_action="grade",
                state_updates={"shared_state": shared_updates},
                metadata={
                    "doc_count": len(documents),
                    "query": query,
                    "retrieval_time_ms": elapsed,
                    **(
                        {"retrieval_diagnostics": workflow_result.diagnostics}
                        if workflow_result is not None
                        else {}
                    ),
                },
            )

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            log.error(f"RetrieveSkill failed ({elapsed:.0f}ms): {e}")
            return SkillResult(
                status=SkillStatus.FAILURE,
                skill_name=self.name,
                error=str(e),
                messages=[AIMessage(content="检索文档时发生错误，请稍后重试。")],
                state_updates={"shared_state": cleared_updates},
            )

    async def aexecute(self, context: SkillContext) -> SkillResult:
        """
        Retrieve documents asynchronously.

        If an MCP client is configured, delegates to the MCP retrieval server.
        Otherwise falls back to direct retrieval.
        """
        start = time.perf_counter()
        messages = context.messages
        cleared_updates = self._retrieval_shared_updates([])
        context.shared_state.update(cleared_updates)

        try:
            query = self._extract_query(context)
            if not query:
                return SkillResult(
                    status=SkillStatus.SKIPPED,
                    skill_name=self.name,
                    error="No query found in context",
                    state_updates={"shared_state": self._retrieval_shared_updates([])},
                )

            # Try MCP client first
            filter_expr = self._extract_filter(context)
            transform = self._decide_transform(context, query)
            from core.retrieval.workflow import retrieval_workflow_enabled

            workflow_result = None
            workflow_diagnostics = None
            if retrieval_workflow_enabled() and self._mcp_client is not None:
                try:
                    raw_results = await self._mcp_client.call_tool(
                        "rag_retrieve",
                        {
                            "query": query,
                            "top_k": self._skill_config.top_k,
                            # Forward filtering + query transform so the MCP
                            # path matches the direct-retrieval path. Previously
                            # these were dropped, causing a correctness divergence.
                            "filter_expr": filter_expr,
                            "transform": transform,
                        },
                    )
                    documents, workflow_diagnostics = self._raw_workflow_documents(raw_results)
                except Exception as e:
                    log.warning(f"MCP retrieval failed, falling back to direct: {e}")
                    workflow_result = await self.workflow.aretrieve(
                        query,
                        filter_expr=filter_expr,
                        final_k=self._skill_config.top_k,
                    )
                    documents = workflow_result.documents
                    workflow_diagnostics = workflow_result.diagnostics
            elif retrieval_workflow_enabled():
                workflow_result = await self.workflow.aretrieve(
                    query,
                    filter_expr=filter_expr,
                    final_k=self._skill_config.top_k,
                )
                documents = workflow_result.documents
                workflow_diagnostics = workflow_result.diagnostics
            elif self._mcp_client is not None:
                try:
                    raw_results = await self._mcp_client.call_tool(
                        "rag_retrieve",
                        {
                            "query": query,
                            "top_k": self._skill_config.top_k,
                            "filter_expr": filter_expr,
                            "transform": transform,
                        },
                    )
                    documents = self._raw_to_documents(raw_results)
                except Exception as e:
                    log.warning(f"MCP retrieval failed, falling back to direct: {e}")
                    documents = await self._aretrieve(query, filter_expr, transform)
            else:
                documents = await self._aretrieve(query, filter_expr, transform)
            documents = self._maybe_expand_parents(context, documents)
            documents = self._inject_memories(context, documents)
            # Bug2 Layer ④: rerank relevance floor (see sync path comment).
            documents = self._filter_by_rerank_score(documents)
            # F3: optional per-document continuous scoring (async).
            documents = await self._amaybe_score_per_doc(query, documents, context)

            # Build result messages
            result_messages = self._build_result_messages(documents, messages, context)

            elapsed = (time.perf_counter() - start) * 1000
            log.info(f"RetrieveSkill (async): {len(documents)} docs, " f"{elapsed:.0f}ms")

            # Publish mean retrieval relevance into shared_state (parity with
            # the sync path) for cross-node composite confidence.
            shared_updates = self._retrieval_shared_updates(documents, workflow_diagnostics)
            context.shared_state.update(shared_updates)

            return SkillResult(
                status=SkillStatus.SUCCESS if documents else SkillStatus.PARTIAL,
                messages=result_messages,
                next_action="grade",
                state_updates={"shared_state": shared_updates},
                metadata={
                    "doc_count": len(documents),
                    "query": query,
                    "retrieval_time_ms": elapsed,
                    **(
                        {"retrieval_diagnostics": workflow_diagnostics}
                        if workflow_diagnostics is not None
                        else {}
                    ),
                },
            )

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            log.error(f"RetrieveSkill async failed ({elapsed:.0f}ms): {e}")
            return SkillResult(
                status=SkillStatus.FAILURE,
                skill_name=self.name,
                error=str(e),
                messages=[AIMessage(content="检索文档时发生错误，请稍后重试。")],
                state_updates={"shared_state": cleared_updates},
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mean_relevance(documents: list[Document]) -> float | None:
        """Mean calibrated relevance, excluding rank-only RRF scores."""
        from agent.skills.grade.per_doc_scoring import _get_rerank_score

        scores = []
        for document in documents:
            from core.retrieval.scoring import probability

            grade = probability(document.metadata.get("grade_score"))
            if grade is not None:
                scores.append(grade)
                continue
            rerank = _get_rerank_score(document)
            if rerank is not None:
                scores.append(rerank)
        if not scores:
            return None
        return sum(scores) / len(scores)

    def _retrieval_shared_updates(
        self,
        documents: list[Document],
        diagnostics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from core.retrieval.evidence import documents_to_evidence

        updates = {
            "retrieval_evidence": documents_to_evidence(documents),
            "retrieval_relevance": self._mean_relevance(documents),
            "relevance_scores": [],
            "retrieved_contexts": [],
            "sources": [],
            "max_rerank_prob": self._compute_max_rerank_prob(documents),
        }
        if diagnostics is not None:
            updates["retrieval_diagnostics"] = diagnostics
        return updates

    def _maybe_score_per_doc(
        self, query: str, documents: list[Document], context: SkillContext
    ) -> list[Document]:
        """F3: optional per-document continuous scoring (LLM grade + rerank fusion).

        Gated by env PER_DOC_SCORING_ENABLED (default false — opt-in precision layer
        on top of the binary grade gate). Scores each doc ∈ [0,1], filters below
        threshold, re-ranks. Degrades to unchanged on any failure.
        """
        if not documents or not _per_doc_scoring_enabled():
            return documents
        try:
            from agent.skills.grade.per_doc_scoring import score_documents
            from models.llm_models import create_custom_llm

            llm = create_custom_llm(temperature=0.0)
            return score_documents(query, documents, llm)
        except Exception as e:  # noqa: BLE001 — degrade to unfiltered
            log.debug(f"per-doc scoring skipped: {e}")
            return documents

    async def _amaybe_score_per_doc(
        self, query: str, documents: list[Document], context: SkillContext
    ) -> list[Document]:
        """F3 async: concurrent per-document scoring."""
        if not documents or not _per_doc_scoring_enabled():
            return documents
        try:
            from agent.skills.grade.per_doc_scoring import ascore_documents
            from models.llm_models import create_custom_llm

            llm = create_custom_llm(temperature=0.0)
            return await ascore_documents(query, documents, llm)
        except Exception as e:  # noqa: BLE001
            log.debug(f"per-doc scoring (async) skipped: {e}")
            return documents

    def _filter_by_rerank_score(self, documents: list[Document]) -> list[Document]:
        """Bug2 Layer ④ — dual sieve: sigmoid absolute floor + min-max relative.

        ``rerank_score`` is a raw cross-encoder logit (unbounded, can be
        negative; ``core/retrieval/reranker.py:204``). Pure min-max has zero
        filtering power on weak batches (the batch-top is always normalized to
        1.0). The sigmoid floor gives an absolute relevance signal:
        ``sigmoid(score) < min_rerank_prob`` is dropped outright, so an
        all-weak batch (e.g. logits [-6,-5,-4,-3]) is correctly emptied and
        pushed to Layer ⑤. min-max is a batch-internal secondary filter.

        Docs without ``rerank_applied is True`` (reranker degraded/no reranker,
        or injected memories) bypass filtering; empty-set handling is delegated
        to Layer ⑤ A/B shunting.
        """
        rel_thr = self._skill_config.min_rerank_score
        prob_floor = self._skill_config.min_rerank_prob
        from core.retrieval.scoring import finite_real

        reranked: list[tuple[Document, float]] = []
        others = []
        for document in documents:
            raw_score = document.metadata.get("rerank_score")
            score = finite_real(raw_score)
            if document.metadata.get("rerank_applied") is True and score is not None:
                reranked.append((document, score))
            else:
                others.append(document)
        if not reranked or (rel_thr <= 0 and prob_floor <= 0):
            return documents  # degraded/unconfigured: do not filter, hand to Layer ⑤
        scores = [score for _, score in reranked]
        lo, hi = min(scores), max(scores)
        span = hi - lo

        def _passes(s: float) -> bool:
            if prob_floor > 0:
                try:
                    if _sigmoid(s) < prob_floor:
                        return False
                except ValueError:
                    return False
            if rel_thr > 0 and span >= 1e-9 and ((s - lo) / span) < rel_thr:
                return False
            return True

        kept = [document for document, score in reranked if _passes(score)]
        if not kept and others:
            kept = [max(reranked, key=lambda item: item[1])[0]]
        return kept + others

    def _compute_max_rerank_prob(self, documents: list[Document]) -> float | None:
        """Bug2 Layer ④ → ⑤ signal: the batch's max sigmoid probability.

        Published to ``shared_state['max_rerank_prob']`` so GenerateSkill (Layer ⑤)
        judges absolute usability on the SAME sigmoid scale as the filter above
        (one ruler, eliminating the v1 'empty-set definition mismatch' F-01).
        Returns None when no reranked docs exist (reranker degraded) — Layer ⑤
        then skips the shunt (degradation semantics: prefer recall over refuse).
        """
        from core.retrieval.scoring import raw_logit_probability

        probs = []
        for document in documents:
            if document.metadata.get("rerank_applied") is not True:
                continue
            probability = raw_logit_probability(document.metadata.get("rerank_score"))
            if probability is not None:
                probs.append(probability)
        return max(probs) if probs else None

    def _retrieve(
        self,
        query: str,
        filter_expr: str | None = None,
        transform: str | None = None,
    ) -> list[Document]:
        """Perform retrieval using the hybrid retriever (with optional transform)."""
        try:
            if transform == "multi_query":
                from core.retrieval.query_transform import multi_query_retrieve

                return multi_query_retrieve(
                    query,
                    self.retriever,
                    top_k=self._skill_config.top_k,
                    filter_expr=filter_expr,
                )
            if transform == "hyde":
                from core.retrieval.query_transform import hyde

                hyde_query = hyde(query)
                return self.retriever.retrieve(
                    hyde_query, top_k=self._skill_config.top_k, filter_expr=filter_expr
                )
        except Exception as e:  # noqa: BLE001 - transform is best-effort
            log.debug(f"query transform '{transform}' failed, direct retrieve: {e}")
        return self.retriever.retrieve(
            query, top_k=self._skill_config.top_k, filter_expr=filter_expr
        )

    @staticmethod
    def _extract_transform(context: SkillContext) -> str | None:
        """Which query transform to apply, if any (from shared_state).

        Recognised values: ``"hyde"`` | ``"multi_query"`` | None.
        """
        shared = getattr(context, "shared_state", None)
        if not shared:
            return None
        val = shared.get("query_transform")
        if isinstance(val, str) and val.strip() in ("hyde", "multi_query"):
            return val.strip()
        return None

    # --- HyDE / multi_query heuristic wiring (Stage B) ---------------------
    # Explicit shared_state["query_transform"] takes precedence (callers can
    # force a mode); otherwise a domain profile heuristic decides based on
    # query shape, so query transforms are finally exercised instead of dead
    # code. The regex/word-lists live in the active DomainProfile
    # (query_anchor_patterns / diagnostic_keywords / symptom_keywords) — no
    # domain literals are hardcoded here. ``_compiled_anchors`` caches the
    # compiled anchor regexes keyed by profile label (patterns rarely change).
    _anchor_cache: dict[str, list[re.Pattern]] = {}

    @classmethod
    def _anchor_patterns(cls, profile_label: str, patterns: list[str]) -> list[re.Pattern]:
        """Compile + cache the profile's anchor regexes (first call per label)."""
        cached = cls._anchor_cache.get(profile_label)
        if cached is not None:
            return cached
        compiled: list[re.Pattern] = []
        for p in patterns:
            try:
                compiled.append(re.compile(p, re.IGNORECASE))
            except re.error as e:  # noqa: BLE001 - bad profile pattern must not crash hot path
                log.warning(f"retrieve skill: invalid anchor pattern {p!r}: {e}")
        cls._anchor_cache[profile_label] = compiled
        return compiled

    @classmethod
    def _decide_transform(cls, context: SkillContext, query: str) -> str | None:
        """Pick a query transform: explicit shared_state first, else heuristic.

        The heuristic is sourced from the active DomainProfile:
        - anchor_patterns present (precise identifier / code) -> no transform
          (precise anchor, direct retrieval is enough, saves an LLM call).
        - diagnostic_keywords present (如何/为什么/原因) -> hyde (hypothetical
          doc closer to the answer distribution).
        - short abstract symptom (e.g. a short status phrase) -> multi_query
          (broaden recall across phrasings).
        - otherwise -> None (direct retrieval).

        Under the general profile, anchors/symptoms are empty and only the
        domain-neutral diagnostic verbs apply — so no aviation regex leaks.
        """
        explicit = cls._extract_transform(context)
        if explicit:
            return explicit
        if not query:
            return None
        q = query.strip()
        from core.prompts.domain_profile import get_active_profile

        profile = get_active_profile()
        if any(
            rx.search(q)
            for rx in cls._anchor_patterns(profile.profile_label, profile.query_anchor_patterns)
        ):
            return None
        if profile.diagnostic_keywords and any(k in q for k in profile.diagnostic_keywords):
            return "hyde"
        # Short, no diagnostic verb, but mentions a symptom -> abstract.
        if (
            len(q) <= 12
            and profile.symptom_keywords
            and any(k in q for k in profile.symptom_keywords)
        ):
            return "multi_query"
        return None

    async def _aretrieve(
        self,
        query: str,
        filter_expr: str | None = None,
        transform: str | None = None,
    ) -> list[Document]:
        """Async retrieval with optional query transform."""
        try:
            if transform == "multi_query":
                from core.retrieval.query_transform import amulti_query_retrieve

                return await amulti_query_retrieve(
                    query,
                    self.retriever,
                    top_k=self._skill_config.top_k,
                    filter_expr=filter_expr,
                )
            if transform == "hyde":
                from core.retrieval.query_transform import ahyde

                hyde_query = await ahyde(query)
                return await self.retriever.aretrieve(
                    hyde_query, top_k=self._skill_config.top_k, filter_expr=filter_expr
                )
        except Exception as e:  # noqa: BLE001
            log.debug(f"query transform '{transform}' failed, direct retrieve: {e}")
        return await self.retriever.aretrieve(
            query, top_k=self._skill_config.top_k, filter_expr=filter_expr
        )

    def _extract_query(self, context: SkillContext) -> str:
        """
        Extract the search query from context.

        Looks for:
        1. Tool call arguments from the agent node
        2. Last human message content (fallback)
        """
        messages = context.messages

        # Check last AI message for tool calls
        from langchain_core.messages import AIMessage

        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    for tc in tool_calls:
                        args = tc.get("args", {})
                        if "query" in args:
                            return args["query"]
                break

        # Fallback to last human message
        return context.question

    @staticmethod
    def _extract_filter(context: SkillContext) -> str | None:
        """
        Extract an optional Milvus filter expression from shared state.

        Callers (e.g. the chat router) can set ``shared_state["filter_expr"]``
        to restrict retrieval by source / model / chapter, e.g.
        ``source == "engine_manual"``.
        """
        shared = getattr(context, "shared_state", None)
        if not shared:
            return None
        expr = shared.get("filter_expr")
        if isinstance(expr, str) and expr.strip():
            return expr.strip()
        return None

    @staticmethod
    def _maybe_expand_parents(context: SkillContext, documents: list[Document]) -> list[Document]:
        """
        Expand small-chunk hits to their parent documents (small-to-big).

        Strategy (Stage B): expand is ON by default when chunks carry
        ``parent_id`` metadata — i.e. the index was built with parent_store
        wiring. Callers may force it OFF via ``shared_state["expand_parents"]=False``.
        Old indexes without parent_id are a no-op (backward compatible).
        """
        shared = getattr(context, "shared_state", None)
        # Explicit opt-out wins; absence or True both allow expand.
        if shared and shared.get("expand_parents") is False:
            return documents
        if not any(isinstance(d.metadata, dict) and d.metadata.get("parent_id") for d in documents):
            return documents  # old index without parent_id, no-op
        try:
            from documents.parent_store import expand_to_parents

            return expand_to_parents(documents)
        except Exception as e:  # noqa: BLE001
            log.debug(f"parent expansion skipped: {e}")
            return documents

    @staticmethod
    def _inject_memories(context: SkillContext, documents: list[Document]) -> list[Document]:
        """
        Prepend long-term memories (enriched by the memory hook) to the
        retrieved documents.

        The memory enrichment hook runs before the ``agent`` node and returns a
        ``shared_state["relevant_memories"]`` increment that is persisted into
        the graph state; this node (``retrieve``) then reads it back via its
        own ``SkillContext``. This prepends memory entries as high-priority
        context so correction memories (e.g. a corrected threshold value) influence
        generation.
        """
        shared = getattr(context, "shared_state", None)
        if not shared:
            return documents
        memories = shared.get("relevant_memories")
        if not memories:
            return documents
        try:
            memory_docs = [
                Document(
                    page_content=m.get("content", "") if isinstance(m, dict) else str(m),
                    metadata={
                        "source": "agent_memory",
                        "memory_type": (m.get("type") if isinstance(m, dict) else "fact"),
                        "score": 1.0,  # memories are high-trust
                        "is_memory": True,
                    },
                )
                for m in memories
                if isinstance(m, dict) and m.get("content")
            ]
            if not memory_docs:
                return documents
            # Memories first, then retrieved docs (de-duped by content prefix).
            existing_prefixes = {d.page_content[:80] for d in documents}
            deduped = [md for md in memory_docs if md.page_content[:80] not in existing_prefixes]
            return deduped + documents
        except Exception as e:  # noqa: BLE001
            log.debug(f"memory injection skipped: {e}")
            return documents

    def _build_result_messages(
        self,
        documents: list[Document],
        messages: list[BaseMessage],
        context: SkillContext,
    ) -> list[BaseMessage]:
        """
        Build result messages in the format expected by the graph.

        When return_as_tool_message is True, produces a ToolMessage
        that mirrors what LangGraph's ToolNode would emit.
        """
        if not self._skill_config.return_as_tool_message:
            # Return as plain content
            content = self._format_documents(documents)
            return [AIMessage(content=content)]

        # Find the tool_call_id from the last AI message with tool_calls
        tool_call_id = None
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    tool_call_id = tool_calls[0].get("id", "retriever_call")
                    break

        if tool_call_id is None:
            tool_call_id = "retriever_call"

        content = self._format_documents(documents)
        return [
            ToolMessage(
                content=content,
                tool_call_id=tool_call_id,
            )
        ]

    @staticmethod
    def _format_documents(documents: list[Document]) -> str:
        """
        Format documents into the context string used by GenerateNode.

        Delegates to the shared :mod:`core.retrieval.formatting` layer so the
        evidence-line format is defined in one place (previously this was
        duplicated across retrieve/generate/fast-mode).
        """
        from core.retrieval.formatting import format_documents

        context, _ = format_documents(documents)
        return context

    @staticmethod
    def _raw_to_documents(raw_results: list) -> list[Document]:
        """Convert MCP raw result dicts back to Document objects."""
        documents = []
        for item in raw_results:
            if isinstance(item, dict):
                doc = Document(
                    page_content=item.get("content", ""),
                    metadata={
                        "source": item.get("source", "unknown"),
                        "title": item.get("title", "unknown"),
                        "score": item.get("score"),
                        # Restore parent_id so _maybe_expand_parents works over
                        # the MCP path (critic F-RB-01: server now carries it).
                        **({"parent_id": item["parent_id"]} if item.get("parent_id") else {}),
                    },
                )
                documents.append(doc)
            elif isinstance(item, Document):
                documents.append(item)
        return documents

    @classmethod
    def _raw_workflow_documents(
        cls,
        raw_results: Any,
    ) -> tuple[list[Document], dict[str, Any] | None]:
        if isinstance(raw_results, dict):
            documents = cls._raw_to_documents(raw_results.get("documents", []))
            diagnostics = raw_results.get("diagnostics")
            return documents, diagnostics if isinstance(diagnostics, dict) else None
        return cls._raw_to_documents(raw_results if isinstance(raw_results, list) else []), None

    def health_check(self) -> dict[str, Any]:
        """Check if retriever is healthy."""
        try:
            retriever = self.retriever
            return {
                "name": self.name,
                "healthy": True,
                "retriever_type": type(retriever).__name__,
            }
        except Exception as e:
            return {"name": self.name, "healthy": False, "error": str(e)}
