from __future__ import annotations

from pathlib import Path

import pytest


def _active_paths(tmp_path: Path):
    from scripts.run_paired_benchmark import StorePaths

    return StorePaths(
        milvus=tmp_path / "active.db",
        embedding_registry=tmp_path / "active-registry.db",
        raptor=tmp_path / "active-raptor.db",
        visual_index=tmp_path / "active-visual.db",
        visual_assets=tmp_path / "active-assets",
        collection="active_collection",
        cache_namespace="active-cache",
    )


def test_paired_benchmark_specs_isolate_dataset_variant_and_order(tmp_path):
    from scripts.run_paired_benchmark import build_run_specs

    datasets = [tmp_path / "general.yaml", tmp_path / "hotpot.yaml"]
    for dataset in datasets:
        dataset.write_text("cases: []\n", encoding="utf-8")

    specs = build_run_specs(
        datasets,
        output_root=tmp_path / "runs",
        active=_active_paths(tmp_path),
        repeats=3,
    )

    assert len(specs) == len(datasets) * 4
    identities = {
        (
            spec.env["MILVUS_DB_URI"],
            spec.env["COLLECTION_NAME"],
            spec.env["EMBEDDING_REGISTRY_DB"],
            spec.env["RAPTOR_DB_PATH"],
            spec.env["VISUAL_INDEX_PATH"],
            spec.env["PDF_ASSET_DIR"],
            spec.env["RETRIEVAL_CACHE_NAMESPACE"],
        )
        for spec in specs
    }
    assert len(identities) == len(specs)
    assert {(spec.order, spec.position, spec.variant) for spec in specs} == {
        ("AB", 1, "control"),
        ("AB", 2, "treatment"),
        ("BA", 1, "treatment"),
        ("BA", 2, "control"),
    }
    assert all(spec.repeats == 3 for spec in specs)


def test_paired_benchmark_rejects_active_or_existing_store(tmp_path):
    from scripts.run_paired_benchmark import RunSpec, validate_run_spec

    active = _active_paths(tmp_path)
    active.milvus.touch()
    spec = RunSpec(
        dataset=tmp_path / "data.yaml",
        dataset_sha256="a" * 64,
        corpus_sha256=None,
        variant="control",
        order="AB",
        position=1,
        repeats=3,
        run_dir=tmp_path / "run",
        output_json=tmp_path / "run" / "metrics.json",
        log_path=tmp_path / "run" / "benchmark.log",
        env={
            "MILVUS_DB_URI": str(active.milvus),
            "COLLECTION_NAME": "new_collection",
            "EMBEDDING_REGISTRY_DB": str(tmp_path / "new-registry.db"),
            "RAPTOR_DB_PATH": str(tmp_path / "new-raptor.db"),
            "VISUAL_INDEX_PATH": str(tmp_path / "new-visual.db"),
            "PDF_ASSET_DIR": str(tmp_path / "new-assets"),
            "RETRIEVAL_CACHE_NAMESPACE": "new-cache",
        },
    )

    with pytest.raises(ValueError, match="active Milvus"):
        validate_run_spec(spec, active=active)

    spec.env["MILVUS_DB_URI"] = str(tmp_path / "already-exists.db")
    Path(spec.env["MILVUS_DB_URI"]).touch()
    with pytest.raises(ValueError, match="already exists"):
        validate_run_spec(spec, active=active)


def test_paired_benchmark_detects_ab_ba_quality_drift():
    from scripts.run_paired_benchmark import order_independence_report

    runs = [
        {"dataset": "d", "variant": "control", "order": "AB", "metrics": {"median_mrr": 0.8}},
        {"dataset": "d", "variant": "control", "order": "BA", "metrics": {"median_mrr": 0.7}},
        {"dataset": "d", "variant": "treatment", "order": "AB", "metrics": {"median_mrr": 0.9}},
        {"dataset": "d", "variant": "treatment", "order": "BA", "metrics": {"median_mrr": 0.9}},
    ]

    report = order_independence_report(runs, tolerance=1e-9)

    assert report["passed"] is False
    assert report["comparisons"]["d/control"]["median_mrr"]["delta"] == pytest.approx(0.1)


def test_paired_benchmark_feature_env_is_allowlisted():
    from scripts.run_paired_benchmark import parse_feature_env

    assert parse_feature_env(["COLBERT_RERANK_ENABLED=true"]) == {"COLBERT_RERANK_ENABLED": "true"}
    with pytest.raises(ValueError, match="not an allowed retrieval feature"):
        parse_feature_env(["OPENAI_API_KEY=secret"])


def test_corpus_snapshot_matches_ingestion_id_deduplication(tmp_path):
    from scripts.run_paired_benchmark import _content_snapshot_hash, _expected_corpus_snapshot

    dataset = tmp_path / "benchmark.yaml"
    dataset.write_text("cases: []\n", encoding="utf-8")
    (tmp_path / "benchmark_corpus.yaml").write_text(
        """
chunks:
  - id: duplicate
    text: old value
  - id: duplicate
    text: replacement value
  - id: unique
    text: unique value
""".strip()
        + "\n",
        encoding="utf-8",
    )

    count, content_hash = _expected_corpus_snapshot(dataset)

    assert count == 2
    assert content_hash == _content_snapshot_hash(["replacement value", "unique value"])
