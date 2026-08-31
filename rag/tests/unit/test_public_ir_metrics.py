from __future__ import annotations

import pytest

from scripts.public_ir_metrics import evaluate_public_ir


def _qrels():
    return {
        "schema_version": 1,
        "qrels": [
            {"query_id": "q1", "doc_id": "d1", "relevance": 3},
            {"query_id": "q1", "doc_id": "d2", "relevance": 1},
            {"query_id": "q2", "doc_id": "d3", "relevance": 2},
        ],
    }


def _ranked_run():
    return [
        {"query_id": "q1", "doc_ids": ["d2", "d1"], "scores": [2.0, 1.0]},
        {"query_id": "q2", "doc_ids": ["x", "d3"], "scores": [2.0, 1.0]},
    ]


def _manifest(**overrides):
    manifest = {
        "schema_version": 1,
        "dataset_id": "nano-beir/scifact",
        "split": None,
        "corpus_mode": "full",
        "query_limit": None,
        "doc_limit": None,
        "deduplicated": False,
        "selected_query_count": 2,
        "source_query_count": 2,
        "evidence_class": "official-comparable",
    }
    manifest.update(overrides)
    return manifest


def _run_metrics(**overrides):
    metrics = {
        "benchmark_protocol": "public_quality",
        "evaluation_depth": 100,
        "top_k": 100,
        "effective_retrieval_config": {
            "RETRIEVAL_LEG_TOP_K": "200",
            "RETRIEVAL_CANDIDATE_K": "200",
            "RETRIEVAL_RERANK_K": "200",
            "RETRIEVAL_SELECTION_K": "100",
            "RETRIEVAL_FINAL_K": "100",
        },
    }
    metrics.update(overrides)
    return metrics


def test_public_ir_metrics_match_known_graded_run():
    report = evaluate_public_ir(_qrels(), _ranked_run(), _manifest(), _run_metrics())

    assert report["metrics"]["nDCG@10"] == pytest.approx(0.7138186672809821)
    assert report["metrics"]["RR@10"] == pytest.approx(0.75)
    assert report["metrics"]["Recall@100"] == pytest.approx(1.0)
    assert report["official_comparable"] is True
    assert report["evidence_class"] == "official-comparable"
    assert report["query_count"] == 2


@pytest.mark.parametrize(
    ("manifest_update", "run_update", "reason"),
    [
        ({"corpus_mode": "qrels-plus-negatives"}, {}, "sampled_corpus"),
        ({"query_limit": 1}, {}, "query_limit_applied"),
        ({}, {"benchmark_protocol": "production_performance"}, "wrong_run_protocol"),
        ({}, {"evaluation_depth": 10, "top_k": 10}, "evaluation_depth_too_small"),
    ],
)
def test_official_gate_rejects_nonstandard_protocol(manifest_update, run_update, reason):
    report = evaluate_public_ir(
        _qrels(),
        _ranked_run(),
        _manifest(**manifest_update),
        _run_metrics(**run_update),
    )

    assert report["official_comparable"] is False
    assert reason in report["comparability_reasons"]
    expected_class = "sampled-local" if manifest_update else "full-local"
    assert report["evidence_class"] == expected_class


def test_miracl_protocol_omits_reciprocal_rank():
    report = evaluate_public_ir(
        _qrels(),
        _ranked_run(),
        _manifest(dataset_id="miracl/zh/dev", split="dev", evidence_class="sampled-local"),
        _run_metrics(),
    )

    assert set(report["metrics"]) == {"nDCG@10", "Recall@100"}
