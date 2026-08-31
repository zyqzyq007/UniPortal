#!/usr/bin/env python3
"""
Benchmark runner — measures RAG *retrieval* effectiveness on the generic
benchmark datasets WITHOUT requiring Ollama/LLM.

Unlike ``scripts/run_eval.py`` (which drives the full harness including LLM
generation), this script targets the retrieval stack directly:

  for each case:
    1. ingest the case's corpus into Milvus + BM25 (once, cached)
    2. retrieve top_k for the case query
    3. map retrieved docs back to chunk ids (content hash) so the deterministic
       context precision/recall (set-overlap with expected_context_ids) is computable
    4. also compute answer-overlap (rule-based) using reference_answer vs the
       top retrieved chunk text

Output: a per-case + aggregate report to stdout and ``data/eval/runs/``.

Usage:
    # Chinese benchmark, general profile (domain-agnostic retrieval)
    DOMAIN_PROFILE=general uv run --frozen python scripts/run_benchmark.py \
        --dataset data/benchmark/benchmark_cmrc2018.yaml

    # English + limit
    DOMAIN_PROFILE=general uv run --frozen python scripts/run_benchmark.py \
        --dataset data/benchmark/benchmark_msmarco.yaml --limit 10
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml  # noqa: E402

from agent.eval.dataset import load_dataset  # noqa: E402
from utils.log_utils import log  # noqa: E402


def _content_id(text: str) -> str:
    """Stable 12-char content id — MUST match prepare_benchmark._chunk_id's
    normalisation (whitespace-collapse via ' '.join(split())) so a retrieved
    doc maps to the same id as the corpus chunk it came from."""
    norm = " ".join((text or "").strip().split())
    return hashlib.sha1(norm.encode()).hexdigest()[:12]


def _load_corpus(dataset_path: str) -> dict[str, dict[str, Any]]:
    """Load the sidecar <name>_corpus.yaml and index chunks by id."""
    p = Path(dataset_path)
    corpus_path = p.with_name(p.stem + "_corpus.yaml")
    if not corpus_path.exists():
        log.warning(f"Corpus file not found: {corpus_path}")
        return {}
    with corpus_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {ch["id"]: ch for ch in data.get("chunks", [])}


def _snapshot_rows(rows: list[tuple[str, str]]) -> dict[str, Any]:
    canonical = [
        {"id": str(doc_id), "text": " ".join((text or "").split())} for doc_id, text in rows
    ]
    canonical.sort(key=lambda row: (row["id"], row["text"]))
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    doc_ids = json.dumps(
        [row["id"] for row in canonical],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return {
        "row_count": len(canonical),
        "doc_ids_sha256": hashlib.sha256(doc_ids.encode("utf-8")).hexdigest(),
        "content_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }


def _corpus_snapshot(corpus_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return _snapshot_rows(
        [(str(doc_id), str(chunk.get("text", ""))) for doc_id, chunk in corpus_by_id.items()]
    )


def _bm25_store_snapshot() -> dict[str, Any]:
    from core.retrieval.bm25_retriever import get_bm25_retriever

    retriever = get_bm25_retriever()
    with retriever._lock:
        documents = list(retriever._documents)
    return _snapshot_rows(
        [
            (str(document.metadata.get("chunk_id", "")), document.page_content)
            for document in documents
        ]
    )


def _milvus_store_snapshot(manager: Any, expected_count: int) -> dict[str, Any]:
    if manager is None:
        raise RuntimeError("active Milvus index has no manager")
    stats = manager.get_collection_stats()
    actual_count = int(stats.get("row_count", -1))
    if actual_count != expected_count:
        raise RuntimeError(
            f"Milvus corpus snapshot mismatch: row_count {actual_count} != {expected_count}"
        )
    rows: list[dict[str, Any]] = []
    offset = 0
    while offset < actual_count:
        page = manager.client.query(
            collection_name=manager.config.collection_name,
            filter="",
            output_fields=["chunk_id", "text"],
            limit=min(4096, actual_count - offset),
            offset=offset,
        )
        if not page:
            break
        rows.extend(row for row in page if isinstance(row, dict))
        offset += len(page)
    return _snapshot_rows(
        [(str(row.get("chunk_id", "")), str(row.get("text", ""))) for row in rows]
    )


def _active_store_snapshot(
    policy: Any,
    corpus_by_id: dict[str, dict[str, Any]],
    manager: Any | None,
) -> dict[str, Any]:
    if not corpus_by_id:
        return {
            "available": False,
            "reason": "corpus_unavailable",
            "expected": None,
            "stores": {},
        }
    expected = _corpus_snapshot(corpus_by_id)
    stores: dict[str, Any] = {}
    if policy.dense or policy.sparse_backend == "native_m3":
        stores["milvus"] = _milvus_store_snapshot(manager, expected["row_count"])
        if any(
            stores["milvus"].get(key) != expected.get(key)
            for key in ("row_count", "doc_ids_sha256")
        ):
            raise RuntimeError("Milvus corpus snapshot mismatch")
    if policy.sparse_backend == "bm25":
        stores["bm25"] = _bm25_store_snapshot()
        if stores["bm25"] != expected:
            raise RuntimeError("BM25 corpus snapshot mismatch")
    return {"expected": expected, "stores": stores}


def _ingest_corpus(corpus_by_id: dict[str, dict[str, Any]]) -> tuple[int, Any | None]:
    """Ingest all corpus chunks into Milvus + BM25 so the retriever can find them.

    Returns the number of chunks ingested. Idempotent-ish: re-running rebuilds
    the BM25 index from Milvus each call (acceptable for a benchmark tool).
    """
    from langchain_core.documents import Document

    from core.retrieval.bm25_retriever import get_bm25_retriever
    from core.retrieval.cache import bump_retrieval_cache_version
    from core.retrieval.hybrid_retriever import HybridRetrieverConfig

    docs = []
    for cid, ch in corpus_by_id.items():
        docs.append(
            Document(
                page_content=ch.get("text", ""),
                metadata={
                    "source": ch.get("source", "benchmark"),
                    "title": ch.get("title", ""),
                    "chunk_id": cid,
                    "score": 0.0,
                },
            )
        )
    if not docs:
        return 0, None
    from core.retrieval.contextual_text import contextualize_documents_if_enabled

    docs = contextualize_documents_if_enabled(docs)
    policy = HybridRetrieverConfig().active_policy()
    manager = None
    try:
        if policy.dense or policy.sparse_backend == "native_m3":
            from documents.milvus_db import get_milvus_manager

            manager = get_milvus_manager()
            manager.add_documents(docs)
        if policy.sparse_backend == "bm25":
            bm25 = get_bm25_retriever()
            bm25.clear()
            bm25.add_documents(docs)
        bump_retrieval_cache_version()
        log.info(
            f"Ingested {len(docs)} benchmark chunks via "
            f"{','.join(_active_index_stages(policy)) or 'no-index'}"
        )
        return len(docs), manager
    except Exception:
        if manager is not None:
            manager.close()
        raise


def _owned_hybrid_retriever():
    from core.retrieval.hybrid_retriever import HybridRetriever

    return HybridRetriever()


def _close_embedding_registry() -> None:
    from documents.embedding_registry import reset_embedding_registry

    reset_embedding_registry()


def _active_index_stages(policy: Any) -> tuple[str, ...]:
    stages: list[str] = []
    if policy.dense:
        stages.append("milvus_dense")
    if policy.sparse:
        if policy.sparse_backend == "native_m3":
            stages.append("milvus_native_sparse")
        elif policy.sparse_backend == "bm25":
            stages.append("bm25")
    return tuple(stages)


def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if not path.is_dir():
        return 0
    return sum(candidate.stat().st_size for candidate in path.rglob("*") if candidate.is_file())


def _configured_store_bytes() -> int:
    values = (
        os.getenv("MILVUS_DB_URI") or os.getenv("MILVUS_URI") or "milvus_data.db",
        os.getenv("EMBEDDING_REGISTRY_DB", "data/embedding_registry.db"),
        os.getenv("RAPTOR_DB_PATH", "data/raptor.db"),
        os.getenv("VISUAL_INDEX_PATH", "data/visual_index.db"),
        os.getenv("PDF_ASSET_DIR", "data/pdf_assets"),
        os.getenv("GRAPH_STORE_DB_PATH", "data/graph_store.db"),
    )
    seen: set[Path] = set()
    total = 0
    for value in values:
        path = Path(value).expanduser().resolve(strict=False)
        if path in seen:
            continue
        seen.add(path)
        total += _path_size(path)
    return total


def _effective_retrieval_config(config: Any) -> dict[str, str]:
    def boolean(value: bool) -> str:
        return "true" if value else "false"

    def env_boolean(name: str, default: bool = False) -> str:
        return boolean(
            os.getenv(name, boolean(default)).strip().lower() in {"1", "true", "yes", "on"}
        )

    values = {
        "COLBERT_RERANK_ENABLED": env_boolean("COLBERT_RERANK_ENABLED"),
        "COLPALI_ENABLED": env_boolean("COLPALI_ENABLED"),
        "CONTEXTUAL_INDEX_ENABLED": env_boolean("CONTEXTUAL_INDEX_ENABLED"),
        "GRAPH_PPR_ENABLED": env_boolean("GRAPH_PPR_ENABLED"),
        "GRAPH_RAG_ENABLED": env_boolean("GRAPH_RAG_ENABLED"),
        "MILVUS_SPARSE_INDEX": boolean(bool(config.enable_native_sparse)),
        "QUERY_TRANSFORM_ENABLED": env_boolean("QUERY_TRANSFORM_ENABLED"),
        "RAPTOR_ENABLED": env_boolean("RAPTOR_ENABLED"),
        "RERANKER_ENABLED": boolean(bool(config.enable_reranker)),
        "RETRIEVAL_CANDIDATE_FUNNEL_ENABLED": boolean(bool(config.enable_candidate_funnel)),
        "RETRIEVAL_DENSE_ENABLED": boolean(bool(config.enable_dense)),
        "RETRIEVAL_MMR_ENABLED": boolean(bool(config.enable_mmr)),
        "RETRIEVAL_SPARSE_ENABLED": boolean(bool(config.enable_sparse)),
        "RETRIEVAL_TIME_DECAY_ENABLED": boolean(bool(config.enable_time_decay)),
        "RETRIEVAL_WORKFLOW_ENABLED": env_boolean("RETRIEVAL_WORKFLOW_ENABLED", True),
        "DENSE_WEIGHT": str(config.dense_weight),
        "MMR_LAMBDA": str(config.mmr_lambda),
        "RRF_K": str(config.rrf_k),
        "SPARSE_WEIGHT": str(config.sparse_weight),
    }
    optional_ints = {
        "RETRIEVAL_CANDIDATE_K": config.candidate_k,
        "RETRIEVAL_LEG_TOP_K": config.dense_top_k,
        "RETRIEVAL_RERANK_K": config.rerank_k,
        "RETRIEVAL_SELECTION_K": config.selection_k,
        "RETRIEVAL_FINAL_K": os.getenv("RETRIEVAL_FINAL_K"),
    }
    for key, value in optional_ints.items():
        if value not in (None, ""):
            values[key] = str(value)
    return values


def _normalize_text(text: str) -> str:
    """Normalize text for robust matching (strip + collapse whitespace)."""
    return " ".join((text or "").strip().split())


def _build_text_index(corpus_by_id: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Build a normalized-text -> chunk_id map so retrieved docs (whose Milvus
    metadata may not carry our chunk_id) can be matched back to corpus ids."""
    return {_normalize_text(ch.get("text", "")): cid for cid, ch in corpus_by_id.items()}


async def _retrieve(
    query: str,
    top_k: int,
    text_index: dict[str, str],
    corpus_by_id: dict[str, dict[str, Any]] | None = None,
    dedup_source: bool = False,
    retriever=None,
    workflow=None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Retrieve and return docs with chunk_id.

    chunk_id resolution priority:
      1. metadata.chunk_id (if Milvus preserved it)
      2. normalized-text reverse-lookup against the corpus (robust to metadata loss)
      3. content hash fallback

    When ``dedup_source`` is set, we over-fetch (2x top_k) then collapse chunks
    from the same source document to the single highest-scoring one. This
    targets the CMRC2018 failure mode where retrieval returns several chunks of
    the same Wikipedia article, diluting precision without aiding recall.
    """
    if retriever is None:
        from core.retrieval.hybrid_retriever import get_hybrid_retriever

        retriever = get_hybrid_retriever()
    fetch_k = top_k * 2 if dedup_source else top_k
    diagnostics = None
    if workflow is not None:
        workflow_result = await workflow.aretrieve(query, final_k=fetch_k)
        docs = workflow_result.documents
        diagnostics = workflow_result.diagnostics
    else:
        docs = await retriever.aretrieve(query, top_k=fetch_k)
    out = []
    for d in docs:
        meta = getattr(d, "metadata", {}) or {}
        text = getattr(d, "page_content", "") or ""
        norm = _normalize_text(text)
        cid = meta.get("chunk_id") or text_index.get(norm) or _content_id(text)
        # Resolve the source document (for source-level dedup). Prefer the
        # corpus's source for the matched chunk; fall back to metadata.
        source = ""
        if corpus_by_id and cid in corpus_by_id:
            source = corpus_by_id[cid].get("source", "")
        if not source:
            source = meta.get("source", "")
        out.append(
            {
                "chunk_id": cid,
                "text": text,
                "score": meta.get("score", 0.0),
                "source": source,
                "parent_id": meta.get("parent_id"),
                "retrieval_source": meta.get("retrieval_source", "hybrid"),
            }
        )

    if not dedup_source or len(out) <= top_k:
        return out[:top_k], diagnostics

    # Collapse same-source chunks to the highest-scoring one. This raises
    # precision when one document dominates the result set.
    seen_sources: dict[str, dict[str, Any]] = {}
    for r in out:
        src = r.get("source") or ""
        if src not in seen_sources or r["score"] > seen_sources[src]["score"]:
            seen_sources[src] = r
    # Preserve retrieval order among the survivors.
    survivor_ids = {r["chunk_id"] for r in seen_sources.values()}
    deduped = [r for r in out if r["chunk_id"] in survivor_ids]
    return deduped[:top_k], diagnostics


def _answer_overlap(reference: str, top_chunk_text: str) -> float:
    """Rule-based answer correctness: fraction of reference-answer chars found
    in the top retrieved chunk. Crude but LLM-free; signals whether retrieval
    surfaced the evidence needed to answer."""
    if not reference or not top_chunk_text:
        return 0.0
    ref = reference.strip()
    hits = sum(1 for ch in ref if ch in top_chunk_text)
    return hits / max(1, len(ref))


def _ctx_metrics(expected: list[str], retrieved: list[str]) -> tuple[float | None, float | None]:
    from agent.eval.scorer import EvalScorer

    return EvalScorer.score_context_ids(expected, retrieved)


def _rank_metrics(expected: list[str], retrieved: list[str]) -> tuple[float | None, float | None]:
    if not expected:
        return None, None
    expected_set = set(expected)
    reciprocal_rank = 0.0
    dcg = 0.0
    for rank, chunk_id in enumerate(retrieved, 1):
        if chunk_id in expected_set:
            if reciprocal_rank == 0.0:
                reciprocal_rank = 1.0 / rank
            dcg += 1.0 / math.log2(rank + 1)
    ideal_hits = min(len(expected_set), len(retrieved))
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return reciprocal_rank, (dcg / ideal if ideal else 0.0)


def _facet_coverage(diagnostics: dict[str, Any] | None) -> float | None:
    if not diagnostics:
        return None
    plan = diagnostics.get("plan")
    facet_count = plan.get("facet_count", 0) if isinstance(plan, dict) else 0
    if not isinstance(facet_count, int) or facet_count <= 0:
        return None
    uncovered = diagnostics.get("uncovered_facets")
    uncovered_count = len(uncovered) if isinstance(uncovered, list) else 0
    return max(0.0, min(1.0, (facet_count - uncovered_count) / facet_count))


def _available_mean(values: list[float | None]) -> float | None:
    available = [float(value) for value in values if value is not None]
    return statistics.fmean(available) if available else None


def _available_median(values: list[float | None]) -> float | None:
    available = [float(value) for value in values if value is not None]
    return statistics.median(available) if available else None


def _sum_nested_counts(values: list[dict[str, Any]]) -> dict[str, int]:
    total: dict[str, int] = {}
    for value in values:
        if not isinstance(value, dict):
            continue
        for key, count in value.items():
            if isinstance(count, int) and not isinstance(count, bool):
                total[str(key)] = total.get(str(key), 0) + count
    return total


def _optional_unavailable_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        statuses = row.get("optional_channel_status")
        if not isinstance(statuses, dict):
            continue
        for channel, status in statuses.items():
            if status == "unavailable_or_no_match":
                counts[str(channel)] = counts.get(str(channel), 0) + 1
    return counts


def _query_forward_count(retriever: Any) -> int | None:
    try:
        embedding = retriever.dense_manager.embedding_function
        embedding = getattr(embedding, "base", embedding)
        value = getattr(embedding, "query_forward_count", None)
        return int(value) if value is not None else None
    except Exception:
        return None


def _gpu_peak_mb() -> float | None:
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        return torch.cuda.max_memory_allocated() / (1024 * 1024)
    except Exception:
        return None


def _gpu_reserved_peak_mb() -> float | None:
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        return torch.cuda.max_memory_reserved() / (1024 * 1024)
    except Exception:
        return None


def _peak_rss_mb() -> float | None:
    try:
        import resource

        value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value / 1024 if sys.platform != "darwin" else value / (1024 * 1024)
    except Exception:
        return None


def _resource_probe_status(
    *,
    peak_rss_mb: float | None,
    gpu_peak_mb: float | None,
    gpu_reserved_peak_mb: float | None,
    query_forwards: int | None,
) -> dict[str, dict[str, Any]]:
    values = {
        "peak_rss_mb": (peak_rss_mb, "rss_probe_failed"),
        "gpu_peak_mb": (gpu_peak_mb, "cuda_unavailable_or_probe_failed"),
        "gpu_reserved_peak_mb": (
            gpu_reserved_peak_mb,
            "cuda_unavailable_or_probe_failed",
        ),
        "query_embedding_forwards": (
            query_forwards,
            "embedding_counter_unavailable",
        ),
    }
    return {
        key: {
            "available": value is not None,
            "reason": None if value is not None else reason,
        }
        for key, (value, reason) in values.items()
    }


def _reset_gpu_peak() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    except Exception:
        return


def _latency_summary(latencies_ms: list[float]) -> dict[str, float | None]:
    if not latencies_ms:
        return {
            "first_query_ms": None,
            "cold_ms": None,
            "warm_p50_ms": None,
            "warm_p95_ms": None,
        }
    warm = sorted(latencies_ms[1:])
    if not warm:
        return {
            "first_query_ms": latencies_ms[0],
            "cold_ms": latencies_ms[0],
            "warm_p50_ms": None,
            "warm_p95_ms": None,
        }
    p95_index = max(0, min(len(warm) - 1, int(len(warm) * 0.95 + 0.999999) - 1))
    return {
        "first_query_ms": latencies_ms[0],
        "cold_ms": latencies_ms[0],
        "warm_p50_ms": statistics.median(warm),
        "warm_p95_ms": warm[p95_index],
    }


def _quality_summary(run_metrics: list[dict[str, float]]) -> dict[str, float]:
    def values(key: str) -> list[float]:
        return [float(metrics.get(key, 0.0)) for metrics in run_metrics]

    hit_rates = values("hit_rate")
    precisions = values("avg_context_precision")
    recalls = values("avg_context_recall")
    overlaps = values("avg_answer_overlap")
    mrrs = values("mrr")
    ndcgs = values("ndcg")
    return {
        "median_hit_rate": statistics.median(hit_rates),
        "worst_hit_rate": min(hit_rates),
        "median_context_precision": statistics.median(precisions),
        "worst_context_precision": min(precisions),
        "median_context_recall": statistics.median(recalls),
        "worst_context_recall": min(recalls),
        "median_answer_overlap_advisory": statistics.median(overlaps),
        "worst_answer_overlap_advisory": min(overlaps),
        "median_mrr": statistics.median(mrrs),
        "worst_mrr": min(mrrs),
        "median_ndcg": statistics.median(ndcgs),
        "worst_ndcg": min(ndcgs),
    }


async def _run(args: argparse.Namespace) -> int:
    run_started = time.perf_counter()
    protocol = getattr(args, "benchmark_protocol", "production_performance")
    if protocol == "public_quality" and int(args.top_k) < 100:
        log.error("public_quality requires top_k >= 100")
        return 2
    preparation_started = time.perf_counter()
    cases = load_dataset(args.dataset)
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        log.error(f"No cases loaded from {args.dataset}")
        return 2
    corpus_by_id = _load_corpus(args.dataset)
    shared_preparation_ms = (time.perf_counter() - preparation_started) * 1000

    from core.retrieval.hybrid_retriever import HybridRetrieverConfig

    ingestion_config = HybridRetrieverConfig()
    active_policy = ingestion_config.active_policy()

    ingest_manager = None
    retriever = None
    workflow = None
    dense_manager = None
    try:
        ingest_started = time.perf_counter()
        ingested_count = 0
        if corpus_by_id:
            ingested_count, ingest_manager = _ingest_corpus(corpus_by_id)
        else:
            log.warning("No corpus — retrieving against whatever is already indexed")
        active_store_snapshot = _active_store_snapshot(active_policy, corpus_by_id, ingest_manager)
        index_build_ms = (time.perf_counter() - ingest_started) * 1000
        text_index = _build_text_index(corpus_by_id)
        retriever_started = time.perf_counter()
        retriever = _owned_hybrid_retriever()
        retriever_ready_ms = (time.perf_counter() - retriever_started) * 1000
        from core.retrieval.workflow import RetrievalWorkflow, retrieval_workflow_enabled

        if retrieval_workflow_enabled():
            workflow = RetrievalWorkflow(retriever=retriever)
        _reset_gpu_peak()
        forwards_before = _query_forward_count(retriever)

        print(f"\n{'=' * 64}")
        repeats = max(1, int(getattr(args, "repeats", 1)))
        print(
            f"Benchmark: {args.dataset}  "
            f"({len(cases)} cases, top_k={args.top_k}, repeats={repeats})"
        )
        print(f"{'=' * 64}")

        run_metrics = []
        all_latencies_ms = []
        ranked_run: list[dict[str, Any]] = []
        total_started = time.perf_counter()
        for repeat_index in range(repeats):
            from core.retrieval.cache import get_retrieval_cache

            get_retrieval_cache().clear()
            rows = []
            latencies_ms = []
            print(f"\nRUN {repeat_index + 1}/{repeats}")
            for case in cases:
                query_started = time.perf_counter()
                retrieval_output = await _retrieve(
                    case.query,
                    top_k=args.top_k,
                    text_index=text_index,
                    corpus_by_id=corpus_by_id,
                    dedup_source=args.dedup_source,
                    retriever=retriever,
                    workflow=workflow,
                )
                if (
                    isinstance(retrieval_output, tuple)
                    and len(retrieval_output) == 2
                    and (retrieval_output[1] is None or isinstance(retrieval_output[1], dict))
                ):
                    retrieved, diagnostics = retrieval_output
                else:
                    retrieved, diagnostics = retrieval_output, None
                query_latency_ms = (time.perf_counter() - query_started) * 1000
                latencies_ms.append(query_latency_ms)
                retrieved_ids = [item["chunk_id"] for item in retrieved]
                precision, recall = _ctx_metrics(case.expected_context_ids, retrieved_ids)
                reciprocal_rank, ndcg = _rank_metrics(case.expected_context_ids, retrieved_ids)
                top_text = retrieved[0]["text"] if retrieved else ""
                answer_overlap = _answer_overlap(case.reference_answer, top_text)
                hit = bool(set(case.expected_context_ids) & set(retrieved_ids))
                rows.append(
                    {
                        "id": case.id,
                        "query": case.query[:40],
                        "ctx_precision": precision,
                        "ctx_recall": recall,
                        "answer_overlap": answer_overlap,
                        "retrieved_hit": hit,
                        "n_retrieved": len(retrieved),
                        "latency_ms": query_latency_ms,
                        "reciprocal_rank": reciprocal_rank,
                        "ndcg": ndcg,
                        "retry_used": bool(diagnostics and diagnostics.get("retry_action")),
                        "degraded": bool(diagnostics and diagnostics.get("degraded")),
                        "safe_refusal": bool(
                            diagnostics and diagnostics.get("should_generate") is False
                        ),
                        "distinct_sources": len(
                            {item.get("source") for item in retrieved if item.get("source")}
                        ),
                        "distinct_parents": len(
                            {item.get("parent_id") or item.get("chunk_id") for item in retrieved}
                        ),
                        "facet_coverage": _facet_coverage(diagnostics),
                        "channel_counts": (
                            diagnostics.get("channel_counts", {}) if diagnostics else {}
                        ),
                        "optional_channel_status": (
                            diagnostics.get("optional_channel_status", {}) if diagnostics else {}
                        ),
                    }
                )
                if repeat_index == 0:
                    ranked_run.append(
                        {
                            "query_id": case.id,
                            "doc_ids": retrieved_ids,
                            "scores": [item.get("score") for item in retrieved],
                        }
                    )
                flag = "✓" if hit else "✗"
                print(
                    f"  {flag} {case.id:<14} "
                    f"P={precision if precision is not None else 'n/a':<5} "
                    f"R={recall if recall is not None else 'n/a':<5} "
                    f"ans_ov={answer_overlap:.2f} latency={query_latency_ms:.1f}ms "
                    f"| {case.query[:30]}"
                )

            precisions = [x["ctx_precision"] for x in rows if x["ctx_precision"] is not None]
            recalls = [x["ctx_recall"] for x in rows if x["ctx_recall"] is not None]
            overlaps = [x["answer_overlap"] for x in rows]
            reciprocal_ranks = [
                x["reciprocal_rank"] for x in rows if x["reciprocal_rank"] is not None
            ]
            ndcgs = [x["ndcg"] for x in rows if x["ndcg"] is not None]
            hits = sum(1 for x in rows if x["retrieved_hit"])
            metrics = {
                "hit_rate": hits / len(rows) if rows else 0.0,
                "avg_context_precision": (sum(precisions) / len(precisions) if precisions else 0.0),
                "avg_context_recall": sum(recalls) / len(recalls) if recalls else 0.0,
                "avg_answer_overlap": sum(overlaps) / len(overlaps) if overlaps else 0.0,
                "mrr": (sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0),
                "ndcg": sum(ndcgs) / len(ndcgs) if ndcgs else 0.0,
                "retry_count": sum(1 for row in rows if row["retry_used"]),
                "degraded_count": sum(1 for row in rows if row["degraded"]),
                "safe_refusal_count": sum(1 for row in rows if row["safe_refusal"]),
                "avg_distinct_sources": statistics.fmean(row["distinct_sources"] for row in rows),
                "avg_distinct_parents": statistics.fmean(row["distinct_parents"] for row in rows),
                "avg_facet_coverage": _available_mean([row["facet_coverage"] for row in rows]),
                "channel_counts": _sum_nested_counts([row["channel_counts"] for row in rows]),
                "optional_unavailable_counts": _optional_unavailable_counts(rows),
            }
            run_metrics.append(metrics)
            all_latencies_ms.extend(latencies_ms)
            print(
                f"  run aggregate: hit={metrics['hit_rate']:.1%}, "
                f"precision={metrics['avg_context_precision']:.3f}, "
                f"recall={metrics['avg_context_recall']:.3f}, "
                f"MRR={metrics['mrr']:.3f}, nDCG={metrics['ndcg']:.3f}, "
                f"answer_overlap={metrics['avg_answer_overlap']:.3f} (advisory)"
            )

        elapsed = time.perf_counter() - total_started
        quality = _quality_summary(run_metrics)
        latency = _latency_summary(all_latencies_ms)
        forwards_after = _query_forward_count(retriever)
        query_forwards = (
            forwards_after - forwards_before
            if forwards_after is not None and forwards_before is not None
            else None
        )
        gpu_peak_mb = _gpu_peak_mb()
        gpu_reserved_peak_mb = _gpu_reserved_peak_mb()
        peak_rss_mb = _peak_rss_mb()
        store_bytes = _configured_store_bytes()
        throughput_qps = (len(cases) * repeats / elapsed) if elapsed > 0 else None
        resource_probe_status = _resource_probe_status(
            peak_rss_mb=peak_rss_mb,
            gpu_peak_mb=gpu_peak_mb,
            gpu_reserved_peak_mb=gpu_reserved_peak_mb,
            query_forwards=query_forwards,
        )

        print(f"\n{'-' * 64}")
        print(f"AGGREGATE ({len(cases)} cases x {repeats} runs, {elapsed:.1f}s)")
        print(
            "  hit rate median/worst                    : "
            f"{quality['median_hit_rate']:.1%}/{quality['worst_hit_rate']:.1%}"
        )
        print(
            "  context precision median/worst           : "
            f"{quality['median_context_precision']:.3f}/"
            f"{quality['worst_context_precision']:.3f}"
        )
        print(
            "  context recall median/worst              : "
            f"{quality['median_context_recall']:.3f}/{quality['worst_context_recall']:.3f}"
        )
        print(
            "  answer overlap median/worst (advisory)   : "
            f"{quality['median_answer_overlap_advisory']:.3f}/"
            f"{quality['worst_answer_overlap_advisory']:.3f}"
        )
        print(
            "  MRR median/worst                          : "
            f"{quality['median_mrr']:.3f}/{quality['worst_mrr']:.3f}"
        )
        print(
            "  nDCG median/worst                         : "
            f"{quality['median_ndcg']:.3f}/{quality['worst_ndcg']:.3f}"
        )
        print(
            f"  latency first-query/warm P50/P95 (ms)    : "
            f"{latency['first_query_ms']!s}/"
            f"{latency['warm_p50_ms']!s}/{latency['warm_p95_ms']!s}"
        )
        print(
            f"  ingest ms / store bytes / throughput QPS : "
            f"{index_build_ms:.1f}/{store_bytes}/{throughput_qps}"
        )
        print(
            f"  query forwards / GPU alloc/reserved MB    : "
            f"{query_forwards}/{gpu_peak_mb}/{gpu_reserved_peak_mb}"
        )

        # --- regression gate: persist + compare against a stored baseline ---
        exit_code = 0
        metrics = {
            "hit_rate": quality["worst_hit_rate"],
            "avg_context_precision": quality["worst_context_precision"],
            "avg_context_recall": quality["worst_context_recall"],
            "avg_answer_overlap": quality["median_answer_overlap_advisory"],
            "n_cases": len(cases),
            "top_k": args.top_k,
            "dedup_source": args.dedup_source,
            "repeats": repeats,
            "benchmark_protocol": protocol,
            "evaluation_depth": args.top_k,
            "shared_preparation_ms": shared_preparation_ms,
            "index_build_ms": index_build_ms,
            "retriever_ready_ms": retriever_ready_ms,
            "runner_wall_ms": (time.perf_counter() - run_started) * 1000,
            "throughput_qps": throughput_qps,
            "store_bytes": store_bytes,
            "peak_rss_mb": peak_rss_mb,
            "query_embedding_forwards": query_forwards,
            "gpu_peak_mb": gpu_peak_mb,
            "gpu_reserved_peak_mb": gpu_reserved_peak_mb,
            "resource_probe_status": resource_probe_status,
            "ingested_count": ingested_count,
            "active_index_stages": list(_active_index_stages(active_policy)),
            "active_store_snapshot": active_store_snapshot,
            "effective_retrieval_config": _effective_retrieval_config(
                getattr(retriever, "config", ingestion_config)
            ),
            "ranked_run": ranked_run,
            "retry_count": sum(metric["retry_count"] for metric in run_metrics),
            "degraded_count": sum(metric["degraded_count"] for metric in run_metrics),
            "safe_refusal_count": sum(metric["safe_refusal_count"] for metric in run_metrics),
            "avg_distinct_sources": statistics.median(
                metric["avg_distinct_sources"] for metric in run_metrics
            ),
            "avg_distinct_parents": statistics.median(
                metric["avg_distinct_parents"] for metric in run_metrics
            ),
            "avg_facet_coverage": _available_median(
                [metric["avg_facet_coverage"] for metric in run_metrics]
            ),
            "channel_counts": _sum_nested_counts(
                [metric["channel_counts"] for metric in run_metrics]
            ),
            "optional_unavailable_counts": _sum_nested_counts(
                [metric["optional_unavailable_counts"] for metric in run_metrics]
            ),
            **quality,
            **latency,
        }
        if args.fail_on_regression:
            exit_code = _regression_gate(args.dataset, metrics)
        if args.update_baseline:
            _save_baseline(args.dataset, metrics)
            print("  (baseline updated)")
        if getattr(args, "output_json", None):
            output_path = Path(args.output_json)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(metrics, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
        print(f"{'-' * 64}\n")
        return exit_code
    finally:
        if retriever is not None:
            dense_manager = getattr(retriever, "_dense_manager", None)
            try:
                retriever.close()
            except Exception as exc:
                log.debug(f"Benchmark retriever close skipped: {exc}")
        if dense_manager is not None:
            try:
                dense_manager.close()
            except Exception as exc:
                log.debug(f"Benchmark dense manager close skipped: {exc}")
        if ingest_manager is not None:
            try:
                ingest_manager.close()
            except Exception as exc:
                log.debug(f"Benchmark ingest manager close skipped: {exc}")
        try:
            _close_embedding_registry()
        except Exception as exc:
            log.debug(f"Benchmark registry close skipped: {exc}")


BENCHMARK_RUNS_DIR = Path("data/eval/runs")
BENCHMARK_BASELINES_DIR = Path("data/benchmark/baselines")
BASELINE_SCHEMA_VERSION = 1
QUALITY_SEMANTICS_VERSION = 1
_GATE_METRIC_KEYS = ("hit_rate", "avg_context_precision", "avg_context_recall")
_BASELINE_METRIC_KEYS = (
    *_GATE_METRIC_KEYS,
    "avg_answer_overlap",
    "median_hit_rate",
    "worst_hit_rate",
    "median_context_precision",
    "worst_context_precision",
    "median_context_recall",
    "worst_context_recall",
    "median_answer_overlap_advisory",
    "worst_answer_overlap_advisory",
    "cold_ms",
    "warm_p50_ms",
    "warm_p95_ms",
    "median_mrr",
    "worst_mrr",
    "median_ndcg",
    "worst_ndcg",
    "query_embedding_forwards",
    "gpu_peak_mb",
    "retry_count",
    "degraded_count",
)


def _baseline_path(dataset: str) -> Path:
    stem = Path(dataset).stem
    return BENCHMARK_BASELINES_DIR / f"{stem}_baseline.json"


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _baseline_config(dataset: str, metrics: dict[str, Any]) -> dict[str, Any]:
    from utils.env_utils import resolve_embedding_settings

    dataset_path = Path(dataset)
    corpus_path = dataset_path.with_name(dataset_path.stem + "_corpus.yaml")
    settings = resolve_embedding_settings()
    return {
        "dataset": dataset_path.stem,
        "dataset_sha256": _file_sha256(dataset_path),
        "corpus_sha256": _file_sha256(corpus_path),
        "n_cases": metrics.get("n_cases"),
        "top_k": metrics.get("top_k"),
        "dedup_source": metrics.get("dedup_source"),
        "repeats": metrics.get("repeats"),
        "embedding": {
            "provider": settings.provider,
            "model": settings.model,
            "dimension": settings.dimension,
            "sparse_enabled": settings.sparse_enabled,
        },
    }


def _baseline_payload(dataset: str, metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "quality_semantics_version": QUALITY_SEMANTICS_VERSION,
        "config": _baseline_config(dataset, metrics),
        "metrics": {key: metrics.get(key) for key in _BASELINE_METRIC_KEYS},
    }


def _finite_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _valid_sha256(value: Any, *, optional: bool = False) -> bool:
    if optional and value is None:
        return True
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(char in "0123456789abcdef" for char in value.lower())


def _baseline_validation_error(
    payload: Any,
    current_config: dict[str, Any],
) -> str | None:
    if not isinstance(payload, dict):
        return "baseline root must be an object"
    if payload.get("schema_version") != BASELINE_SCHEMA_VERSION:
        return "schema_version mismatch"
    if payload.get("quality_semantics_version") != QUALITY_SEMANTICS_VERSION:
        return "quality_semantics_version mismatch"

    config = payload.get("config")
    if not isinstance(config, dict):
        return "config must be an object"
    if not isinstance(config.get("dataset"), str) or not config["dataset"]:
        return "config.dataset must be a non-empty string"
    if not _valid_sha256(config.get("dataset_sha256")):
        return "config.dataset_sha256 must be a SHA-256 digest"
    if not _valid_sha256(config.get("corpus_sha256"), optional=True):
        return "config.corpus_sha256 must be a SHA-256 digest or null"
    for key in ("n_cases", "top_k", "repeats"):
        value = config.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return f"config.{key} must be a positive integer"
    if not isinstance(config.get("dedup_source"), bool):
        return "config.dedup_source must be boolean"
    embedding = config.get("embedding")
    if not isinstance(embedding, dict):
        return "config.embedding must be an object"
    if embedding.get("provider") not in {"local", "api"}:
        return "config.embedding.provider is invalid"
    if not isinstance(embedding.get("model"), str) or not embedding["model"]:
        return "config.embedding.model must be a non-empty string"
    dimension = embedding.get("dimension")
    if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
        return "config.embedding.dimension must be a positive integer"
    if not isinstance(embedding.get("sparse_enabled"), bool):
        return "config.embedding.sparse_enabled must be boolean"
    if config != current_config:
        return "baseline config does not match the current benchmark"

    stored_metrics = payload.get("metrics")
    if not isinstance(stored_metrics, dict):
        return "metrics must be an object"
    for key in _GATE_METRIC_KEYS:
        value = stored_metrics.get(key)
        if not _finite_number(value) or not 0.0 <= float(value) <= 1.0:
            return f"metrics.{key} must be finite and within [0, 1]"
    for key in (
        "avg_answer_overlap",
        "median_hit_rate",
        "worst_hit_rate",
        "median_context_precision",
        "worst_context_precision",
        "median_context_recall",
        "worst_context_recall",
        "median_answer_overlap_advisory",
        "worst_answer_overlap_advisory",
    ):
        value = stored_metrics.get(key)
        if value is not None and (not _finite_number(value) or not 0.0 <= float(value) <= 1.0):
            return f"metrics.{key} must be finite and within [0, 1]"
    for key in ("cold_ms", "warm_p50_ms", "warm_p95_ms"):
        value = stored_metrics.get(key)
        if value is not None and (not _finite_number(value) or float(value) < 0.0):
            return f"metrics.{key} must be finite and non-negative"
    return None


def _save_baseline(dataset: str, metrics: dict[str, Any]) -> None:
    path = _baseline_path(dataset)
    payload = _baseline_payload(dataset, metrics)
    error = _baseline_validation_error(payload, payload["config"])
    if error:
        raise ValueError(f"refusing to write invalid benchmark baseline: {error}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _regression_gate(dataset: str, metrics: dict[str, Any]) -> int:
    """Compare current metrics to the stored baseline; return 1 on regression.

    A regression is a drop beyond a small tolerance (2 points = 0.02) in any of
    hit_rate / context_precision / context_recall. answer_overlap is advisory.
    Missing, malformed, or configuration-mismatched baselines fail closed.
    """
    bp = _baseline_path(dataset)
    if not bp.exists():
        print(f"\n!! BASELINE MISSING: {bp}")
        print("Run with --update-baseline after an explicitly reviewed benchmark run.\n")
        return 1
    try:
        with bp.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        current_config = _baseline_config(dataset, metrics)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"\n!! BASELINE INVALID: {exc}\n")
        return 1
    error = _baseline_validation_error(payload, current_config)
    if error:
        print(f"\n!! BASELINE INVALID: {error}\n")
        return 1
    base = payload["metrics"]

    for key in _GATE_METRIC_KEYS:
        value = metrics.get(key)
        if not _finite_number(value) or not 0.0 <= float(value) <= 1.0:
            print(f"\n!! CURRENT METRIC INVALID: {key}={value!r}\n")
            return 1

    tol = 0.02
    regressed = []
    for key in _GATE_METRIC_KEYS:
        cur = float(metrics[key])
        prev = float(base[key])
        if cur < prev - tol:
            regressed.append(f"{key}: {prev:.3f} -> {cur:.3f}")

    if regressed:
        print(f"\n!! REGRESSION DETECTED on {dataset}:")
        for r in regressed:
            print(f"    {r}")
        print("Run with --update-baseline to accept the new values if intended.\n")
        return 1
    print("  regression gate: PASS (no metric dropped beyond tolerance)\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the RAG retrieval benchmark (no LLM needed).")
    parser.add_argument("--dataset", required=True, help="Path to benchmark_<name>.yaml")
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument(
        "--benchmark-protocol",
        choices=("production_performance", "public_quality"),
        default="production_performance",
        help="Separate actual production budgets from depth>=100 public-quality runs.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N cases")
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        choices=range(1, 101),
        metavar="1..100",
        help="Repeat retrieval to report median/worst quality (default: 3).",
    )
    parser.add_argument(
        "--dedup-source",
        action="store_true",
        help="Collapse same-source chunks to the top-scoring one (raises precision).",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help="Write aggregate metrics to this path (runtime artifact).",
    )
    baseline_group = parser.add_mutually_exclusive_group()
    baseline_group.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Compare to stored baseline; exit 1 if metrics regress (CI gate).",
    )
    baseline_group.add_argument(
        "--update-baseline",
        action="store_true",
        help="Persist the current run as the new baseline.",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
