#!/usr/bin/env python3
"""Deterministic enabled/disabled microbenchmarks for frontier retrieval channels."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import tempfile
import time
import tracemalloc
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml
from langchain_core.documents import Document


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * fraction + 0.999999) - 1))
    return ordered[index]


def _variant_summary(
    calls: list[tuple[float, float, bool]],
) -> dict[str, Any]:
    qualities = [quality for quality, _latency, _degraded in calls]
    latencies = [latency for _quality, latency, _degraded in calls]
    return {
        "quality": statistics.median(qualities),
        "worst_quality": min(qualities),
        "p50_ms": statistics.median(latencies),
        "p95_ms": _percentile(latencies, 0.95),
        "degraded_count": sum(1 for _quality, _latency, degraded in calls if degraded),
    }


def _measure(repeats: int, call: Callable[[], tuple[float, bool]]) -> dict[str, Any]:
    rows = []
    for _ in range(repeats):
        started = time.perf_counter()
        quality, degraded = call()
        rows.append((quality, (time.perf_counter() - started) * 1000, degraded))
    return _variant_summary(rows)


def _reciprocal_rank(expected: str, ordered: list[str]) -> float:
    try:
        return 1.0 / (ordered.index(expected) + 1)
    except ValueError:
        return 0.0


def _colbert_benchmark(config: dict[str, Any], repeats: int) -> dict[str, Any]:
    from core.retrieval.colbert_reranker import ColBERTReranker, ColBERTRerankerConfig

    records = config["documents"]
    expected = config["expected_id"]
    base_order = [
        record["id"] for record in sorted(records, key=lambda item: -float(item["base_score"]))
    ]

    class Embedding:
        def encode_colbert_documents(self, texts, *, max_tokens, batch_size):
            by_text = {record["text"]: record["token_vectors"] for record in records}
            return [by_text[text] for text in texts]

    documents = [
        Document(
            page_content=record["text"],
            metadata={"benchmark_id": record["id"], "score": record["base_score"]},
        )
        for record in sorted(records, key=lambda item: -float(item["base_score"]))
    ]
    reranker = ColBERTReranker(
        Embedding(),
        ColBERTRerankerConfig(max_candidates=len(documents), batch_size=len(documents)),
    )

    disabled = _measure(repeats, lambda: (_reciprocal_rank(expected, base_order), False))

    def enabled_call():
        result = reranker.rerank(config["query_tokens"], documents, top_k=len(documents))
        order = [document.metadata["benchmark_id"] for document in result.documents]
        return _reciprocal_rank(expected, order), result.degraded

    return {"disabled": disabled, "enabled": _measure(repeats, enabled_call)}


def _terms(text: str) -> set[str]:
    import re

    return {token.casefold() for token in re.findall(r"[A-Za-z0-9_]+", text or "")}


def _raptor_benchmark(
    config: dict[str, Any],
    repeats: int,
    work_dir: Path,
) -> dict[str, Any]:
    from core.retrieval.raptor_store import RaptorStore

    documents = [
        Document(
            page_content=record["text"],
            metadata={
                "source": config["source"],
                "title_path": record["title_path"],
                "parent_id": record["parent_id"],
            },
        )
        for record in config["documents"]
    ]
    expected = set(config["expected_prefixes"])
    query_terms = _terms(config["query"])

    def quality(texts: list[str]) -> float:
        hits = {prefix for prefix in expected if any(text.startswith(prefix) for text in texts)}
        return len(hits) / len(expected)

    def disabled_call():
        ranked = sorted(
            documents,
            key=lambda document: -len(query_terms & _terms(document.page_content)),
        )[:2]
        return quality([document.page_content for document in ranked]), False

    store = RaptorStore(work_dir / "raptor.db")
    store.build_source(
        config["source"],
        documents,
        content_hash=hashlib.sha256(config["source"].encode()).hexdigest(),
        embedding_fingerprint="synthetic",
    )

    def enabled_call():
        result = store.retrieve(config["query"], top_k=2)
        return quality([document.page_content for document in result.documents]), result.degraded

    try:
        return {
            "disabled": _measure(repeats, disabled_call),
            "enabled": _measure(repeats, enabled_call),
        }
    finally:
        store.close()


def _ppr_benchmark(config: dict[str, Any], repeats: int) -> dict[str, Any]:
    from core.retrieval.graph_ppr import personalized_pagerank

    adjacency = config["adjacency"]
    seeds = set(config["seeds"])
    expected = config["expected_id"]

    def disabled_call():
        one_hop = sorted({neighbor for seed in seeds for neighbor in adjacency.get(seed, {})})
        return _reciprocal_rank(expected, one_hop), False

    def enabled_call():
        result = personalized_pagerank(adjacency, seeds, max_iterations=100, tolerance=1e-6)
        order = [node for node, _score in sorted(result.scores.items(), key=lambda item: -item[1])]
        return _reciprocal_rank(expected, order), result.degraded

    return {
        "disabled": _measure(repeats, disabled_call),
        "enabled": _measure(repeats, enabled_call),
    }


def _visual_benchmark(
    config: dict[str, Any],
    repeats: int,
    work_dir: Path,
) -> dict[str, Any]:
    from core.retrieval.visual_retriever import VisualRetriever

    class Encoder:
        def embed_query(self, query):
            return config["query_tokens"]

    retriever = VisualRetriever(
        index_path=work_dir / "visual.db",
        asset_dir=work_dir / "assets",
        encoder=Encoder(),
    )
    pages = config["pages"]
    generation = retriever.stage_pages(
        config["source"],
        hashlib.sha256(config["source"].encode()).hexdigest(),
        [record["bytes"].encode() for record in pages],
        ocr_texts=[record["ocr_text"] for record in pages],
        page_vectors=[record["token_vectors"] for record in pages],
    )
    retriever.publish_generation(generation)
    expected = int(config["expected_page"])

    def disabled_call():
        encoder = retriever._encoder
        retriever._encoder = None
        try:
            result = retriever.retrieve(config["query"], top_k=1)
        finally:
            retriever._encoder = encoder
        quality = (
            1.0 if result.documents and result.documents[0].metadata["page"] == expected else 0.0
        )
        return quality, result.degraded

    def enabled_call():
        result = retriever.retrieve(config["query"], top_k=1)
        quality = (
            1.0 if result.documents and result.documents[0].metadata["page"] == expected else 0.0
        )
        return quality, result.degraded

    try:
        return {
            "disabled": _measure(repeats, disabled_call),
            "enabled": _measure(repeats, enabled_call),
        }
    finally:
        retriever.close()


def run_frontier_benchmarks(
    fixture_path: str | Path,
    *,
    repeats: int = 3,
    work_dir: str | Path | None = None,
) -> dict[str, Any]:
    if repeats < 3:
        raise ValueError("frontier benchmarks require at least three repeats")
    path = Path(fixture_path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    root = (
        Path(work_dir)
        if work_dir is not None
        else Path(tempfile.mkdtemp(prefix="rag-frontier-benchmark-"))
    )
    root.mkdir(parents=True, exist_ok=True)
    tracemalloc.start()
    try:
        channels = {
            "colbert": _colbert_benchmark(payload["colbert"], repeats),
            "raptor": _raptor_benchmark(payload["raptor"], repeats, root / "raptor"),
            "ppr": _ppr_benchmark(payload["ppr"], repeats),
            "visual": _visual_benchmark(payload["visual"], repeats, root / "visual"),
        }
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {
        "schema_version": 1,
        "fixture_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "repeats": repeats,
        "channels": channels,
        "resource": {
            "python_peak_mb": peak / (1024 * 1024),
            "gpu_peak_mb": None,
        },
        "synthetic_encoder": True,
        "promotion_eligible": False,
        "default_decision": "keep_frontier_channels_off",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run frontier retrieval microbenchmarks.")
    parser.add_argument(
        "--fixture",
        default="data/benchmark/frontier_specialized.yaml",
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--work-dir")
    parser.add_argument("--output-json")
    args = parser.parse_args(argv)
    result = run_frontier_benchmarks(
        args.fixture,
        repeats=args.repeats,
        work_dir=args.work_dir,
    )
    serialized = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output_json:
        output = Path(args.output_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
