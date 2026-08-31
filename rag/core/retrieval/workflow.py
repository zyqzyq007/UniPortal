"""Shared adaptive/corrective retrieval workflow for every generation entry."""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, replace
from typing import Any

from langchain_core.documents import Document

from core.retrieval.authority import rank_by_authority
from core.retrieval.corrective import CorrectiveDecision, EvidenceState, evaluate_evidence
from core.retrieval.filter_scope import FilterKind, FilterScope
from core.retrieval.planner import RetrievalPlan, RetrievalPlanner, apply_channel_health

__all__ = [
    "RetrievalWorkflow",
    "RetrievalWorkflowResult",
    "get_retrieval_workflow",
    "reset_retrieval_workflow",
    "retrieval_workflow_enabled",
]


@dataclass(frozen=True)
class RetrievalWorkflowResult:
    documents: list[Document]
    plan: RetrievalPlan
    state: EvidenceState
    should_generate: bool
    retry_action: str | None
    degraded: bool
    diagnostics: dict[str, Any]


class RetrievalWorkflow:
    def __init__(self, retriever: Any | None = None, planner: RetrievalPlanner | None = None):
        self._retriever = retriever
        self._planner = planner or RetrievalPlanner()

    def close(self) -> None:
        """Release references owned by the workflow singleton.

        The hybrid retriever has its own process singleton and lifecycle closer,
        so this method deliberately does not close an injected/shared retriever.
        """
        self._retriever = None

    @property
    def retriever(self):
        if self._retriever is None:
            from core.retrieval.hybrid_retriever import get_hybrid_retriever

            self._retriever = get_hybrid_retriever()
        return self._retriever

    def retrieve(
        self,
        query: str,
        *,
        filter_expr: str | None = None,
        final_k: int = 5,
        channel_health: dict[str, bool] | None = None,
    ) -> RetrievalWorkflowResult:
        started = time.perf_counter()
        scope = FilterScope.parse(filter_expr)
        effective_health = self._effective_channel_health(channel_health)
        plan = self._planner.plan(query, final_k=final_k, channel_health=effective_health)
        if scope.kind is FilterKind.INVALID:
            return self._result(
                [],
                plan,
                CorrectiveDecision(
                    EvidenceState.EMPTY,
                    True,
                    None,
                    False,
                    None,
                    reasons=("invalid_filter",),
                ),
                scope,
                None,
                started,
            )

        if _no_active_evidence_channels(plan):
            terminal_plan = replace(plan, facets=(), query_transform=None, retry_budget=0)
            documents = self._call_retriever(
                query,
                filter_expr,
                terminal_plan,
                _request_identity(terminal_plan, "no_active_channel", 0),
            )
            return self._result(
                documents,
                terminal_plan,
                CorrectiveDecision(
                    EvidenceState.EMPTY,
                    True,
                    None,
                    False,
                    None,
                    reasons=("no_active_channel",),
                ),
                scope,
                None,
                started,
            )

        first_identity = _request_identity(plan, "initial", 0)
        documents = self._retrieve_once(query, filter_expr, plan, first_identity)
        documents = rank_by_authority(documents)
        decision = evaluate_evidence(documents, plan, retry_index=0)
        action_used = decision.retry_action
        active_plan = plan

        if action_used is not None:
            retry_plan = apply_channel_health(plan.for_retry(action_used), effective_health)
            retry_identity = _request_identity(retry_plan, action_used, 1)
            retry_documents = self._retrieve_once(
                query,
                filter_expr,
                retry_plan,
                retry_identity,
            )
            if retry_documents:
                documents = rank_by_authority(retry_documents)
            active_plan = retry_plan
            decision = evaluate_evidence(
                documents, active_plan, retry_index=active_plan.retry_budget
            )

        return self._result(
            documents,
            active_plan,
            decision,
            scope,
            action_used,
            started,
        )

    async def aretrieve(
        self,
        query: str,
        *,
        filter_expr: str | None = None,
        final_k: int = 5,
        channel_health: dict[str, bool] | None = None,
    ) -> RetrievalWorkflowResult:
        started = time.perf_counter()
        scope = FilterScope.parse(filter_expr)
        effective_health = self._effective_channel_health(channel_health)
        plan = self._planner.plan(query, final_k=final_k, channel_health=effective_health)
        if scope.kind is FilterKind.INVALID:
            return self._result(
                [],
                plan,
                CorrectiveDecision(
                    EvidenceState.EMPTY,
                    True,
                    None,
                    False,
                    None,
                    reasons=("invalid_filter",),
                ),
                scope,
                None,
                started,
            )
        if _no_active_evidence_channels(plan):
            terminal_plan = replace(plan, facets=(), query_transform=None, retry_budget=0)
            documents = await self._call_aretriever(
                query,
                filter_expr,
                terminal_plan,
                _request_identity(terminal_plan, "no_active_channel", 0),
            )
            return self._result(
                documents,
                terminal_plan,
                CorrectiveDecision(
                    EvidenceState.EMPTY,
                    True,
                    None,
                    False,
                    None,
                    reasons=("no_active_channel",),
                ),
                scope,
                None,
                started,
            )
        first_identity = _request_identity(plan, "initial", 0)
        documents = await self._aretrieve_once(query, filter_expr, plan, first_identity)
        documents = rank_by_authority(documents)
        decision = evaluate_evidence(documents, plan, retry_index=0)
        action_used = decision.retry_action
        active_plan = plan
        if action_used is not None:
            retry_plan = apply_channel_health(plan.for_retry(action_used), effective_health)
            retry_identity = _request_identity(retry_plan, action_used, 1)
            retry_documents = await self._aretrieve_once(
                query,
                filter_expr,
                retry_plan,
                retry_identity,
            )
            if retry_documents:
                documents = rank_by_authority(retry_documents)
            active_plan = retry_plan
            decision = evaluate_evidence(
                documents, active_plan, retry_index=active_plan.retry_budget
            )
        return self._result(
            documents,
            active_plan,
            decision,
            scope,
            action_used,
            started,
        )

    def _effective_channel_health(
        self,
        provided: dict[str, bool] | None,
    ) -> dict[str, bool]:
        health = dict(provided or {})
        try:
            policy = self.retriever.active_policy()
        except (AttributeError, TypeError):
            return health
        policy_values = {
            "dense": policy.dense,
            "sparse": policy.sparse,
            "graph": policy.graph,
            "mmr": policy.mmr,
            "time_decay": policy.time_decay,
        }
        for key, available in policy_values.items():
            health[key] = bool(health.get(key, True) and available)
        return health

    def _retrieve_once(
        self,
        query: str,
        filter_expr: str | None,
        plan: RetrievalPlan,
        retry_identity: str,
    ) -> list[Document]:
        if plan.facets:
            facet_plan = replace(plan, facets=(), query_transform=None)
            combined: list[Document] = []
            for facet in plan.facets:
                for document in self._call_retriever(
                    facet,
                    filter_expr,
                    facet_plan,
                    f"{retry_identity}:{_short_hash(facet)}",
                ):
                    metadata = dict(document.metadata)
                    matched = metadata.get("matched_facets", ())
                    if isinstance(matched, str):
                        matched = (matched,)
                    metadata["matched_facets"] = list(dict.fromkeys([*matched, facet]))
                    combined.append(Document(page_content=document.page_content, metadata=metadata))
            from core.retrieval.selector import select_evidence

            return select_evidence(
                combined,
                final_k=plan.final_k,
                selection_k=plan.selection_k,
                facets=plan.facets,
            )
        queries = self._transformed_queries(query, plan)
        if len(queries) > 1:
            lists = [
                self._call_retriever(
                    variant,
                    filter_expr,
                    replace(plan, query_transform=None),
                    f"{retry_identity}:{index}",
                )
                for index, variant in enumerate(queries)
            ]
            from core.retrieval.query_transform import _rrf_fuse

            return _rrf_fuse(lists)[: plan.final_k]
        return self._call_retriever(queries[0], filter_expr, plan, retry_identity)

    def _call_retriever(
        self,
        query: str,
        filter_expr: str | None,
        plan: RetrievalPlan,
        retry_identity: str,
    ) -> list[Document]:
        try:
            documents = self.retriever.retrieve(
                query,
                top_k=plan.final_k,
                filter_expr=filter_expr,
                plan=plan,
                retry_identity=retry_identity,
            )
        except TypeError as exc:
            if "unexpected keyword" not in str(exc):
                raise
            documents = self.retriever.retrieve(
                query,
                top_k=plan.final_k,
                filter_expr=filter_expr,
            )
        return self._augment_optional_channels(query, filter_expr, plan, documents)

    async def _aretrieve_once(
        self,
        query: str,
        filter_expr: str | None,
        plan: RetrievalPlan,
        retry_identity: str,
    ) -> list[Document]:
        import asyncio

        if plan.facets:
            facet_plan = replace(plan, facets=(), query_transform=None)
            gathered = await asyncio.gather(
                *(
                    self._call_aretriever(
                        facet,
                        filter_expr,
                        facet_plan,
                        f"{retry_identity}:{_short_hash(facet)}",
                    )
                    for facet in plan.facets
                ),
                return_exceptions=True,
            )
            combined: list[Document] = []
            for facet, result in zip(plan.facets, gathered):
                if isinstance(result, Exception):
                    continue
                for document in result:
                    metadata = dict(document.metadata)
                    matched = metadata.get("matched_facets", ())
                    if isinstance(matched, str):
                        matched = (matched,)
                    metadata["matched_facets"] = list(dict.fromkeys([*matched, facet]))
                    combined.append(Document(page_content=document.page_content, metadata=metadata))
            from core.retrieval.selector import select_evidence

            return select_evidence(
                combined,
                final_k=plan.final_k,
                selection_k=plan.selection_k,
                facets=plan.facets,
            )
        queries = self._transformed_queries(query, plan)
        gathered = await asyncio.gather(
            *(
                self._call_aretriever(
                    variant,
                    filter_expr,
                    replace(plan, query_transform=None),
                    f"{retry_identity}:{index}",
                )
                for index, variant in enumerate(queries)
            ),
            return_exceptions=True,
        )
        lists = [result for result in gathered if not isinstance(result, Exception)]
        if len(lists) > 1:
            from core.retrieval.query_transform import _rrf_fuse

            return _rrf_fuse(lists)[: plan.final_k]
        return lists[0] if lists else []

    async def _call_aretriever(
        self,
        query: str,
        filter_expr: str | None,
        plan: RetrievalPlan,
        retry_identity: str,
    ) -> list[Document]:
        import asyncio

        if not hasattr(self.retriever, "aretrieve"):
            return await asyncio.to_thread(
                self._call_retriever,
                query,
                filter_expr,
                plan,
                retry_identity,
            )
        try:
            documents = await self.retriever.aretrieve(
                query,
                top_k=plan.final_k,
                filter_expr=filter_expr,
                plan=plan,
                retry_identity=retry_identity,
            )
        except TypeError as exc:
            if "unexpected keyword" not in str(exc):
                raise
            documents = await self.retriever.aretrieve(
                query,
                top_k=plan.final_k,
                filter_expr=filter_expr,
            )
        return await asyncio.to_thread(
            self._augment_optional_channels,
            query,
            filter_expr,
            plan,
            documents,
        )

    @staticmethod
    def _augment_optional_channels(
        query: str,
        filter_expr: str | None,
        plan: RetrievalPlan,
        documents: list[Document],
    ) -> list[Document]:
        channels: list[tuple[list[Document], float]] = [
            (
                documents,
                max(0.0, plan.dense_weight + plan.sparse_weight + plan.graph_weight),
            )
        ]
        if plan.use_raptor and plan.summary_weight > 0:
            try:
                from core.retrieval.raptor_store import get_raptor_store

                result = get_raptor_store().retrieve(
                    query,
                    top_k=plan.rerank_k,
                    filter_expr=filter_expr,
                )
                if result.documents:
                    channels.append((result.documents, plan.summary_weight))
            except Exception:
                pass
        if plan.use_visual and plan.visual_weight > 0:
            try:
                from core.retrieval.visual_retriever import get_visual_retriever

                result = get_visual_retriever().retrieve(
                    query,
                    top_k=plan.rerank_k,
                    filter_expr=filter_expr,
                )
                if result.documents:
                    channels.append((result.documents, plan.visual_weight))
            except Exception:
                pass
        if len(channels) == 1:
            return documents
        fused = _weighted_document_rrf(channels)
        try:
            from core.retrieval.selector import select_evidence

            return select_evidence(
                fused,
                final_k=plan.final_k,
                selection_k=plan.selection_k,
                facets=plan.facets,
            )
        except Exception:
            return fused[: plan.final_k]

    @staticmethod
    def _transformed_queries(query: str, plan: RetrievalPlan) -> list[str]:
        if plan.query_transform == "hyde":
            try:
                from core.retrieval.query_transform import hyde

                return [hyde(query)]
            except Exception:
                return [query]
        if plan.query_transform == "multi_query":
            try:
                from core.retrieval.query_transform import multi_query_expand

                variants = multi_query_expand(query)
                return variants or [query]
            except Exception:
                return [query]
        return [query]

    @staticmethod
    def _result(
        documents: list[Document],
        plan: RetrievalPlan,
        decision: CorrectiveDecision,
        scope: FilterScope,
        action_used: str | None,
        started: float,
    ) -> RetrievalWorkflowResult:
        degraded = bool(plan.degraded or decision.degraded or scope.kind is FilterKind.INVALID)
        channel_counts = _channel_counts(documents)
        optional_channel_status = {
            "colbert": (
                "contributed"
                if any((document.metadata or {}).get("colbert_applied") for document in documents)
                else "unavailable_or_no_match"
            )
            if plan.use_colbert
            else "disabled",
            "raptor": (
                "contributed" if channel_counts.get("raptor", 0) else "unavailable_or_no_match"
            )
            if plan.use_raptor
            else "disabled",
            "ppr": (
                "contributed"
                if any(
                    (document.metadata or {}).get("graph_mode") == "ppr" for document in documents
                )
                else "unavailable_or_no_match"
            )
            if plan.use_ppr
            else "disabled",
            "visual": (
                "contributed" if channel_counts.get("visual", 0) else "unavailable_or_no_match"
            )
            if plan.use_visual
            else "disabled",
        }
        try:
            from core.retrieval.hybrid_retriever import get_current_retrieval_execution_info

            execution = get_current_retrieval_execution_info()
        except Exception:
            execution = None
        diagnostics = {
            "plan": plan.to_metadata(),
            "state": decision.state.value,
            "should_generate": decision.should_generate,
            "retry_action": action_used,
            "degraded": degraded,
            "document_count": len(documents),
            "channel_counts": channel_counts,
            "optional_channel_status": optional_channel_status,
            "primary_channel_status": (execution.channel_status if execution is not None else {}),
            "retrieval_identity": execution.identity if execution is not None else None,
            "retrieval_cache_hit": execution.cache_hit if execution is not None else False,
            "uncovered_facets": list(decision.uncovered_facets),
            "filter_kind": scope.kind.value,
            "filter_fingerprint": scope.fingerprint,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }
        return RetrievalWorkflowResult(
            documents=documents,
            plan=plan,
            state=decision.state,
            should_generate=decision.should_generate,
            retry_action=action_used,
            degraded=degraded,
            diagnostics=diagnostics,
        )


def _request_identity(plan: RetrievalPlan, action: str, retry_index: int) -> str:
    raw = f"{plan.fingerprint}|{action}|{retry_index}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _no_active_evidence_channels(plan: RetrievalPlan) -> bool:
    return not any(
        weight > 0
        for weight in (
            plan.dense_weight,
            plan.sparse_weight,
            plan.graph_weight,
            plan.summary_weight,
            plan.visual_weight,
        )
    )


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _weighted_document_rrf(
    channels: list[tuple[list[Document], float]],
    *,
    rrf_k: int = 60,
) -> list[Document]:
    total_weight = sum(weight for _documents, weight in channels if weight > 0) or 1.0
    folded: dict[str, tuple[float, int, Document]] = {}
    insertion = 0
    for documents, weight in channels:
        if weight <= 0:
            continue
        normalized_weight = weight / total_weight
        for rank, document in enumerate(documents, 1):
            metadata = document.metadata or {}
            identity = "|".join(
                (
                    str(metadata.get("source", "")),
                    str(metadata.get("parent_id", "")),
                    hashlib.sha1(document.page_content.encode("utf-8")).hexdigest()[:16],
                )
            )
            score = normalized_weight / (rrf_k + rank)
            if identity in folded:
                previous, order, selected = folded[identity]
                folded[identity] = (previous + score, order, selected)
            else:
                folded[identity] = (score, insertion, document)
                insertion += 1
    ordered = sorted(folded.values(), key=lambda item: (-item[0], item[1]))
    output: list[Document] = []
    for score, _order, document in ordered:
        metadata = dict(document.metadata)
        metadata["fusion_score"] = score
        metadata.setdefault("score", score)
        output.append(Document(page_content=document.page_content, metadata=metadata))
    return output


def _channel_counts(documents: list[Document]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for document in documents:
        channel = str((document.metadata or {}).get("retrieval_source") or "hybrid")
        counts[channel] = counts.get(channel, 0) + 1
    return counts


_workflow: RetrievalWorkflow | None = None


def get_retrieval_workflow() -> RetrievalWorkflow:
    global _workflow
    if _workflow is None:
        _workflow = RetrievalWorkflow()
    return _workflow


def reset_retrieval_workflow() -> None:
    """Close and clear the process-wide workflow singleton."""
    global _workflow
    previous = _workflow
    _workflow = None
    if previous is not None:
        try:
            previous.close()
        except Exception:
            pass


def retrieval_workflow_enabled() -> bool:
    return os.getenv("RETRIEVAL_WORKFLOW_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
