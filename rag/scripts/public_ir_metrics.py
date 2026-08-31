#!/usr/bin/env python3
"""Evaluate stable query/doc runs with versioned public IR metrics."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVALUATOR_VERSION = 1


@dataclass(frozen=True)
class DatasetProtocol:
    metrics: tuple[str, ...]
    max_cutoff: int
    split: str | None
    family: str


DATASET_PROTOCOLS = {
    "nano-beir/scifact": DatasetProtocol(
        ("nDCG@10", "RR@10", "Recall@100"), 100, None, "nano-beir"
    ),
    "nano-beir/nfcorpus": DatasetProtocol(
        ("nDCG@10", "RR@10", "Recall@100"), 100, None, "nano-beir"
    ),
    "nano-beir/fiqa": DatasetProtocol(("nDCG@10", "RR@10", "Recall@100"), 100, None, "nano-beir"),
    "beir/scifact/test": DatasetProtocol(("nDCG@10", "RR@10", "Recall@100"), 100, "test", "beir"),
    "beir/nfcorpus/test": DatasetProtocol(("nDCG@10", "RR@10", "Recall@100"), 100, "test", "beir"),
    "beir/fiqa/test": DatasetProtocol(("nDCG@10", "RR@10", "Recall@100"), 100, "test", "beir"),
    "miracl/zh/dev": DatasetProtocol(("nDCG@10", "Recall@100"), 100, "dev", "miracl"),
}


def _version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def _canonical_json_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _measure_registry(names: tuple[str, ...]) -> dict[str, Any]:
    try:
        from ir_measures import RR, Recall, nDCG
    except ImportError as exc:
        raise RuntimeError("ir_measures is required; install the benchmark extra") from exc
    registry = {
        "nDCG@10": nDCG @ 10,
        "RR@10": RR @ 10,
        "Recall@100": Recall @ 100,
    }
    return {name: registry[name] for name in names}


def _qrel_records(payload: dict[str, Any] | list[dict[str, Any]]) -> tuple[list[Any], set[str]]:
    try:
        from ir_measures import Qrel
    except ImportError as exc:
        raise RuntimeError("ir_measures is required; install the benchmark extra") from exc
    rows = payload.get("qrels") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        raise ValueError("qrels must be a non-empty list")
    records = []
    query_ids: set[str] = set()
    for row in rows:
        query_id = str(row["query_id"])
        doc_id = str(row["doc_id"])
        relevance = int(row["relevance"])
        records.append(Qrel(query_id, doc_id, relevance))
        query_ids.add(query_id)
    return records, query_ids


def _run_records(ranked_run: list[dict[str, Any]]) -> tuple[list[Any], set[str]]:
    try:
        from ir_measures import ScoredDoc
    except ImportError as exc:
        raise RuntimeError("ir_measures is required; install the benchmark extra") from exc
    records = []
    query_ids: set[str] = set()
    for query_row in ranked_run:
        query_id = str(query_row["query_id"])
        doc_ids = query_row.get("doc_ids")
        scores = query_row.get("scores")
        if not isinstance(doc_ids, list):
            raise ValueError("ranked_run doc_ids must be a list")
        scores = scores if isinstance(scores, list) else []
        seen: set[str] = set()
        for index, raw_doc_id in enumerate(doc_ids):
            doc_id = str(raw_doc_id)
            if doc_id in seen:
                continue
            seen.add(doc_id)
            raw_score = scores[index] if index < len(scores) else None
            score = (
                float(raw_score)
                if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool)
                else float(len(doc_ids) - index)
            )
            records.append(ScoredDoc(query_id, doc_id, score))
        query_ids.add(query_id)
    return records, query_ids


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _comparability_reasons(
    manifest: dict[str, Any],
    run_metrics: dict[str, Any],
    protocol: DatasetProtocol | None,
    qrel_query_ids: set[str],
    run_query_ids: set[str],
) -> list[str]:
    reasons: list[str] = []
    if protocol is None:
        reasons.append("dataset_protocol_unregistered")
        return reasons
    if manifest.get("corpus_mode") != "full":
        reasons.append("sampled_corpus")
    if manifest.get("query_limit") is not None:
        reasons.append("query_limit_applied")
    if manifest.get("doc_limit") is not None:
        reasons.append("doc_limit_applied")
    if manifest.get("deduplicated") is not False:
        reasons.append("corpus_deduplicated")
    if manifest.get("split") != protocol.split:
        reasons.append("nonstandard_split")
    if manifest.get("selected_query_count") != manifest.get("source_query_count"):
        reasons.append("incomplete_query_set")
    if qrel_query_ids != run_query_ids:
        reasons.append("run_query_set_mismatch")
    if run_metrics.get("benchmark_protocol") != "public_quality":
        reasons.append("wrong_run_protocol")
    evaluation_depth = _positive_int(run_metrics.get("evaluation_depth"))
    top_k = _positive_int(run_metrics.get("top_k"))
    if (
        evaluation_depth is None
        or top_k is None
        or min(evaluation_depth, top_k) < protocol.max_cutoff
    ):
        reasons.append("evaluation_depth_too_small")
    effective = run_metrics.get("effective_retrieval_config")
    if not isinstance(effective, dict):
        reasons.append("effective_config_missing")
        return reasons
    leg_depth = _positive_int(effective.get("RETRIEVAL_LEG_TOP_K"))
    if leg_depth is None or leg_depth < protocol.max_cutoff:
        reasons.append("retrieval_depth_too_small")
    funnel_enabled = str(effective.get("RETRIEVAL_CANDIDATE_FUNNEL_ENABLED", "false")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if funnel_enabled:
        for key in (
            "RETRIEVAL_CANDIDATE_K",
            "RETRIEVAL_RERANK_K",
            "RETRIEVAL_SELECTION_K",
            "RETRIEVAL_FINAL_K",
        ):
            depth = _positive_int(effective.get(key))
            if depth is None or depth < protocol.max_cutoff:
                reasons.append(f"{key.lower()}_too_small")
    return reasons


def evaluate_public_ir(
    qrels_payload: dict[str, Any] | list[dict[str, Any]],
    ranked_run: list[dict[str, Any]],
    manifest: dict[str, Any],
    run_metrics: dict[str, Any],
) -> dict[str, Any]:
    from ir_measures import calc_aggregate

    dataset_id = str(manifest.get("dataset_id", ""))
    protocol = DATASET_PROTOCOLS.get(dataset_id)
    metric_names = (
        protocol.metrics
        if protocol is not None
        else (
            "nDCG@10",
            "RR@10",
            "Recall@100",
        )
    )
    measures = _measure_registry(metric_names)
    qrels, qrel_query_ids = _qrel_records(qrels_payload)
    run, run_query_ids = _run_records(ranked_run)
    aggregate = calc_aggregate(list(measures.values()), qrels, run)
    metric_values = {name: float(aggregate[measure]) for name, measure in measures.items()}
    reasons = _comparability_reasons(manifest, run_metrics, protocol, qrel_query_ids, run_query_ids)
    official = not reasons
    if official:
        evidence_class = "official-comparable"
    elif manifest.get("evidence_class") == "synthetic":
        evidence_class = "synthetic"
    elif manifest.get("corpus_mode") != "full" or manifest.get("query_limit") is not None:
        evidence_class = "sampled-local"
    else:
        evidence_class = "full-local"
    return {
        "schema_version": EVALUATOR_VERSION,
        "evaluator": "ir_measures",
        "evaluator_version": _version("ir_measures"),
        "dataset_id": dataset_id,
        "dataset_family": protocol.family if protocol is not None else "unregistered",
        "metric_registry": list(metric_names),
        "metrics": metric_values,
        "query_count": len(qrel_query_ids),
        "qrels_sha256": _canonical_json_sha256(qrels_payload),
        "official_comparable": official,
        "harness_comparable": True,
        "evidence_class": evidence_class,
        "comparability_reasons": reasons,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qrels", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--run-json", required=True)
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args(argv)
    try:
        qrels = json.loads(Path(args.qrels).read_text(encoding="utf-8"))
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        run_metrics = json.loads(Path(args.run_json).read_text(encoding="utf-8"))
        report = evaluate_public_ir(
            qrels,
            run_metrics.get("ranked_run", []),
            manifest,
            run_metrics,
        )
        from scripts.prepare_ir_benchmark import atomic_write_json

        atomic_write_json(args.output_json, report)
        return 0
    except Exception as exc:
        print(f"Public IR evaluation failed: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
