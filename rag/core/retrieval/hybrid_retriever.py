"""
Hybrid Retriever for Enterprise RAG Platform

Combines dense (vector) and sparse (BM25) retrieval with RRF fusion.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import time
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import Any

from langchain_core.documents import Document

from core.retrieval.bm25_retriever import BM25Retriever
from documents.milvus_db import MilvusManager
from utils.env_utils import (
    GRAPH_RAG_ENABLED,
    GRAPH_RAG_TOP_K,
    GRAPH_RAG_WEIGHT,
    MILVUS_SPARSE_INDEX,
    RERANKER_CANDIDATE_TOP_K,
    RERANKER_ENABLED,
    RERANKER_TOP_K,
)
from utils.log_utils import log

__all__ = [
    "ActiveChannelPolicy",
    "ChannelExecution",
    "HybridRetriever",
    "HybridRetrieverConfig",
    "HybridRetrievalOutcome",
    "RetrievalBudgets",
    "RetrievalExecutionInfo",
    "get_current_retrieval_execution_info",
]


def _retrieval_cache_enabled() -> bool:
    """Env-gated retrieval-result cache (default on)."""
    import os

    return os.getenv("RETRIEVAL_CACHE_ENABLED", "true").lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    """Read a float env var (F4 parameterisation — algorithm constants tunable)."""
    import os

    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    """Read an int env var (F4 parameterisation)."""
    import os

    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    import os

    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class HybridRetrieverConfig:
    """Configuration for hybrid retriever.

    F4: algorithm constants (RRF k, MMR lambda, dense/sparse weights) are now
    env-tunable so the eval flywheel can calibrate them without code changes.
    Defaults match the pre-F4 hardcoded values (byte-for-byte identical when
    the env vars are unset).
    """

    # Dense retrieval
    enable_dense: bool = field(default_factory=lambda: _env_bool("RETRIEVAL_DENSE_ENABLED", True))
    dense_weight: float = field(default_factory=lambda: _env_float("DENSE_WEIGHT", 0.5))
    dense_top_k: int = field(
        default_factory=lambda: _env_int(
            "RETRIEVAL_LEG_TOP_K",
            RERANKER_CANDIDATE_TOP_K if RERANKER_ENABLED else 5,
        )
    )

    # Sparse retrieval (BM25)
    enable_sparse: bool = field(default_factory=lambda: _env_bool("RETRIEVAL_SPARSE_ENABLED", True))
    sparse_weight: float = field(default_factory=lambda: _env_float("SPARSE_WEIGHT", 0.5))
    sparse_top_k: int = field(
        default_factory=lambda: _env_int(
            "RETRIEVAL_LEG_TOP_K",
            RERANKER_CANDIDATE_TOP_K if RERANKER_ENABLED else 5,
        )
    )

    # RRF parameters — F4: RRF_K env-tunable (eval flywheel calibrates).
    rrf_k: int = field(default_factory=lambda: _env_int("RRF_K", 60))

    # Final results. Without a reranker, RRF+MMR output is the final ranking —
    # 3 is too aggressive a cut (loses relevant-but-lower-ranked evidence);
    # 5 matches the reranker-off candidate pool above.
    final_top_k: int = RERANKER_TOP_K if RERANKER_ENABLED else 5
    enable_reranker: bool = RERANKER_ENABLED

    # MMR de-redundancy (applied after RRF, optionally after reranker).
    # When enabled, near-duplicate chunks are removed in favour of diverse,
    # still-relevant evidence. F4: MMR_LAMBDA env-tunable.
    enable_mmr: bool = field(default_factory=lambda: _env_bool("RETRIEVAL_MMR_ENABLED", True))
    mmr_lambda: float = field(default_factory=lambda: _env_float("MMR_LAMBDA", 0.7))
    enable_time_decay: bool = field(
        default_factory=lambda: _env_bool("RETRIEVAL_TIME_DECAY_ENABLED", True)
    )

    # Performance
    enable_parallel: bool = True

    # GraphRAG leg (docs/specs/graphrag). Default OFF (REQ-GR-008): when False
    # the graph leg is never invoked and RRF normalisation excludes graph_weight,
    # so behaviour is byte-for-byte identical to the pre-graph implementation.
    enable_graph: bool = GRAPH_RAG_ENABLED
    graph_weight: float = GRAPH_RAG_WEIGHT
    graph_top_k: int = GRAPH_RAG_TOP_K

    # Native sparse leg (docs/specs/retrieval-backend-modernization, F-02 方案 A).
    # When True, the sparse leg uses Milvus sparse_search (BGE-M3 lexical_weights)
    # instead of the self-implemented BM25Retriever. The dense and sparse legs stay
    # two INDEPENDENT searches so _rrf_fusion's double-hit accumulation semantics
    # (hybrid_retriever.py:637-639) are preserved byte-for-byte (F-02). F-01: filter
    # goes through search(filter=), not hybrid_search's top-level filter.
    # False reverts to BM25Retriever (REQ-RBM-005 legacy path, BM25 code retained).
    enable_native_sparse: bool = MILVUS_SPARSE_INDEX

    # Independent candidate funnel. ``None`` preserves compatibility by deriving
    # bounded defaults from the existing dense/sparse/final settings.
    candidate_k: int | None = field(
        default_factory=lambda: _env_int("RETRIEVAL_CANDIDATE_K", 0) or None
    )
    rerank_k: int | None = field(default_factory=lambda: _env_int("RETRIEVAL_RERANK_K", 0) or None)
    selection_k: int | None = field(
        default_factory=lambda: _env_int("RETRIEVAL_SELECTION_K", 0) or None
    )
    enable_candidate_funnel: bool = field(
        default_factory=lambda: _env_bool("RETRIEVAL_CANDIDATE_FUNNEL_ENABLED", False)
    )
    enable_query_reuse: bool = field(
        default_factory=lambda: _env_bool("RETRIEVAL_QUERY_REUSE_ENABLED", False)
    )

    def active_policy(self) -> ActiveChannelPolicy:
        sparse_backend = (
            "disabled"
            if not self.enable_sparse
            else "native_m3"
            if self.enable_native_sparse
            else "bm25"
        )
        return ActiveChannelPolicy(
            dense=bool(self.enable_dense),
            sparse=bool(self.enable_sparse),
            graph=bool(self.enable_graph),
            sparse_backend=sparse_backend,
            reranker=bool(self.enable_reranker),
            mmr=bool(self.enable_mmr and self.enable_dense),
            time_decay=bool(self.enable_time_decay),
            candidate_funnel=bool(self.enable_candidate_funnel),
            contextual_index=_env_bool("CONTEXTUAL_INDEX_ENABLED", False),
            dense_weight=float(self.dense_weight),
            sparse_weight=float(self.sparse_weight),
            graph_weight=float(self.graph_weight),
            rrf_k=int(self.rrf_k),
        )

    def resolve_budgets(self, top_k: int | None = None) -> RetrievalBudgets:
        final_raw = top_k if top_k is not None else self.final_top_k
        final = _bounded_positive(final_raw, 5)
        frontier_requested = self.enable_candidate_funnel or any(
            value is not None for value in (self.candidate_k, self.rerank_k, self.selection_k)
        )
        if not frontier_requested:
            candidate = max(self.dense_top_k, self.sparse_top_k, final)
            return RetrievalBudgets(candidate, final, final, final, False)
        default_candidate = max(
            self.dense_top_k,
            self.sparse_top_k,
            final * 2 if (self.enable_mmr or self.enable_reranker) else final,
        )
        raw_candidate = self.candidate_k or default_candidate
        raw_rerank = self.rerank_k or raw_candidate
        # Default diversification selects the final target from the full rerank
        # reservoir. It therefore receives >final candidates without forcing the
        # first final slots to be the prefix of an over-diversified size-N order.
        raw_selection = self.selection_k or final
        values = (raw_candidate, raw_rerank, raw_selection, final_raw)
        degraded = any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in values
        )
        candidate = _bounded_positive(raw_candidate, default_candidate)
        rerank = _bounded_positive(raw_rerank, candidate)
        selection = _bounded_positive(raw_selection, rerank)
        if not candidate >= rerank >= selection >= final:
            degraded = True
        selection = max(selection, final)
        rerank = max(rerank, selection)
        candidate = max(candidate, rerank)
        return RetrievalBudgets(candidate, rerank, selection, final, degraded)


def _bounded_positive(value: Any, default: int, maximum: int = 200) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        value = default
    return min(int(value), maximum)


@dataclass(frozen=True)
class RetrievalBudgets:
    candidate_k: int
    rerank_k: int
    selection_k: int
    final_k: int
    degraded: bool = False

    @property
    def fingerprint(self) -> str:
        return f"{self.candidate_k}:{self.rerank_k}:{self.selection_k}:{self.final_k}"


@dataclass(frozen=True)
class ActiveChannelPolicy:
    dense: bool
    sparse: bool
    graph: bool
    sparse_backend: str
    reranker: bool
    mmr: bool
    time_decay: bool
    candidate_funnel: bool
    contextual_index: bool
    dense_weight: float
    sparse_weight: float
    graph_weight: float
    rrf_k: int

    @property
    def fingerprint(self) -> str:
        payload = {
            "candidate_funnel": self.candidate_funnel,
            "contextual_index": self.contextual_index,
            "dense": self.dense,
            "dense_weight": self.dense_weight,
            "graph": self.graph,
            "graph_weight": self.graph_weight,
            "mmr": self.mmr,
            "reranker": self.reranker,
            "rrf_k": self.rrf_k,
            "sparse": self.sparse,
            "sparse_backend": self.sparse_backend,
            "sparse_weight": self.sparse_weight,
            "time_decay": self.time_decay,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True)
class ChannelExecution:
    results: tuple[RetrievalResult, ...] = ()
    status: str = "unavailable_or_no_match"

    @classmethod
    def disabled(cls) -> ChannelExecution:
        return cls(status="disabled")

    @classmethod
    def from_results(cls, results: list[RetrievalResult]) -> ChannelExecution:
        return cls(
            tuple(results),
            "contributed" if results else "unavailable_or_no_match",
        )


@dataclass(frozen=True)
class RetrievalExecutionInfo:
    identity: str
    statuses: tuple[tuple[str, str], ...]
    cache_hit: bool = False
    degraded: bool = False
    relevance_score: float | None = None

    @property
    def channel_status(self) -> dict[str, str]:
        return dict(self.statuses)


@dataclass(frozen=True)
class HybridRetrievalOutcome:
    documents: list[Document]
    execution: RetrievalExecutionInfo


@dataclass
class _ChannelResults:
    dense: ChannelExecution
    sparse: ChannelExecution
    graph: ChannelExecution
    representation: Any | None = None

    def __iter__(self) -> Iterator[list[RetrievalResult]]:
        yield list(self.dense.results)
        yield list(self.sparse.results)
        yield list(self.graph.results)


_request_budgets: ContextVar[RetrievalBudgets | None] = ContextVar(
    "retrieval_frontier_budgets",
    default=None,
)
_request_representation: ContextVar[Any | None] = ContextVar(
    "retrieval_frontier_query_representation",
    default=None,
)
_request_plan: ContextVar[Any | None] = ContextVar("retrieval_frontier_plan", default=None)
_request_retry_identity: ContextVar[str | None] = ContextVar(
    "retrieval_frontier_retry_identity",
    default=None,
)
_request_execution_info: ContextVar[RetrievalExecutionInfo | None] = ContextVar(
    "retrieval_execution_info",
    default=None,
)


def get_current_retrieval_execution_info() -> RetrievalExecutionInfo | None:
    return _request_execution_info.get()


@dataclass
class RetrievalResult:
    """Single retrieval result."""

    document: Document
    score: float
    source: str  # "dense", "sparse", or "hybrid"
    rank: int = 0


class HybridRetriever:
    """
    Hybrid retriever combining dense and sparse retrieval.

    Uses Reciprocal Rank Fusion (RRF) to combine results from
    multiple retrievers for improved recall and precision.

    RRF Formula:
        RRF(d) = Σ 1/(k + rank(d)) for each retriever ranking

    Features:
    - Parallel retrieval for performance
    - Configurable weights for dense/sparse
    - RRF fusion algorithm
    - Optional reranking
    """

    def __init__(
        self,
        dense_manager: MilvusManager | None = None,
        sparse_retriever: BM25Retriever | None = None,
        config: HybridRetrieverConfig | None = None,
    ):
        """
        Initialize hybrid retriever.

        Args:
            dense_manager: Milvus manager for dense retrieval
            sparse_retriever: BM25 retriever for sparse retrieval
            config: Retrieval configuration
        """
        self.config = config or HybridRetrieverConfig()
        self._dense_manager = dense_manager
        self._sparse_retriever = sparse_retriever
        self._initialized = False
        # Per-instance executor for the parallel dense/sparse sync legs. The
        # legacy class-level ThreadPoolExecutor(max_workers=2) was a process-wide
        # serialization point (2 workers shared across every request); it is now
        # instance-scoped with a configurable worker count, and shut down in
        # close() (wired into api.main lifespan shutdown). The async path uses
        # run_in_executor(None, ...) (default pool) and is intentionally left
        # unchanged — it is not bottlenecked.
        import os

        try:
            workers = max(2, int(os.getenv("RETRIEVAL_PARALLEL_WORKERS", "4")))
        except (TypeError, ValueError):
            workers = 4
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)

        log.debug(
            f"HybridRetriever created: "
            f"dense_weight={self.config.dense_weight}, "
            f"sparse_weight={self.config.sparse_weight}, "
            f"parallel_workers={workers}"
        )

    def close(self) -> None:
        """Release the parallel-retrieval thread pool. Idempotent."""
        ex = getattr(self, "_executor", None)
        if ex is not None:
            try:
                ex.shutdown(wait=False)
            except Exception:
                pass

    def active_policy(self, plan: Any | None = None) -> ActiveChannelPolicy:
        policy = self.config.active_policy()
        if plan is None:
            return policy
        graph = bool(policy.graph or getattr(plan, "graph_weight", 0) > 0)
        mmr = bool(policy.mmr and getattr(plan, "use_mmr", False))
        time_decay = bool(policy.time_decay and getattr(plan, "use_time_decay", False))
        return replace(
            policy,
            graph=graph,
            mmr=mmr,
            time_decay=time_decay,
            dense_weight=float(getattr(plan, "dense_weight", policy.dense_weight))
            if policy.dense
            else 0.0,
            sparse_weight=float(getattr(plan, "sparse_weight", policy.sparse_weight))
            if policy.sparse
            else 0.0,
            graph_weight=float(getattr(plan, "graph_weight", policy.graph_weight))
            if graph
            else 0.0,
        )

    def _execution_identity(
        self,
        budgets: RetrievalBudgets,
        plan: Any | None = None,
    ) -> str:
        raw = "|".join(
            (
                self.active_policy(plan).fingerprint,
                budgets.fingerprint,
                getattr(plan, "fingerprint", "compatibility"),
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]

    def _publish_execution(
        self,
        channels: _ChannelResults | None,
        *,
        budgets: RetrievalBudgets,
        plan: Any | None,
        documents: list[Document],
        cache_hit: bool = False,
        degraded: bool = False,
    ) -> RetrievalExecutionInfo:
        policy = self.active_policy(plan)
        if cache_hit:
            statuses = {
                "dense": "cache_hit" if policy.dense else "disabled",
                "sparse": "cache_hit" if policy.sparse else "disabled",
                "graph": "cache_hit" if policy.graph else "disabled",
            }
        elif channels is None:
            statuses = {
                "dense": "unavailable_or_no_match" if policy.dense else "disabled",
                "sparse": "unavailable_or_no_match" if policy.sparse else "disabled",
                "graph": "unavailable_or_no_match" if policy.graph else "disabled",
            }
        else:
            statuses = {
                "dense": channels.dense.status,
                "sparse": channels.sparse.status,
                "graph": channels.graph.status,
            }
        scores = [
            float(document.metadata["score"])
            for document in documents
            if isinstance(document.metadata.get("score"), (int, float))
        ]
        info = RetrievalExecutionInfo(
            identity=self._execution_identity(budgets, plan),
            statuses=tuple(sorted(statuses.items())),
            cache_hit=cache_hit,
            degraded=bool(degraded or not documents),
            relevance_score=(sum(scores) / len(scores)) if scores else None,
        )
        _request_execution_info.set(info)
        return info

    @staticmethod
    def _coerce_channel_results(
        value: Any,
        policy: ActiveChannelPolicy,
    ) -> _ChannelResults:
        if isinstance(value, _ChannelResults):
            return value
        dense, sparse, graph = value

        def execution(enabled: bool, results: Any) -> ChannelExecution:
            if not enabled:
                return ChannelExecution.disabled()
            if isinstance(results, ChannelExecution):
                return results
            return ChannelExecution.from_results(list(results or []))

        return _ChannelResults(
            execution(policy.dense, dense),
            execution(policy.sparse, sparse),
            execution(policy.graph, graph),
            getattr(value, "representation", None),
        )

    def retrieve_with_info(self, *args: Any, **kwargs: Any) -> HybridRetrievalOutcome:
        documents = self.retrieve(*args, **kwargs)
        info = get_current_retrieval_execution_info()
        if info is None:
            budgets = self.config.resolve_budgets(kwargs.get("top_k"))
            info = self._publish_execution(
                None,
                budgets=budgets,
                plan=kwargs.get("plan"),
                documents=documents,
                degraded=not documents,
            )
        return HybridRetrievalOutcome(documents, info)

    async def aretrieve_with_info(self, *args: Any, **kwargs: Any) -> HybridRetrievalOutcome:
        documents = await self.aretrieve(*args, **kwargs)
        info = get_current_retrieval_execution_info()
        if info is None:
            budgets = self.config.resolve_budgets(kwargs.get("top_k"))
            info = self._publish_execution(
                None,
                budgets=budgets,
                plan=kwargs.get("plan"),
                documents=documents,
                degraded=not documents,
            )
        return HybridRetrievalOutcome(documents, info)

    @property
    def dense_manager(self) -> MilvusManager:
        """Get dense retriever (lazy initialization)."""
        if self._dense_manager is None:
            from documents.milvus_db import get_milvus_manager

            self._dense_manager = get_milvus_manager()
        return self._dense_manager

    @property
    def sparse_retriever(self) -> BM25Retriever:
        """Get the shared BM25 singleton (auto-synced from Milvus on cold start).

        Returns the process-wide ``get_bm25_retriever()`` singleton — the same
        instance the documents router writes to on add/remove. This closes the
        historical divergence where the hybrid retriever built its own
        ``BM25Retriever()`` instance that never saw runtime document mutations.
        """
        if self._sparse_retriever is None:
            from core.retrieval.bm25_retriever import get_bm25_retriever

            self._sparse_retriever = get_bm25_retriever()
        self._ensure_sparse_indexed()
        return self._sparse_retriever

    def _ensure_sparse_indexed(self) -> None:
        """Bootstrap the shared BM25 singleton from Milvus on cold start only.

        The singleton is incrementally maintained by the documents write path
        (add/remove call ``add_documents``/``remove_by_source`` on it directly),
        so once it has an index we never re-bootstrap — its own
        ``_index_built``/``_documents`` flags are authoritative. This only runs
        on a cold process (or after an explicit ``clear()``) to hydrate BM25
        from the durable Milvus store.
        """
        if self._sparse_retriever._index_built and self._sparse_retriever._documents:
            return  # Singleton already holds an index maintained by the write path.
        if not self.config.enable_dense:
            return
        try:
            results = self.dense_manager.query(
                filter_expr="id > 0",
                output_fields=["text", "source", "title", "index_text", "display_text"],
                limit=10000,
            )
            if results:
                docs = [
                    Document(
                        page_content=r.get("text", ""),
                        metadata={
                            "source": r.get("source", ""),
                            "title": r.get("title", ""),
                            **({"index_text": r.get("index_text")} if r.get("index_text") else {}),
                        },
                    )
                    for r in results
                    if r.get("text")
                ]
                if docs:
                    self._sparse_retriever.add_documents(docs)
                    log.info(f"BM25 index loaded from Milvus: {len(docs)} docs")
        except Exception as e:
            log.debug(f"BM25 Milvus sync skipped (collection may not exist): {e}")

    @staticmethod
    def _execute_channel(
        enabled: bool,
        operation: Any,
        *,
        name: str,
    ) -> ChannelExecution:
        if not enabled:
            return ChannelExecution.disabled()
        try:
            return ChannelExecution.from_results(operation())
        except Exception as exc:
            log.warning(f"{name} retrieval failed, degraded to empty: {exc}")
            return ChannelExecution()

    # ------------------------------------------------------------------
    # Cache helpers (F19 — single source of truth for version folding +
    # deepcopy placement, so the sync and async retrieve paths cannot drift)
    # ------------------------------------------------------------------

    def _cache_key_for(
        self,
        query: str,
        filter_expr: str | None,
        budgets: RetrievalBudgets,
        plan_fingerprint: str = "compatibility",
        retry_identity: str | None = None,
    ) -> str:
        """Build the versioned retrieval cache key (single source)."""
        from core.retrieval.cache import cache_key, get_retrieval_cache_version
        from core.retrieval.filter_scope import FilterScope

        return cache_key(
            "hybrid-v2",
            query,
            FilterScope.parse(filter_expr).fingerprint,
            budgets.fingerprint,
            self.config.active_policy().fingerprint,
            plan_fingerprint,
            retry_identity or "initial",
            get_retrieval_cache_version(),
        )

    @staticmethod
    def _cache_get(key: str) -> list[Document] | None:
        """Read-through cache helper. Returns None on any failure (degrade to
        live retrieval — never break the path over caching)."""
        if not _retrieval_cache_enabled():
            return None
        try:
            from core.retrieval.cache import get_retrieval_cache

            return get_retrieval_cache().get(key)
        except Exception as e:
            log.debug(f"retrieval cache read skipped: {e}")
            return None

    @staticmethod
    def _cache_put(key: str, documents: list[Document]) -> None:
        """Write cache helper. Deep-copies so downstream mutations to the
        returned Document objects do not corrupt the cached entry."""
        if not _retrieval_cache_enabled():
            return
        try:
            import copy

            from core.retrieval.cache import get_retrieval_cache

            get_retrieval_cache().put(key, copy.deepcopy(documents))
        except Exception as e:
            log.debug(f"retrieval cache write skipped: {e}")

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        filter_expr: str | None = None,
        plan: Any | None = None,
        retry_identity: str | None = None,
    ) -> list[Document]:
        """
        Perform hybrid retrieval synchronously.

        Args:
            query: Search query
            top_k: Number of results (default from config)
            filter_expr: optional Milvus boolean expression to pre-filter
                dense candidates (e.g. ``source == "engine_manual"``).

        Returns:
            List of retrieved documents
        """
        budgets = self._resolve_request_budgets(top_k, plan)
        top_k = budgets.final_k
        start_time = time.perf_counter()
        from core.retrieval.filter_scope import FilterCapability, FilterKind, FilterScope

        filter_scope = FilterScope.parse(filter_expr)
        policy = self.active_policy(plan)
        if filter_scope.kind is FilterKind.INVALID:
            log.warning("Hybrid retrieval excluded invalid filter expression")
            self._publish_execution(
                None,
                budgets=budgets,
                plan=plan,
                documents=[],
                degraded=True,
            )
            return []

        # Result cache: identical (query, filter, top_k) returns instantly.
        # The cache is best-effort; on any failure we fall through to live
        # retrieval (never break the path over caching).
        # Result cache: identical (query, filter, top_k, version) returns
        # instantly. Version-folding + read are centralised in _cache_get /
        # _cache_key_for so sync and async cannot drift.
        cache_key_str = self._cache_key_for(
            query,
            filter_expr,
            budgets,
            getattr(plan, "fingerprint", "compatibility"),
            retry_identity,
        )
        cached = self._cache_get(cache_key_str)
        if cached is not None:
            log.debug(f"Hybrid retrieval cache HIT (key={cache_key_str[:8]})")
            self._publish_execution(
                None,
                budgets=budgets,
                plan=plan,
                documents=cached,
                cache_hit=True,
            )
            return cached

        budget_token = _request_budgets.set(budgets)
        plan_token = _request_plan.set(plan)
        retry_token = _request_retry_identity.set(retry_identity)
        representation_token = None
        try:
            # Perform retrievals
            if self.config.enable_parallel:
                channel_results = self._coerce_channel_results(
                    self._parallel_retrieve(query, filter_expr),
                    policy,
                )
                dense_results, sparse_results, graph_results = channel_results
                representation = channel_results.representation
            else:
                representation = None
                if self._needs_shared_representation(filter_scope):
                    representation = self._prepare_query_representation(query)
                dense_execution = self._execute_channel(
                    policy.dense and filter_scope.supports(FilterCapability.MILVUS_EXPRESSION),
                    lambda: self._dense_retrieve(
                        query,
                        filter_expr,
                        query_representation=representation,
                        top_k=budgets.candidate_k,
                    ),
                    name="dense",
                )
                sparse_capability = (
                    FilterCapability.MILVUS_EXPRESSION
                    if self.config.enable_native_sparse
                    else FilterCapability.SOURCE_SET
                )
                sparse_execution = self._execute_channel(
                    policy.sparse and filter_scope.supports(sparse_capability),
                    lambda: self._sparse_retrieve(
                        query,
                        filter_expr,
                        query_representation=representation,
                        top_k=budgets.candidate_k,
                    ),
                    name="sparse",
                )
                graph_execution = self._execute_channel(
                    policy.graph and filter_scope.supports(FilterCapability.SOURCE_SET),
                    lambda: self._graph_retrieve(
                        query,
                        filter_expr,
                        query_representation=representation,
                        top_k=budgets.candidate_k,
                    ),
                    name="graph",
                )
                channel_results = _ChannelResults(
                    dense_execution,
                    sparse_execution,
                    graph_execution,
                    representation,
                )
                dense_results, sparse_results, graph_results = channel_results

            representation_token = _request_representation.set(representation)

            # Fuse results
            fused_results = self._rrf_fusion(dense_results, sparse_results, graph_results)

            # Pipeline order: RRF → time_decay → rerank → MMR. time_decay MUST
            # run before rerank so the decayed `score` feeds the reranker's
            # blend signal; running it after rerank left decay with no ranking
            # effect whenever the reranker was on (its `rerank_score` then
            # dominated MMR). See time_decay.py docstring (B6).
            documents = [r.document for r in fused_results]
            documents = self._time_decay(documents)
            documents = self._rerank(query, documents, budgets.rerank_k)
            documents = self._colbert_rerank(documents, budgets.rerank_k)
            if plan is not None:
                from core.retrieval.authority import rank_by_authority

                documents = rank_by_authority(documents)
            documents = self._mmr(query, documents, budgets.selection_k)
            documents = (
                self._select(documents, budgets)
                if self._candidate_funnel_enabled()
                else documents[: budgets.final_k]
            )

            elapsed = (time.perf_counter() - start_time) * 1000
            graph_count = len(graph_results) if isinstance(graph_results, list) else 0
            log.info(
                f"Hybrid retrieval completed: "
                f"dense={len(dense_results)}, sparse={len(sparse_results)}, "
                f"graph={graph_count}, final={len(documents)}, "
                f"elapsed={elapsed:.1f}ms"
            )

            # Persist into the result cache (deep-copy + version folded in the
            # shared _cache_put helper so sync/async cannot drift).
            self._cache_put(cache_key_str, documents)
            self._publish_execution(
                channel_results,
                budgets=budgets,
                plan=plan,
                documents=documents,
                degraded=budgets.degraded,
            )

            return documents

        except Exception as e:
            log.error(f"Hybrid retrieval failed: {e}")
            dense_execution = self._execute_channel(
                policy.dense and filter_scope.supports(FilterCapability.MILVUS_EXPRESSION),
                lambda: self._dense_retrieve(query, filter_expr, top_k=top_k),
                name="dense fallback",
            )
            sparse_capability = (
                FilterCapability.MILVUS_EXPRESSION
                if self.config.enable_native_sparse
                else FilterCapability.SOURCE_SET
            )
            sparse_execution = self._execute_channel(
                not dense_execution.results
                and policy.sparse
                and filter_scope.supports(sparse_capability),
                lambda: self._sparse_retrieve(query, filter_expr, top_k=top_k),
                name="sparse fallback",
            )
            fallback_results = [*dense_execution.results, *sparse_execution.results]
            documents = [result.document for result in fallback_results[:top_k]]
            channel_results = _ChannelResults(
                dense_execution,
                sparse_execution,
                ChannelExecution.disabled() if not policy.graph else ChannelExecution(),
            )
            self._publish_execution(
                channel_results,
                budgets=budgets,
                plan=plan,
                documents=documents,
                degraded=True,
            )
            return documents
        finally:
            if representation_token is not None:
                _request_representation.reset(representation_token)
            _request_retry_identity.reset(retry_token)
            _request_plan.reset(plan_token)
            _request_budgets.reset(budget_token)

    async def aretrieve(
        self,
        query: str,
        top_k: int | None = None,
        filter_expr: str | None = None,
        plan: Any | None = None,
        retry_identity: str | None = None,
    ) -> list[Document]:
        """
        Perform hybrid retrieval asynchronously.

        Args:
            query: Search query
            top_k: Number of results
            filter_expr: optional Milvus boolean expression to pre-filter.

        Returns:
            List of retrieved documents
        """
        budgets = self._resolve_request_budgets(top_k, plan)
        top_k = budgets.final_k
        start_time = time.perf_counter()
        from core.retrieval.filter_scope import FilterKind, FilterScope

        filter_scope = FilterScope.parse(filter_expr)
        policy = self.active_policy(plan)
        if filter_scope.kind is FilterKind.INVALID:
            log.warning("Async hybrid retrieval excluded invalid filter expression")
            self._publish_execution(
                None,
                budgets=budgets,
                plan=plan,
                documents=[],
                degraded=True,
            )
            return []

        # Result cache (parity with the sync path via the shared helpers).
        cache_key_str = self._cache_key_for(
            query,
            filter_expr,
            budgets,
            getattr(plan, "fingerprint", "compatibility"),
            retry_identity,
        )
        cached = self._cache_get(cache_key_str)
        if cached is not None:
            log.debug(f"Async hybrid retrieval cache HIT (key={cache_key_str[:8]})")
            self._publish_execution(
                None,
                budgets=budgets,
                plan=plan,
                documents=cached,
                cache_hit=True,
            )
            return cached

        budget_token = _request_budgets.set(budgets)
        plan_token = _request_plan.set(plan)
        retry_token = _request_retry_identity.set(retry_identity)
        representation_token = None
        try:
            channel_results = self._coerce_channel_results(
                await self._aparallel_retrieve(query, filter_scope),
                policy,
            )
            dense_results, sparse_results, graph_results = channel_results
            representation_token = _request_representation.set(channel_results.representation)

            # Fuse results
            fused_results = self._rrf_fusion(dense_results, sparse_results, graph_results)

            # Pipeline order mirrors the sync path: RRF → time_decay → rerank →
            # MMR (B6 — decay before rerank so the decayed score feeds rerank).
            documents = [r.document for r in fused_results]
            documents = self._time_decay(documents)
            documents = await self._arerank(query, documents, budgets.rerank_k)
            documents = await self._acolbert_rerank(documents, budgets.rerank_k)
            if plan is not None:
                from core.retrieval.authority import rank_by_authority

                documents = rank_by_authority(documents)
            documents = await self._ammr(query, documents, budgets.selection_k)
            documents = (
                self._select(documents, budgets)
                if self._candidate_funnel_enabled()
                else documents[: budgets.final_k]
            )

            elapsed = (time.perf_counter() - start_time) * 1000
            graph_count = len(graph_results) if isinstance(graph_results, list) else 0
            log.info(
                f"Async hybrid retrieval: final={len(documents)}, "
                f"graph={graph_count}, elapsed={elapsed:.1f}ms"
            )

            # Persist into the result cache via the shared helper (deep-copy +
            # version folded in one place).
            self._cache_put(cache_key_str, documents)
            self._publish_execution(
                channel_results,
                budgets=budgets,
                plan=plan,
                documents=documents,
                degraded=budgets.degraded,
            )

            return documents

        except Exception as e:
            log.error(f"Async hybrid retrieval failed: {e}")
            self._publish_execution(
                None,
                budgets=budgets,
                plan=plan,
                documents=[],
                degraded=True,
            )
            return []
        finally:
            if representation_token is not None:
                _request_representation.reset(representation_token)
            _request_retry_identity.reset(retry_token)
            _request_plan.reset(plan_token)
            _request_budgets.reset(budget_token)

    def _dense_retrieve(
        self,
        query: str,
        filter_expr: str | None = None,
        *,
        query_representation: Any | None = None,
        top_k: int | None = None,
    ) -> list[RetrievalResult]:
        """Perform dense (vector) retrieval, optionally pre-filtered."""
        try:
            limit = top_k or (_request_budgets.get() or self.config.resolve_budgets()).candidate_k
            if query_representation is not None:
                query_dense = getattr(query_representation, "dense", None)
                if query_dense is None:
                    return []
                results = self.dense_manager.search_by_vector(
                    query_embedding=query_dense,
                    top_k=limit,
                    filter_expr=filter_expr,
                )
            else:
                results = self.dense_manager.search(
                    query=query,
                    top_k=limit,
                    filter_expr=filter_expr,
                )

            return [
                RetrievalResult(
                    document=r.to_document(),
                    score=r.score,
                    source="dense",
                    rank=i + 1,
                )
                for i, r in enumerate(results)
            ]
        except Exception as e:
            log.warning(f"Dense retrieval failed: {e}")
            return []

    def _sparse_retrieve(
        self,
        query: str,
        filter_expr: str | None = None,
        *,
        query_representation: Any | None = None,
        top_k: int | None = None,
    ) -> list[RetrievalResult]:
        """Perform sparse retrieval.

        F-02 方案 A: dispatches between native Milvus sparse_search (BGE-M3
        lexical_weights) and the legacy self-implemented BM25. The native path
        is filter-aware (F-01: filter via search.filter); the legacy BM25 leg
        ignores filter_expr (pre-existing behaviour — BM25Retriever has no
        source filtering). Both return independent rank lists so _rrf_fusion's
        double-hit accumulation semantics are preserved.
        """
        if self.config.enable_native_sparse:
            if query_representation is None and top_k is None:
                return self._sparse_retrieve_m3(query, filter_expr)
            return self._sparse_retrieve_m3(
                query,
                filter_expr,
                query_representation=query_representation,
                top_k=top_k,
            )
        try:
            from core.retrieval.filter_scope import FilterCapability, FilterScope

            scope = FilterScope.parse(filter_expr)
            if not scope.supports(FilterCapability.SOURCE_SET):
                return []
            limit = top_k or (_request_budgets.get() or self.config.resolve_budgets()).candidate_k
            allowed = set(scope.sources) if scope.sources else None
            return self.sparse_retriever.retrieve(query, limit, allowed_sources=allowed)
        except Exception as e:
            log.warning(f"Sparse (BM25) retrieval failed: {e}")
            return []

    def _sparse_retrieve_m3(
        self,
        query: str,
        filter_expr: str | None = None,
        *,
        query_representation: Any | None = None,
        top_k: int | None = None,
    ) -> list[RetrievalResult]:
        """Native Milvus sparse search (BGE-M3 lexical_weights).

        F-02: replaces BM25. F-01: filter goes through sparse_search(filter_expr)
        which calls MilvusClient.search(filter=) — a first-class param. Degrades
        to [] on failure so RRF falls back to dense+graph (REQ-RBM-004).
        """
        try:
            if query_representation is not None:
                sparse = getattr(query_representation, "sparse", None)
                if sparse is None:
                    return self._legacy_sparse_fallback(query, filter_expr, top_k)
            else:
                from models.bge_m3_embeddings import get_bge_m3_embeddings

                emb = get_bge_m3_embeddings()
                sparse = emb.encode_query_representation(query)["sparse"]
            if not sparse:
                return self._legacy_sparse_fallback(query, filter_expr, top_k)
            limit = top_k or (_request_budgets.get() or self.config.resolve_budgets()).candidate_k
            results = self.dense_manager.sparse_search(
                query_sparse=sparse,
                top_k=limit,
                filter_expr=filter_expr,
            )
            return [
                RetrievalResult(
                    document=r.to_document(),
                    score=r.score,
                    source="sparse",
                    rank=i + 1,
                )
                for i, r in enumerate(results)
            ]
        except Exception as e:
            if query_representation is None:
                log.warning(f"Sparse M3 retrieval failed, degraded to empty: {e}")
                return []
            log.warning(f"Sparse M3 retrieval failed, trying safe legacy fallback: {e}")
            return self._legacy_sparse_fallback(query, filter_expr, top_k)

    def _legacy_sparse_fallback(
        self,
        query: str,
        filter_expr: str | None,
        top_k: int | None,
    ) -> list[RetrievalResult]:
        from core.retrieval.filter_scope import FilterCapability, FilterScope

        scope = FilterScope.parse(filter_expr)
        if not scope.supports(FilterCapability.SOURCE_SET):
            return []
        try:
            limit = top_k or (_request_budgets.get() or self.config.resolve_budgets()).candidate_k
            allowed = set(scope.sources) if scope.sources else None
            return self.sparse_retriever.retrieve(query, limit, allowed_sources=allowed)
        except Exception as exc:  # hot-path degradation
            log.warning(f"Legacy sparse fallback unavailable: {exc}")
            return []

    async def _adense_retrieve(
        self,
        query: str,
        filter_expr: str | None = None,
        *,
        query_representation: Any | None = None,
        top_k: int | None = None,
    ) -> list[RetrievalResult]:
        """Async dense retrieval."""
        return await asyncio.to_thread(
            self._dense_retrieve,
            query,
            filter_expr,
            query_representation=query_representation,
            top_k=top_k,
        )

    async def _asparse_retrieve(
        self,
        query: str,
        filter_expr: str | None = None,
        *,
        query_representation: Any | None = None,
        top_k: int | None = None,
    ) -> list[RetrievalResult]:
        """Async sparse retrieval."""
        return await asyncio.to_thread(
            self._sparse_retrieve,
            query,
            filter_expr,
            query_representation=query_representation,
            top_k=top_k,
        )

    def _graph_retrieve(
        self,
        query: str,
        filter_expr: str | None = None,
        *,
        query_representation: Any | None = None,
        top_k: int | None = None,
    ) -> list[RetrievalResult]:
        """GraphRAG leg (third RRF leg). Gated by ``enable_graph``.

        Degrades to ``[]`` on any failure (REQ-GR-003) — never raises, so the
        surrounding RRF path falls back to dense+sparse transparently.
        """
        if not self._graph_enabled():
            return []
        try:
            from core.retrieval.graph_retriever import get_graph_retriever

            query_dense = (
                getattr(query_representation, "dense", None)
                if query_representation is not None
                else None
            )
            if query_representation is not None and query_dense is None:
                return []
            limit = top_k or min(
                self.config.graph_top_k,
                (_request_budgets.get() or self.config.resolve_budgets()).candidate_k,
            )
            kwargs = {"top_k": limit, "filter_expr": filter_expr}
            plan = _request_plan.get()
            if plan is not None and getattr(plan, "use_ppr", False):
                kwargs["use_ppr"] = True
                kwargs["facets"] = getattr(plan, "facets", ())
            if query_representation is not None:
                kwargs["query_dense"] = query_dense
            return get_graph_retriever().retrieve(query, **kwargs)
        except Exception as e:  # degrade to empty
            log.warning(f"Graph retrieval failed, degraded to empty: {e}")
            return []

    async def _agraph_retrieve(
        self,
        query: str,
        filter_expr: str | None = None,
        *,
        query_representation: Any | None = None,
        top_k: int | None = None,
    ) -> list[RetrievalResult]:
        """Async graph leg."""
        return await asyncio.to_thread(
            self._graph_retrieve,
            query,
            filter_expr,
            query_representation=query_representation,
            top_k=top_k,
        )

    def _rerank(
        self,
        query: str,
        documents: list[Document],
        top_k: int,
    ) -> list[Document]:
        """Optionally apply a cross-encoder after RRF fusion."""
        if not self.config.enable_reranker:
            return documents[:top_k]

        from core.retrieval.reranker import get_reranker

        return get_reranker().rerank(query, documents, top_k=top_k)

    async def _arerank(
        self,
        query: str,
        documents: list[Document],
        top_k: int,
    ) -> list[Document]:
        """Async counterpart of the optional cross-encoder stage."""
        if not self.config.enable_reranker:
            return documents[:top_k]

        from core.retrieval.reranker import get_reranker

        return await get_reranker().arerank(query, documents, top_k=top_k)

    def _colbert_rerank(self, documents: list[Document], top_k: int) -> list[Document]:
        from core.retrieval.colbert_reranker import colbert_rerank_enabled

        if not documents or not colbert_rerank_enabled():
            return documents
        representation = _request_representation.get()
        query_colbert = (
            getattr(representation, "colbert", None) if representation is not None else None
        )
        try:
            from core.retrieval.colbert_reranker import ColBERTReranker

            embedding = self.dense_manager.embedding_function
            return (
                ColBERTReranker(embedding)
                .rerank(
                    query_colbert,
                    documents,
                    top_k=top_k,
                )
                .documents
            )
        except Exception as exc:
            log.warning(f"ColBERT stage skipped: {type(exc).__name__}")
            return documents

    async def _acolbert_rerank(
        self,
        documents: list[Document],
        top_k: int,
    ) -> list[Document]:
        return await asyncio.to_thread(self._colbert_rerank, documents, top_k)

    def _time_decay(self, documents: list[Document]) -> list[Document]:
        """Apply gentle time-decay scoring (P3.7). No-op without timestamps."""
        if not documents or not self._time_decay_enabled():
            return documents
        try:
            from core.retrieval.time_decay import apply_time_decay

            return apply_time_decay(documents)
        except Exception as e:
            log.debug(f"time-decay skipped: {e}")
            return documents

    def _mmr(
        self,
        query: str,
        documents: list[Document],
        top_k: int,
    ) -> list[Document]:
        """
        Optional MMR de-redundancy stage.

        Runs after RRF (and reranker if enabled). When MMR embeddings are
        unavailable it silently returns the input unchanged so retrieval never
        fails on this account.
        """
        if not self._mmr_enabled() or len(documents) <= 1:
            return documents

        from core.retrieval.mmr import mmr_rerank

        try:
            representation = _request_representation.get()
            query_vector = (
                getattr(representation, "dense", None) if representation is not None else None
            )
            selected = mmr_rerank(
                query,
                documents,
                top_k=top_k,
                lambda_=self.config.mmr_lambda,
                query_vector=query_vector,
            )
            selected_ids = {id(document) for document in selected}
            return [*selected, *(doc for doc in documents if id(doc) not in selected_ids)]
        except Exception as e:
            log.debug(f"MMR skipped: {e}")
            return documents

    async def _ammr(
        self,
        query: str,
        documents: list[Document],
        top_k: int,
    ) -> list[Document]:
        """Async counterpart of the MMR stage (offloads to executor)."""
        if not self._mmr_enabled() or len(documents) <= 1:
            return documents
        return await asyncio.to_thread(self._mmr, query, documents, top_k)

    def _resolve_request_budgets(self, top_k: int | None, plan: Any | None) -> RetrievalBudgets:
        if plan is None:
            return self.config.resolve_budgets(top_k)
        final = _bounded_positive(top_k if top_k is not None else plan.final_k, plan.final_k)
        selection = max(final, _bounded_positive(plan.selection_k, final))
        rerank = max(selection, _bounded_positive(plan.rerank_k, selection))
        candidate = max(rerank, _bounded_positive(plan.candidate_k, rerank))
        return RetrievalBudgets(candidate, rerank, selection, final, False)

    def _needs_shared_representation(self, filter_scope: Any) -> bool:
        from core.retrieval.filter_scope import FilterCapability

        if not (self.config.enable_query_reuse or _request_plan.get() is not None):
            return False
        policy = self.active_policy(_request_plan.get())
        return bool(
            policy.dense
            or policy.mmr
            or self._colbert_enabled()
            or (
                policy.sparse
                and self.config.enable_native_sparse
                and filter_scope.supports(FilterCapability.MILVUS_EXPRESSION)
            )
            or (policy.graph and filter_scope.supports(FilterCapability.SOURCE_SET))
        )

    def _candidate_funnel_enabled(self) -> bool:
        return (
            _request_plan.get() is not None
            or self.config.enable_candidate_funnel
            or any(
                value is not None
                for value in (
                    self.config.candidate_k,
                    self.config.rerank_k,
                    self.config.selection_k,
                )
            )
        )

    def _mmr_enabled(self) -> bool:
        return self.active_policy(_request_plan.get()).mmr

    def _graph_enabled(self) -> bool:
        return self.active_policy(_request_plan.get()).graph

    @staticmethod
    def _colbert_enabled() -> bool:
        plan = _request_plan.get()
        if plan is not None:
            return bool(getattr(plan, "use_colbert", False))
        from core.retrieval.colbert_reranker import colbert_rerank_enabled

        return colbert_rerank_enabled()

    def _time_decay_enabled(self) -> bool:
        return self.active_policy(_request_plan.get()).time_decay

    def _prepare_query_representation(self, query: str) -> Any:
        from core.retrieval.query_representation import (
            QueryRepresentation,
            QueryRepresentationProvider,
        )

        try:
            embedding = self.dense_manager.embedding_function
            return QueryRepresentationProvider(embedding).encode(
                query,
                include_colbert=self._colbert_enabled(),
            )
        except Exception as exc:  # hot path: no exception escapes
            log.warning(f"Query representation setup unavailable: {type(exc).__name__}")
            return QueryRepresentation(
                degraded=True,
                errors=("query_representation_unavailable",),
                forward_count=0,
            )

    @staticmethod
    def _select(documents: list[Document], budgets: RetrievalBudgets) -> list[Document]:
        try:
            from core.retrieval.selector import select_evidence

            plan = _request_plan.get()

            return select_evidence(
                documents,
                final_k=budgets.final_k,
                selection_k=budgets.selection_k,
                facets=getattr(plan, "facets", ()),
            )
        except Exception as exc:  # selector must degrade to ranked order
            log.warning(f"Evidence selector degraded to relevance order: {exc}")
            return documents[: budgets.final_k]

    async def _aparallel_retrieve(self, query: str, filter_scope: Any) -> _ChannelResults:
        from core.retrieval.filter_scope import FilterCapability

        budgets = _request_budgets.get() or self.config.resolve_budgets()
        policy = self.active_policy(_request_plan.get())
        representation = None
        if self._needs_shared_representation(filter_scope):
            representation = await asyncio.to_thread(self._prepare_query_representation, query)

        tasks: dict[str, asyncio.Task] = {}
        if policy.dense and filter_scope.supports(FilterCapability.MILVUS_EXPRESSION):
            tasks["dense"] = asyncio.create_task(
                self._adense_retrieve(
                    query,
                    filter_scope.raw_expr,
                    query_representation=representation,
                    top_k=budgets.candidate_k,
                )
            )
        sparse_capability = (
            FilterCapability.MILVUS_EXPRESSION
            if self.config.enable_native_sparse
            else FilterCapability.SOURCE_SET
        )
        if policy.sparse and filter_scope.supports(sparse_capability):
            tasks["sparse"] = asyncio.create_task(
                self._asparse_retrieve(
                    query,
                    filter_scope.raw_expr,
                    query_representation=representation,
                    top_k=budgets.candidate_k,
                )
            )
        if policy.graph and filter_scope.supports(FilterCapability.SOURCE_SET):
            tasks["graph"] = asyncio.create_task(
                self._agraph_retrieve(
                    query,
                    filter_scope.raw_expr,
                    query_representation=representation,
                    top_k=budgets.candidate_k,
                )
            )

        values = {
            "dense": ChannelExecution() if policy.dense else ChannelExecution.disabled(),
            "sparse": ChannelExecution() if policy.sparse else ChannelExecution.disabled(),
            "graph": ChannelExecution() if policy.graph else ChannelExecution.disabled(),
        }
        if tasks:
            names = list(tasks)
            gathered = await asyncio.gather(
                *(tasks[name] for name in names), return_exceptions=True
            )
            for name, result in zip(names, gathered):
                if isinstance(result, Exception):
                    log.warning(f"{name} retrieval failed, degraded to empty: {result}")
                else:
                    values[name] = ChannelExecution.from_results(result)
        return _ChannelResults(
            values["dense"],
            values["sparse"],
            values["graph"],
            representation,
        )

    def _parallel_retrieve(self, query: str, filter_expr: str | None = None) -> _ChannelResults:
        """Perform parallel retrieval using threads.

        Returns ``(dense, sparse, graph)``; the graph leg runs only when
        ``enable_graph`` is on and degrades to ``[]`` on any failure.
        """
        from core.retrieval.filter_scope import FilterCapability, FilterScope

        scope = FilterScope.parse(filter_expr)
        budgets = _request_budgets.get() or self.config.resolve_budgets()
        policy = self.active_policy(_request_plan.get())
        representation = (
            self._prepare_query_representation(query)
            if self._needs_shared_representation(scope)
            else None
        )
        futures: dict[str, concurrent.futures.Future] = {}
        if policy.dense and scope.supports(FilterCapability.MILVUS_EXPRESSION):
            futures["dense"] = self._executor.submit(
                self._dense_retrieve,
                query,
                filter_expr,
                query_representation=representation,
                top_k=budgets.candidate_k,
            )
        sparse_capability = (
            FilterCapability.MILVUS_EXPRESSION
            if self.config.enable_native_sparse
            else FilterCapability.SOURCE_SET
        )
        if policy.sparse and scope.supports(sparse_capability):
            futures["sparse"] = self._executor.submit(
                self._sparse_retrieve,
                query,
                filter_expr,
                query_representation=representation,
                top_k=budgets.candidate_k,
            )
        if policy.graph and scope.supports(FilterCapability.SOURCE_SET):
            futures["graph"] = self._executor.submit(
                self._graph_retrieve,
                query,
                filter_expr,
                query_representation=representation,
                top_k=budgets.candidate_k,
            )

        values = {
            "dense": ChannelExecution() if policy.dense else ChannelExecution.disabled(),
            "sparse": ChannelExecution() if policy.sparse else ChannelExecution.disabled(),
            "graph": ChannelExecution() if policy.graph else ChannelExecution.disabled(),
        }
        for name, future in futures.items():
            try:
                values[name] = ChannelExecution.from_results(future.result())
            except Exception as exc:  # each leg degrades independently
                log.warning(f"{name} retrieval leg failed, degraded to empty: {exc}")
        return _ChannelResults(
            values["dense"],
            values["sparse"],
            values["graph"],
            representation,
        )

    def _rrf_fusion(
        self,
        dense_results: list[RetrievalResult],
        sparse_results: list[RetrievalResult],
        graph_results: list[RetrievalResult] | None = None,
    ) -> list[RetrievalResult]:
        """
        Reciprocal Rank Fusion (RRF) to combine retrieval results.

        RRF(d) = Σ w_i / (k + rank_i(d))

        The GraphRAG leg (``graph_results``) joins as a third retriever when
        ``enable_graph`` is on and the leg produced hits. F-04 gate: when graph
        is off (or empty), ``graph_weight`` is excluded from the normalisation
        denominator so dense/sparse weights stay byte-for-byte identical to the
        pre-graph implementation (REQ-GR-008 zero-change default).

        Args:
            dense_results: Results from dense retrieval
            sparse_results: Results from sparse retrieval
            graph_results: Results from the graph leg (optional)

        Returns:
            Fused and ranked results
        """
        # F-04 weight normalisation. The graph weight participates only when
        # the leg is both enabled AND non-empty; otherwise the denominator is
        # dense+sparse so the existing two-leg scores are unchanged.
        plan = _request_plan.get()
        policy = self.active_policy(plan)
        dense_weight = policy.dense_weight if policy.dense else 0.0
        sparse_weight = policy.sparse_weight if policy.sparse else 0.0
        configured_graph_weight = policy.graph_weight if policy.graph else 0.0
        use_graph = bool(graph_results) and policy.graph and configured_graph_weight > 0
        if use_graph:
            total = dense_weight + sparse_weight + configured_graph_weight
        else:
            total = dense_weight + sparse_weight
        if total <= 0:
            return []
        dense_w = dense_weight / total
        sparse_w = sparse_weight / total
        graph_w = configured_graph_weight / total if use_graph else 0.0

        # Build document ID to result mapping
        doc_scores: dict[str, tuple[float, RetrievalResult]] = {}

        def _fold(results: list[RetrievalResult], weight: float) -> None:
            if not weight:
                return
            for result in results:
                doc_id = self._get_doc_id(result.document)
                rrf_score = weight / (self.config.rrf_k + max(result.rank, 1))
                if doc_id in doc_scores:
                    existing_score, existing_result = doc_scores[doc_id]
                    doc_scores[doc_id] = (existing_score + rrf_score, existing_result)
                else:
                    doc_scores[doc_id] = (rrf_score, result)

        _fold(dense_results, dense_w)
        _fold(sparse_results, sparse_w)
        if use_graph:
            _fold(graph_results or [], graph_w)

        # Stable tie-break by document identity. ANN/native-sparse backends may
        # return equal-score hits in backend-dependent order; allowing dict
        # insertion order to decide would create false AB/BA benchmark drift.
        sorted_results = sorted(
            doc_scores.items(),
            key=lambda item: (-item[1][0], item[0]),
        )

        # Create final results with updated scores
        fused_results = []
        for rank, (_doc_id, (score, result)) in enumerate(sorted_results, 1):
            result.score = score
            result.source = "hybrid"
            result.rank = rank
            metadata = dict(result.document.metadata)
            metadata["retrieval_score"] = float(score)
            metadata["score"] = float(score)
            metadata["retrieval_source"] = "hybrid"
            result.document = Document(
                page_content=result.document.page_content,
                metadata=metadata,
            )
            fused_results.append(result)

        log.debug(f"RRF fusion: {len(fused_results)} results")
        return fused_results

    def _get_doc_id(self, document: Document) -> str:
        """Generate unique ID for document deduplication.

        Hashes the full ``page_content`` (not just a prefix) so that two chunks
        sharing a long boilerplate header — common in aviation manuals — are not
        collapsed into one RRF entry and silently dropped from fusion.
        """
        import hashlib

        chunk_id = (document.metadata or {}).get("chunk_id")
        if chunk_id not in (None, ""):
            return f"chunk:{chunk_id}"
        content = document.page_content
        return hashlib.md5(content.encode()).hexdigest()[:16]


# Module-level instance
_hybrid_retriever: HybridRetriever | None = None


def get_hybrid_retriever(config: HybridRetrieverConfig | None = None) -> HybridRetriever:
    """Get or create hybrid retriever instance."""
    global _hybrid_retriever
    if _hybrid_retriever is None or config is not None:
        _hybrid_retriever = HybridRetriever(config=config)
    return _hybrid_retriever
