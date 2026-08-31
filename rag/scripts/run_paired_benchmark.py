#!/usr/bin/env python3
"""Run isolated AB/BA retrieval benchmarks in fresh subprocesses."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

QUALITY_KEYS = (
    "median_hit_rate",
    "median_context_precision",
    "median_context_recall",
    "median_mrr",
    "median_ndcg",
)

_FEATURE_ENV_KEYS = {
    "RETRIEVAL_WORKFLOW_ENABLED",
    "RETRIEVAL_CANDIDATE_FUNNEL_ENABLED",
    "CONTEXTUAL_INDEX_ENABLED",
    "QUERY_TRANSFORM_ENABLED",
    "COLBERT_RERANK_ENABLED",
    "RAPTOR_ENABLED",
    "GRAPH_PPR_ENABLED",
    "COLPALI_ENABLED",
    "RETRIEVAL_CANDIDATE_K",
    "RETRIEVAL_RERANK_K",
    "RETRIEVAL_SELECTION_K",
    "RETRIEVAL_FINAL_K",
}

_EXPERIMENT_DEFAULTS = {
    "RETRIEVAL_WORKFLOW_ENABLED": "false",
    "RETRIEVAL_CANDIDATE_FUNNEL_ENABLED": "false",
    "CONTEXTUAL_INDEX_ENABLED": "false",
    "QUERY_TRANSFORM_ENABLED": "false",
    "COLBERT_RERANK_ENABLED": "false",
    "RAPTOR_ENABLED": "false",
    "GRAPH_PPR_ENABLED": "false",
    "COLPALI_ENABLED": "false",
}


@dataclass(frozen=True)
class StorePaths:
    milvus: Path
    embedding_registry: Path
    raptor: Path
    visual_index: Path
    visual_assets: Path
    collection: str
    cache_namespace: str


@dataclass
class RunSpec:
    dataset: Path
    dataset_sha256: str
    corpus_sha256: str | None
    variant: str
    order: str
    position: int
    repeats: int
    run_dir: Path
    output_json: Path
    log_path: Path
    env: dict[str, str]


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _corpus_path(dataset: Path) -> Path:
    return dataset.with_name(dataset.stem + "_corpus.yaml")


def current_store_paths() -> StorePaths:
    return StorePaths(
        milvus=Path(os.getenv("MILVUS_DB_URI") or os.getenv("MILVUS_URI") or "milvus_data.db"),
        embedding_registry=Path(os.getenv("EMBEDDING_REGISTRY_DB", "data/embedding_registry.db")),
        raptor=Path(os.getenv("RAPTOR_DB_PATH", "data/raptor.db")),
        visual_index=Path(os.getenv("VISUAL_INDEX_PATH", "data/visual_index.db")),
        visual_assets=Path(os.getenv("PDF_ASSET_DIR", "data/pdf_assets")),
        collection=os.getenv("COLLECTION_NAME", "rag_knowledge_base"),
        cache_namespace=os.getenv("RETRIEVAL_CACHE_NAMESPACE", "default"),
    )


def parse_feature_env(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"feature env must use KEY=VALUE: {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        if key not in _FEATURE_ENV_KEYS:
            raise ValueError(f"{key!r} is not an allowed retrieval feature")
        parsed[key] = value.strip()
    return parsed


def build_run_specs(
    datasets: list[Path],
    *,
    output_root: Path,
    active: StorePaths,
    repeats: int,
    treatment_env: dict[str, str] | None = None,
) -> list[RunSpec]:
    treatment_env = dict(treatment_env or {})
    specs: list[RunSpec] = []
    order_variants = {
        "AB": ("control", "treatment"),
        "BA": ("treatment", "control"),
    }
    for dataset in datasets:
        dataset = dataset.resolve()
        dataset_hash = _file_sha256(dataset)
        if dataset_hash is None:
            raise ValueError(f"dataset does not exist: {dataset}")
        corpus_hash = _file_sha256(_corpus_path(dataset))
        for order, variants in order_variants.items():
            for position, variant in enumerate(variants, 1):
                raw_id = f"{dataset_hash}:{order}:{position}:{variant}"
                suffix = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:10]
                stem = "".join(char if char.isalnum() else "_" for char in dataset.stem)[:24]
                run_name = f"{stem}_{order.lower()}{position}_{variant}_{suffix}"
                run_dir = output_root / run_name
                feature_env = dict(_EXPERIMENT_DEFAULTS)
                if variant == "treatment":
                    feature_env["RETRIEVAL_WORKFLOW_ENABLED"] = "true"
                    feature_env.update(treatment_env)
                env = {
                    **feature_env,
                    "DOMAIN_PROFILE": "general",
                    "MILVUS_DB_URI": str(run_dir / "milvus.db"),
                    "COLLECTION_NAME": f"rfo_{stem}_{suffix}"[:60],
                    "EMBEDDING_REGISTRY_DB": str(run_dir / "embedding_registry.db"),
                    "RAPTOR_DB_PATH": str(run_dir / "raptor.db"),
                    "VISUAL_INDEX_PATH": str(run_dir / "visual_index.db"),
                    "PDF_ASSET_DIR": str(run_dir / "pdf_assets"),
                    "RETRIEVAL_CACHE_NAMESPACE": f"rfo-{suffix}",
                }
                spec = RunSpec(
                    dataset=dataset,
                    dataset_sha256=dataset_hash,
                    corpus_sha256=corpus_hash,
                    variant=variant,
                    order=order,
                    position=position,
                    repeats=repeats,
                    run_dir=run_dir,
                    output_json=run_dir / "metrics.json",
                    log_path=run_dir / "benchmark.log",
                    env=env,
                )
                _assert_not_active(spec, active)
                specs.append(spec)
    return specs


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _assert_not_active(spec: RunSpec, active: StorePaths) -> None:
    if _resolved(Path(spec.env["MILVUS_DB_URI"])) == _resolved(active.milvus):
        raise ValueError("paired benchmark refuses the active Milvus store")
    if spec.env["COLLECTION_NAME"] == active.collection:
        raise ValueError("paired benchmark refuses the active Milvus collection")
    comparisons = (
        ("EMBEDDING_REGISTRY_DB", active.embedding_registry),
        ("RAPTOR_DB_PATH", active.raptor),
        ("VISUAL_INDEX_PATH", active.visual_index),
        ("PDF_ASSET_DIR", active.visual_assets),
    )
    for key, active_path in comparisons:
        if _resolved(Path(spec.env[key])) == _resolved(active_path):
            raise ValueError(f"paired benchmark refuses active path for {key}")
    if spec.env["RETRIEVAL_CACHE_NAMESPACE"] == active.cache_namespace:
        raise ValueError("paired benchmark refuses the active cache namespace")


def validate_run_spec(spec: RunSpec, *, active: StorePaths) -> None:
    _assert_not_active(spec, active)
    for key in (
        "MILVUS_DB_URI",
        "EMBEDDING_REGISTRY_DB",
        "RAPTOR_DB_PATH",
        "VISUAL_INDEX_PATH",
        "PDF_ASSET_DIR",
    ):
        path = Path(spec.env[key])
        if path.exists():
            raise ValueError(f"isolated benchmark path already exists: {path.name}")
    if spec.run_dir.exists():
        raise ValueError(f"isolated benchmark run directory already exists: {spec.run_dir.name}")
    if _file_sha256(spec.dataset) != spec.dataset_sha256:
        raise ValueError("dataset changed after run specification was built")
    if _file_sha256(_corpus_path(spec.dataset)) != spec.corpus_sha256:
        raise ValueError("corpus changed after run specification was built")


def _worktree_fingerprint() -> str:
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
        diff = subprocess.check_output(
            ["git", "diff", "--no-ext-diff", "--binary"], cwd=ROOT, stderr=subprocess.DEVNULL
        )
        return hashlib.sha256(head.encode("utf-8") + b"\0" + diff).hexdigest()[:20]
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _model_fingerprints() -> dict[str, Any]:
    try:
        from documents.embedding_registry import fingerprint
        from utils.env_utils import RERANKER_MODEL, resolve_embedding_settings

        settings = resolve_embedding_settings()
        return {
            "embedding": fingerprint(
                settings.model_source,
                settings.dimension,
                settings.sparse_enabled,
            ),
            "embedding_provider": settings.provider,
            "reranker": hashlib.sha256(RERANKER_MODEL.encode("utf-8")).hexdigest()[:12],
        }
    except Exception:
        return {"embedding": "unavailable", "reranker": "unavailable"}


def _content_snapshot_hash(texts: list[str]) -> str:
    normalized = [" ".join((text or "").split()) for text in texts]
    payload = json.dumps(sorted(normalized), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _expected_corpus_snapshot(dataset: Path) -> tuple[int, str] | None:
    corpus_path = _corpus_path(dataset)
    if not corpus_path.is_file():
        return None
    import yaml

    payload = yaml.safe_load(corpus_path.read_text(encoding="utf-8")) or {}
    chunks = payload.get("chunks") if isinstance(payload, dict) else None
    if not isinstance(chunks, list):
        raise RuntimeError("benchmark corpus must contain a chunks list")
    by_id = {
        str(chunk["id"]): chunk
        for chunk in chunks
        if isinstance(chunk, dict) and chunk.get("id") is not None
    }
    texts = [str(chunk.get("text", "")) for chunk in by_id.values()]
    return len(texts), _content_snapshot_hash(texts)


def _verify_corpus_snapshot(spec: RunSpec) -> dict[str, Any]:
    expected = _expected_corpus_snapshot(spec.dataset)
    if expected is None:
        return {"available": False, "row_count": None, "content_sha256": None}
    expected_count, expected_hash = expected
    from pymilvus import MilvusClient

    client = MilvusClient(uri=spec.env["MILVUS_DB_URI"])
    try:
        stats = client.get_collection_stats(spec.env["COLLECTION_NAME"])
        actual_count = int(stats.get("row_count", 0))
        if actual_count != expected_count:
            raise RuntimeError(
                f"isolated collection row count mismatch: {actual_count} != {expected_count}"
            )
        rows = client.query(
            collection_name=spec.env["COLLECTION_NAME"],
            filter="",
            output_fields=["text"],
            limit=max(1, expected_count),
        )
        actual_hash = _content_snapshot_hash(
            [str(row.get("text", "")) for row in rows if isinstance(row, dict)]
        )
        if actual_hash != expected_hash:
            raise RuntimeError("isolated collection content snapshot mismatch")
        return {
            "available": True,
            "row_count": actual_count,
            "content_sha256": actual_hash,
        }
    finally:
        client.close()


def run_spec(spec: RunSpec, *, active: StorePaths, top_k: int) -> dict[str, Any]:
    validate_run_spec(spec, active=active)
    spec.run_dir.mkdir(parents=True, exist_ok=False)
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_benchmark.py"),
        "--dataset",
        str(spec.dataset),
        "--top-k",
        str(top_k),
        "--repeats",
        str(spec.repeats),
        "--output-json",
        str(spec.output_json),
    ]
    environment = os.environ.copy()
    environment.update(spec.env)
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    spec.log_path.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"benchmark failed for {spec.dataset.stem}/{spec.variant}/{spec.order}; "
            f"see {spec.log_path}"
        )
    if not spec.output_json.is_file():
        raise RuntimeError("benchmark completed without a metrics artifact")
    if not Path(spec.env["MILVUS_DB_URI"]).is_file():
        raise RuntimeError("benchmark completed without its isolated Milvus store")
    if not Path(spec.env["EMBEDDING_REGISTRY_DB"]).is_file():
        raise RuntimeError("benchmark completed without its isolated embedding registry")
    if _file_sha256(spec.dataset) != spec.dataset_sha256:
        raise RuntimeError("dataset changed while benchmark was running")
    if _file_sha256(_corpus_path(spec.dataset)) != spec.corpus_sha256:
        raise RuntimeError("corpus changed while benchmark was running")
    metrics = json.loads(spec.output_json.read_text(encoding="utf-8"))
    corpus_snapshot = _verify_corpus_snapshot(spec)
    return {
        "dataset": spec.dataset.stem,
        "dataset_sha256": spec.dataset_sha256,
        "corpus_sha256": spec.corpus_sha256,
        "variant": spec.variant,
        "order": spec.order,
        "position": spec.position,
        "collection": spec.env["COLLECTION_NAME"],
        "cache_namespace": spec.env["RETRIEVAL_CACHE_NAMESPACE"],
        "feature_flags": {
            key: spec.env[key] for key in sorted(_FEATURE_ENV_KEYS) if key in spec.env
        },
        "corpus_snapshot": corpus_snapshot,
        "metrics": metrics,
    }


def order_independence_report(
    runs: list[dict[str, Any]],
    *,
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    groups: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for run in runs:
        groups.setdefault((run["dataset"], run["variant"]), {})[run["order"]] = run["metrics"]
    comparisons: dict[str, Any] = {}
    passed = True
    for (dataset, variant), by_order in sorted(groups.items()):
        key = f"{dataset}/{variant}"
        metrics_report: dict[str, Any] = {}
        if set(by_order) != {"AB", "BA"}:
            passed = False
            comparisons[key] = {"missing_order": sorted({"AB", "BA"} - set(by_order))}
            continue
        for metric in QUALITY_KEYS:
            left = by_order["AB"].get(metric)
            right = by_order["BA"].get(metric)
            if left is None or right is None:
                continue
            delta = abs(float(left) - float(right))
            metric_passed = delta <= tolerance
            passed = passed and metric_passed
            metrics_report[metric] = {
                "ab": left,
                "ba": right,
                "delta": delta,
                "passed": metric_passed,
            }
        comparisons[key] = metrics_report
    return {"passed": passed, "tolerance": tolerance, "comparisons": comparisons}


def _promotion_report(runs: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for run in runs:
        grouped.setdefault((run["dataset"], run["variant"]), []).append(run["metrics"])
    datasets = sorted({dataset for dataset, _variant in grouped})
    decisions: dict[str, Any] = {}
    passed = True
    for dataset in datasets:
        control = grouped.get((dataset, "control"), [])
        treatment = grouped.get((dataset, "treatment"), [])
        if not control or not treatment:
            passed = False
            decisions[dataset] = {"passed": False, "reason": "missing_variant"}
            continue
        control_metrics = control[0]
        treatment_metrics = treatment[0]
        losses = {
            key: float(control_metrics[key]) - float(treatment_metrics[key])
            for key in QUALITY_KEYS
            if control_metrics.get(key) is not None and treatment_metrics.get(key) is not None
        }
        control_p95 = control_metrics.get("warm_p95_ms")
        treatment_p95 = treatment_metrics.get("warm_p95_ms")
        p95_ratio = (
            float(treatment_p95) / float(control_p95)
            if control_p95 not in (None, 0) and treatment_p95 is not None
            else None
        )
        decision_passed = all(loss <= 0.02 for loss in losses.values()) and (
            p95_ratio is None or p95_ratio <= 1.25
        )
        passed = passed and decision_passed
        decisions[dataset] = {
            "passed": decision_passed,
            "quality_losses": losses,
            "warm_p95_ratio": p95_ratio,
        }
    return {"passed": passed, "datasets": decisions}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run control/treatment retrieval benchmarks in isolated AB/BA processes."
    )
    parser.add_argument("--dataset", action="append", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--treatment-env", action="append", default=[])
    args = parser.parse_args(argv)

    if args.repeats < 3:
        parser.error("paired benchmark requires at least three repeats")
    try:
        treatment_env = parse_feature_env(args.treatment_env)
        output_root = (
            Path(args.output_dir).resolve()
            if args.output_dir
            else Path(tempfile.mkdtemp(prefix="rag-paired-benchmark-"))
        )
        active = current_store_paths()
        specs = build_run_specs(
            [Path(value) for value in args.dataset],
            output_root=output_root,
            active=active,
            repeats=args.repeats,
            treatment_env=treatment_env,
        )
        runs = []
        for index, spec in enumerate(specs, 1):
            print(
                f"[{index}/{len(specs)}] {spec.dataset.stem} "
                f"{spec.order}{spec.position} {spec.variant}",
                flush=True,
            )
            runs.append(run_spec(spec, active=active, top_k=args.top_k))
        summary = {
            "schema_version": 1,
            "worktree_fingerprint": _worktree_fingerprint(),
            "model_fingerprints": _model_fingerprints(),
            "runs": runs,
            "order_independence": order_independence_report(runs),
            "promotion": _promotion_report(runs),
        }
        output_root.mkdir(parents=True, exist_ok=True)
        summary_path = output_root / "summary.json"
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(f"summary: {summary_path}")
        return 0 if summary["order_independence"]["passed"] else 1
    except Exception as exc:
        print(f"Paired benchmark failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
