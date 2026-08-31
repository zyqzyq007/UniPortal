"""Deterministic, bounded retrieval planning for closed-corpus RAG."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Any

from utils.log_utils import log

__all__ = [
    "QueryType",
    "RetrievalPlan",
    "RetrievalPlanner",
    "apply_channel_health",
    "safe_default_plan",
]


class QueryType(str, Enum):
    EXACT = "exact"
    SEMANTIC = "semantic"
    PROCEDURE = "procedure"
    COMPARISON = "comparison"
    MULTI_CONSTRAINT = "multi_constraint"
    MULTI_HOP = "multi_hop"
    GLOBAL_SUMMARY = "global_summary"
    VISUAL = "visual"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class RetrievalPlan:
    query_type: QueryType
    dense_weight: float
    sparse_weight: float
    graph_weight: float
    summary_weight: float
    visual_weight: float
    candidate_k: int
    rerank_k: int
    selection_k: int
    final_k: int
    use_mmr: bool
    expand_parents: bool
    use_time_decay: bool
    query_transform: str | None
    retry_budget: int
    facets: tuple[str, ...] = ()
    use_colbert: bool = False
    use_raptor: bool = False
    use_ppr: bool = False
    use_visual: bool = False
    degraded: bool = False

    @property
    def fingerprint(self) -> str:
        raw = json.dumps(_serializable_plan(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_metadata(self) -> dict[str, Any]:
        return {
            "query_type": self.query_type.value,
            "weights": {
                "dense": self.dense_weight,
                "sparse": self.sparse_weight,
                "graph": self.graph_weight,
                "summary": self.summary_weight,
                "visual": self.visual_weight,
            },
            "budgets": {
                "candidate_k": self.candidate_k,
                "rerank_k": self.rerank_k,
                "selection_k": self.selection_k,
                "final_k": self.final_k,
                "retry_budget": self.retry_budget,
            },
            "use_mmr": self.use_mmr,
            "expand_parents": self.expand_parents,
            "query_transform": self.query_transform,
            "facet_count": len(self.facets),
            "optional_channels": {
                "colbert": self.use_colbert,
                "raptor": self.use_raptor,
                "ppr": self.use_ppr,
                "visual": self.use_visual,
            },
            "degraded": self.degraded,
            "fingerprint": self.fingerprint,
        }

    def for_retry(self, action: str) -> RetrievalPlan:
        candidate = min(200, max(self.candidate_k + self.final_k, self.candidate_k * 2))
        updates: dict[str, Any] = {"candidate_k": candidate, "rerank_k": candidate}
        if action == "increase_sparse_budget":
            updates["sparse_weight"] = min(0.8, self.sparse_weight + 0.15)
            updates["dense_weight"] = max(0.2, self.dense_weight - 0.15)
        elif action == "enable_graph_ppr":
            updates["use_ppr"] = True
            updates["graph_weight"] = max(self.graph_weight, 0.3)
        elif action == "enable_raptor":
            updates["use_raptor"] = True
            updates["summary_weight"] = max(self.summary_weight, 0.35)
        elif action == "enable_visual_or_ocr":
            updates["use_visual"] = self.use_visual
            updates["visual_weight"] = max(self.visual_weight, 0.4 if self.use_visual else 0.0)
        elif action == "multi_query":
            updates["query_transform"] = "multi_query"
        return replace(self, **updates)


class RetrievalPlanner:
    """Pure rule planner; failures return a conservative dense+sparse plan."""

    def plan(
        self,
        query: str,
        *,
        final_k: int = 5,
        channel_health: dict[str, bool] | None = None,
    ) -> RetrievalPlan:
        try:
            query_type = self._classify(query)
            facets = self._facets(query, query_type)
            plan = self._build(
                query_type,
                facets,
                max(1, min(int(final_k), 200)),
                channel_health,
            )
            return apply_channel_health(plan, channel_health)
        except Exception as exc:
            log.warning(f"Retrieval planner degraded to safe default: {type(exc).__name__}")
            return apply_channel_health(
                safe_default_plan(final_k=final_k, degraded=True),
                channel_health,
            )

    def _classify(self, query: str) -> QueryType:
        text = (query or "").strip()
        folded = text.casefold()
        if len(text) < 2:
            return QueryType.AMBIGUOUS
        if re.search(r"(?:图\s*\d+|表\s*\d+|截图|曲线|图像|diagram|chart|figure|image)", folded):
            return QueryType.VISUAL
        if re.search(
            r"(?:总结|概述|综述|整份|全文|核心主题|overall|summari[sz]e|overview)", folded
        ):
            return QueryType.GLOBAL_SUMMARY
        if re.search(r"(?:比较|对比|区别|差异|\bvs\.?\b|versus|difference between)", folded):
            return QueryType.COMPARISON
        if re.search(r"(?:如何|怎样|步骤|流程|操作方法|how to|steps? to|procedure)", folded):
            return QueryType.PROCEDURE
        if _looks_exact(text):
            return QueryType.EXACT
        if re.search(r"(?:两跳|三跳|关系链|关联路径|通过.+影响|multi[- ]?hop)", folded):
            return QueryType.MULTI_HOP
        if len(re.findall(r"(?:并且|同时|且|以及|\band\b)", folded)) >= 3:
            return QueryType.MULTI_CONSTRAINT
        return QueryType.SEMANTIC

    def _facets(self, query: str, query_type: QueryType) -> tuple[str, ...]:
        if query_type is not QueryType.COMPARISON and query_type is not QueryType.MULTI_CONSTRAINT:
            return ()
        text = re.sub(r"^\s*(?:请)?(?:比较|对比)\s*", "", query.strip(), flags=re.IGNORECASE)
        parts = re.split(
            r"\s+(?:和|与|及|vs\.?|versus|and)\s+", text, maxsplit=3, flags=re.IGNORECASE
        )
        if len(parts) == 1:
            parts = re.split(r"(?:和|与|及|、|，|,)", text, maxsplit=3)
        return tuple(dict.fromkeys(part.strip(" ：:") for part in parts if part.strip()))[:4]

    def _build(
        self,
        query_type: QueryType,
        facets: tuple[str, ...],
        final_k: int,
        channel_health: dict[str, bool] | None,
    ) -> RetrievalPlan:
        health = channel_health or {}
        candidate = max(10, final_k * 2)
        common = dict(
            query_type=query_type,
            candidate_k=candidate,
            rerank_k=final_k,
            selection_k=final_k,
            final_k=final_k,
            expand_parents=True,
            use_time_decay=False,
            retry_budget=1,
            facets=facets,
            use_colbert=_flag("COLBERT_RERANK_ENABLED") and health.get("colbert", True),
        )
        expanded = {
            **common,
            "candidate_k": max(12, final_k * 3),
            "rerank_k": max(final_k * 2, 8),
        }
        if query_type is QueryType.EXACT:
            return RetrievalPlan(
                dense_weight=0.3,
                sparse_weight=0.7,
                graph_weight=0.0,
                summary_weight=0.0,
                visual_weight=0.0,
                use_mmr=False,
                query_transform=None,
                **common,
            )
        if query_type is QueryType.PROCEDURE:
            return RetrievalPlan(
                dense_weight=0.5,
                sparse_weight=0.5,
                graph_weight=0.0,
                summary_weight=0.0,
                visual_weight=0.0,
                use_mmr=True,
                query_transform="hyde" if _flag("QUERY_TRANSFORM_ENABLED") else None,
                **common,
            )
        if query_type in {QueryType.COMPARISON, QueryType.MULTI_CONSTRAINT}:
            graph_enabled = _flag("GRAPH_RAG_ENABLED") and health.get("graph", True)
            return RetrievalPlan(
                dense_weight=0.45,
                sparse_weight=0.4,
                graph_weight=0.15 if graph_enabled else 0.0,
                summary_weight=0.0,
                visual_weight=0.0,
                use_mmr=True,
                query_transform=None,
                **expanded,
            )
        if query_type is QueryType.MULTI_HOP:
            enabled = _flag("GRAPH_PPR_ENABLED") and health.get("ppr", True)
            return RetrievalPlan(
                dense_weight=0.4,
                sparse_weight=0.3,
                graph_weight=0.3 if enabled else 0.0,
                summary_weight=0.0,
                visual_weight=0.0,
                use_mmr=True,
                query_transform=None,
                use_ppr=enabled,
                **expanded,
            )
        if query_type is QueryType.GLOBAL_SUMMARY:
            enabled = _flag("RAPTOR_ENABLED") and health.get("raptor", True)
            return RetrievalPlan(
                dense_weight=0.4,
                sparse_weight=0.25,
                graph_weight=0.0,
                summary_weight=0.35 if enabled else 0.0,
                visual_weight=0.0,
                use_mmr=True,
                query_transform=None,
                use_raptor=enabled,
                **expanded,
            )
        if query_type is QueryType.VISUAL:
            enabled = _flag("COLPALI_ENABLED") and health.get("visual", True)
            return RetrievalPlan(
                dense_weight=0.4,
                sparse_weight=0.3,
                graph_weight=0.0,
                summary_weight=0.0,
                visual_weight=0.3 if enabled else 0.0,
                use_mmr=False,
                query_transform=None,
                use_visual=enabled,
                **common,
            )
        return RetrievalPlan(
            dense_weight=0.5,
            sparse_weight=0.5,
            graph_weight=0.0,
            summary_weight=0.0,
            visual_weight=0.0,
            use_mmr=True,
            query_transform=None,
            degraded=query_type is QueryType.AMBIGUOUS,
            **common,
        )


def safe_default_plan(final_k: int = 5, degraded: bool = False) -> RetrievalPlan:
    final = max(1, min(int(final_k), 200))
    return RetrievalPlan(
        query_type=QueryType.SEMANTIC,
        dense_weight=0.5,
        sparse_weight=0.5,
        graph_weight=0.0,
        summary_weight=0.0,
        visual_weight=0.0,
        candidate_k=max(10, final * 2),
        rerank_k=final,
        selection_k=final,
        final_k=final,
        use_mmr=True,
        expand_parents=True,
        use_time_decay=False,
        query_transform=None,
        retry_budget=1,
        degraded=degraded,
    )


def apply_channel_health(
    plan: RetrievalPlan,
    channel_health: dict[str, bool] | None,
) -> RetrievalPlan:
    health = channel_health or {}
    dense = health.get("dense", True)
    sparse = health.get("sparse", True)
    graph = health.get("graph", True)
    raptor = health.get("raptor", True)
    visual = health.get("visual", True)
    ppr = health.get("ppr", graph)
    updates = {
        "dense_weight": plan.dense_weight if dense else 0.0,
        "sparse_weight": plan.sparse_weight if sparse else 0.0,
        "graph_weight": plan.graph_weight if graph else 0.0,
        "summary_weight": plan.summary_weight if raptor else 0.0,
        "visual_weight": plan.visual_weight if visual else 0.0,
        "use_mmr": bool(plan.use_mmr and health.get("mmr", True) and dense),
        "use_time_decay": bool(plan.use_time_decay and health.get("time_decay", True)),
        "use_colbert": bool(plan.use_colbert and health.get("colbert", True)),
        "use_raptor": bool(plan.use_raptor and raptor),
        "use_ppr": bool(plan.use_ppr and ppr),
        "use_visual": bool(plan.use_visual and visual),
    }
    no_active_evidence = not any(
        (
            updates["dense_weight"] > 0,
            updates["sparse_weight"] > 0,
            updates["graph_weight"] > 0,
            updates["summary_weight"] > 0,
            updates["visual_weight"] > 0,
        )
    )
    updates["degraded"] = bool(plan.degraded or no_active_evidence)
    return replace(plan, **updates)


def _looks_exact(query: str) -> bool:
    return bool(
        re.search(r"[A-Z]{2,}[A-Z0-9]*(?:[-_.:/][A-Z0-9]+)+", query)
        or re.search(r"\b(?:0x)?[0-9A-F]{6,}\b", query, re.IGNORECASE)
    )


def _flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


def _serializable_plan(plan: RetrievalPlan) -> dict[str, Any]:
    values = asdict(plan)
    values["query_type"] = plan.query_type.value
    return values
