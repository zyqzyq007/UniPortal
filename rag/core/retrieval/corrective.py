"""Deterministic evidence-state evaluation with bounded changed retries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from langchain_core.documents import Document

from core.retrieval.authority import structured_version_conflict
from core.retrieval.planner import QueryType, RetrievalPlan
from core.retrieval.scoring import probability, raw_logit_probability

__all__ = ["CorrectiveDecision", "EvidenceState", "evaluate_evidence"]


class EvidenceState(str, Enum):
    ACCEPT = "accept"
    WEAK = "weak"
    CONFLICT = "conflict"
    EMPTY = "empty"


@dataclass(frozen=True)
class CorrectiveDecision:
    state: EvidenceState
    degraded: bool
    retry_action: str | None
    should_generate: bool
    max_relevance: float | None
    uncovered_facets: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


def evaluate_evidence(
    documents: list[Document],
    plan: RetrievalPlan,
    *,
    retry_index: int,
    relevance_threshold: float = 0.35,
) -> CorrectiveDecision:
    if not documents:
        return _decision(EvidenceState.EMPTY, plan, retry_index, None, reasons=("no_evidence",))
    if structured_version_conflict(documents):
        return _decision(
            EvidenceState.CONFLICT,
            plan,
            retry_index,
            _max_relevance(documents),
            reasons=("structured_version_conflict",),
        )

    uncovered = _uncovered_facets(documents, plan.facets)
    relevance = _max_relevance(documents)
    if relevance is None:
        return _decision(
            EvidenceState.WEAK,
            plan,
            retry_index,
            None,
            uncovered,
            degraded=True,
            reasons=("scoring_unavailable",),
        )
    if relevance < relevance_threshold or uncovered:
        reasons = ("low_relevance",) if relevance < relevance_threshold else ("facet_gap",)
        return _decision(
            EvidenceState.WEAK,
            plan,
            retry_index,
            relevance,
            uncovered,
            reasons=reasons,
        )
    return CorrectiveDecision(EvidenceState.ACCEPT, False, None, True, relevance, (), ())


def _decision(
    state: EvidenceState,
    plan: RetrievalPlan,
    retry_index: int,
    max_relevance: float | None,
    uncovered_facets: tuple[str, ...] = (),
    *,
    degraded: bool = False,
    reasons: tuple[str, ...] = (),
) -> CorrectiveDecision:
    retry_action = _retry_action(plan) if retry_index < plan.retry_budget else None
    return CorrectiveDecision(
        state=state,
        degraded=degraded,
        retry_action=retry_action,
        should_generate=False,
        max_relevance=max_relevance,
        uncovered_facets=uncovered_facets,
        reasons=reasons,
    )


def _retry_action(plan: RetrievalPlan) -> str:
    if plan.query_type is QueryType.EXACT:
        return "increase_sparse_budget"
    if plan.query_type in {QueryType.COMPARISON, QueryType.MULTI_CONSTRAINT}:
        return "retrieve_missing_facets"
    if plan.query_type is QueryType.MULTI_HOP:
        return "enable_graph_ppr"
    if plan.query_type is QueryType.GLOBAL_SUMMARY:
        return "enable_raptor"
    if plan.query_type is QueryType.VISUAL:
        return "enable_visual_or_ocr"
    return "multi_query"


def _max_relevance(documents: list[Document]) -> float | None:
    values = []
    for document in documents:
        metadata = document.metadata
        direct = probability(metadata.get("rerank_probability"))
        if direct is not None:
            values.append(direct)
            continue
        grade = probability(metadata.get("grade_score"))
        if grade is not None:
            values.append(grade)
            continue
        if metadata.get("rerank_applied") is True:
            rerank = raw_logit_probability(metadata.get("rerank_score"))
            if rerank is not None:
                values.append(rerank)
    return max(values) if values else None


def _uncovered_facets(documents: list[Document], facets: tuple[str, ...]) -> tuple[str, ...]:
    covered = set()
    for document in documents:
        matched = document.metadata.get("matched_facets", ())
        if isinstance(matched, str):
            matched = (matched,)
        covered.update(str(value) for value in matched)
    return tuple(facet for facet in facets if facet not in covered)
