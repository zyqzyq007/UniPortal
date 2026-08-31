#!/usr/bin/env python3
"""Run reproducible named retrieval baselines in isolated local-only processes."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QUALITY_KEYS = (
    "median_hit_rate",
    "median_context_precision",
    "median_context_recall",
    "median_mrr",
    "median_ndcg",
)

REFERENCE_METRIC_KEYS = (
    *QUALITY_KEYS,
    "first_query_ms",
    "warm_p50_ms",
    "warm_p95_ms",
    "throughput_qps",
    "index_build_ms",
    "store_bytes",
    "peak_rss_mb",
    "gpu_peak_mb",
    "gpu_reserved_peak_mb",
    "query_embedding_forwards",
    "subprocess_wall_ms",
    "public_ndcg_at_10",
    "public_rr_at_10",
    "public_recall_at_100",
)

_BOOL_KEYS = {
    "COLBERT_RERANK_ENABLED",
    "COLPALI_ENABLED",
    "CONTEXTUAL_INDEX_ENABLED",
    "GRAPH_PPR_ENABLED",
    "GRAPH_RAG_ENABLED",
    "MILVUS_SPARSE_INDEX",
    "QUERY_TRANSFORM_ENABLED",
    "RAPTOR_ENABLED",
    "RERANKER_ENABLED",
    "RETRIEVAL_CANDIDATE_FUNNEL_ENABLED",
    "RETRIEVAL_DENSE_ENABLED",
    "RETRIEVAL_MMR_ENABLED",
    "RETRIEVAL_SPARSE_ENABLED",
    "RETRIEVAL_TIME_DECAY_ENABLED",
    "RETRIEVAL_WORKFLOW_ENABLED",
}
_INT_KEYS = {
    "RETRIEVAL_CANDIDATE_K",
    "RETRIEVAL_FINAL_K",
    "RETRIEVAL_LEG_TOP_K",
    "RETRIEVAL_RERANK_K",
    "RETRIEVAL_SELECTION_K",
    "RRF_K",
}
_FLOAT_KEYS = {"DENSE_WEIGHT", "MMR_LAMBDA", "SPARSE_WEIGHT"}
_ALLOWED_VARIANT_KEYS = _BOOL_KEYS | _INT_KEYS | _FLOAT_KEYS
_FORCED_OFF = {
    "COLBERT_RERANK_ENABLED",
    "COLPALI_ENABLED",
    "GRAPH_PPR_ENABLED",
    "GRAPH_RAG_ENABLED",
    "QUERY_TRANSFORM_ENABLED",
    "RAPTOR_ENABLED",
}
_VARIANT_DEFAULTS = {
    "COLBERT_RERANK_ENABLED": "false",
    "COLPALI_ENABLED": "false",
    "CONTEXTUAL_INDEX_ENABLED": "false",
    "GRAPH_PPR_ENABLED": "false",
    "GRAPH_RAG_ENABLED": "false",
    "MILVUS_SPARSE_INDEX": "true",
    "QUERY_TRANSFORM_ENABLED": "false",
    "RAPTOR_ENABLED": "false",
    "RERANKER_ENABLED": "true",
    "RETRIEVAL_CANDIDATE_FUNNEL_ENABLED": "false",
    "RETRIEVAL_DENSE_ENABLED": "true",
    "RETRIEVAL_MMR_ENABLED": "true",
    "RETRIEVAL_SPARSE_ENABLED": "true",
    "RETRIEVAL_TIME_DECAY_ENABLED": "true",
    "RETRIEVAL_WORKFLOW_ENABLED": "false",
}
_SAFE_PARENT_KEYS = {
    "CUDA_VISIBLE_DEVICES",
    "HF_HOME",
    "HOME",
    "LANG",
    "LC_ALL",
    "LD_LIBRARY_PATH",
    "PATH",
    "TMPDIR",
    "TORCH_HOME",
    "UV_CACHE_DIR",
    "XDG_CACHE_HOME",
}
_LOCAL_MODEL_KEYS = {
    "BGE_M3_MAX_LENGTH",
    "BGE_M3_USE_FP16",
    "EMBEDDING_BATCH_SIZE",
    "EMBEDDING_DEVICE",
    "EMBEDDING_DIMENSION",
    "EMBEDDING_MODEL",
    "EMBEDDING_MODEL_PATH",
    "EMBEDDING_NORMALIZE",
    "RERANKER_DEVICE",
    "RERANKER_MODEL",
    "RERANKER_MODEL_PATH",
}
_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")


@dataclass(frozen=True)
class VariantConfig:
    name: str
    env: dict[str, str]


@dataclass(frozen=True)
class MatrixConfig:
    reference_variant: str
    variants: tuple[VariantConfig, ...]


@dataclass(frozen=True)
class PreflightResult:
    available: bool
    reason: str | None = None
    fingerprints: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkloadLimits:
    max_datasets: int = 12
    max_variants: int = 12
    max_repeats: int = 10
    max_corpus_docs: int = 100_000
    max_corpus_bytes: int = 512 * 1024 * 1024
    max_output_bytes: int = 2 * 1024 * 1024 * 1024
    min_free_disk_bytes: int = 5 * 1024 * 1024 * 1024
    max_runs: int = 1_728


@dataclass(frozen=True)
class WorkloadManifest:
    dataset_count: int
    variant_count: int
    order_count: int
    run_count: int
    query_count: int
    corpus_docs: int
    corpus_bytes: int
    estimated_output_bytes: int
    free_disk_bytes: int


@dataclass(frozen=True)
class ChildResult:
    returncode: int
    output: str
    timed_out: bool
    wall_ms: float


@dataclass(frozen=True)
class MatrixRunSpec:
    dataset: Path
    dataset_sha256: str
    corpus_sha256: str | None
    variant: VariantConfig
    order: str
    position: int
    repeats: int
    run_dir: Path
    output_json: Path
    log_path: Path
    env: dict[str, str]


def _bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _canonical_value(key: str, value: Any) -> str:
    text = str(value).strip()
    if key in _BOOL_KEYS:
        folded = text.lower()
        if folded not in {"true", "false"}:
            raise ValueError(f"{key} must be true or false")
        return folded
    if key in _INT_KEYS:
        try:
            parsed = int(text)
        except ValueError as exc:
            raise ValueError(f"{key} must be an integer") from exc
        upper = 1000 if key == "RRF_K" else 200
        if not 1 <= parsed <= upper:
            raise ValueError(f"{key} must be within [1, {upper}]")
        return str(parsed)
    if key in _FLOAT_KEYS:
        try:
            parsed = float(text)
        except ValueError as exc:
            raise ValueError(f"{key} must be numeric") from exc
        if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
            raise ValueError(f"{key} must be finite and within [0, 1]")
        return str(parsed)
    raise ValueError(f"{key!r} is not an allowed retrieval setting")


def _canonical_variant_env(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError("variant.env must be a mapping")
    env = dict(_VARIANT_DEFAULTS)
    for raw_key, raw_value in raw.items():
        key = str(raw_key).strip()
        if key not in _ALLOWED_VARIANT_KEYS:
            raise ValueError(f"{key!r} is not an allowed retrieval setting")
        env[key] = _canonical_value(key, raw_value)
    for key in _FORCED_OFF:
        if _bool(env[key]):
            raise ValueError(f"{key} is benchmarked only by the specialized frontier runner")
    if not _bool(env["RETRIEVAL_DENSE_ENABLED"]) and not _bool(env["RETRIEVAL_SPARSE_ENABLED"]):
        raise ValueError("a matrix variant must keep at least one primary retrieval channel")
    return env


def load_matrix_config(path: str | os.PathLike[str]) -> MatrixConfig:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("matrix schema_version must be 1")
    raw_variants = payload.get("variants")
    if not isinstance(raw_variants, list) or not raw_variants:
        raise ValueError("matrix variants must be a non-empty list")
    if len(raw_variants) > 12:
        raise ValueError("matrix supports at most 12 variants")
    variants: list[VariantConfig] = []
    names: set[str] = set()
    for raw in raw_variants:
        if not isinstance(raw, dict):
            raise ValueError("each matrix variant must be an object")
        name = str(raw.get("name", "")).strip()
        if not _NAME_RE.fullmatch(name):
            raise ValueError(f"invalid matrix variant name: {name!r}")
        if name in names:
            raise ValueError(f"duplicate matrix variant: {name}")
        names.add(name)
        variants.append(VariantConfig(name, _canonical_variant_env(raw.get("env", {}))))
    reference = str(payload.get("reference_variant", "")).strip()
    if reference not in names:
        raise ValueError("reference_variant must name one configured variant")
    return MatrixConfig(reference, tuple(variants))


def quick_schedule(names: list[str]) -> list[list[str]]:
    if not names:
        return []
    return [list(names), list(reversed(names))]


def balanced_schedule(names: list[str]) -> list[list[str]]:
    if not names:
        return []
    return [names[offset:] + names[:offset] for offset in range(len(names))]


def build_minimal_child_env(
    parent_env: dict[str, str],
    variant_env: dict[str, str],
    run_env: dict[str, str],
) -> dict[str, str]:
    child = {
        key: value
        for key, value in parent_env.items()
        if key in _SAFE_PARENT_KEYS or key in _LOCAL_MODEL_KEYS
    }
    child.update(
        {
            "DOMAIN_PROFILE": "general",
            "EMBEDDING_DIMENSION": "1024",
            "EMBEDDING_MODEL": "BAAI/bge-m3",
            "EMBEDDING_MODEL_PATH": str(ROOT / "models/local_models/bge-m3"),
            "EMBEDDING_PROVIDER": "local",
            "HF_DATASETS_OFFLINE": "1",
            "HF_HUB_OFFLINE": "1",
            "PYTHON_DOTENV_DISABLED": "1",
            "RERANKER_MODEL": "BAAI/bge-reranker-v2-m3",
            "RERANKER_MODEL_PATH": str(ROOT / "models/local_models/reranker/bge-reranker-v2-m3"),
            "RETRIEVAL_CACHE_ENABLED": "false",
            "TRANSFORMERS_OFFLINE": "1",
        }
    )
    for key in _LOCAL_MODEL_KEYS:
        if key in parent_env and parent_env[key]:
            child[key] = parent_env[key]
    child.update(_VARIANT_DEFAULTS)
    child.update({key: str(value) for key, value in variant_env.items()})
    child.update({key: str(value) for key, value in run_env.items()})
    for key in tuple(child):
        folded = key.upper()
        if "KEY" in folded or "TOKEN" in folded or "PROXY" in folded:
            child.pop(key, None)
    return child


def _resolved_model_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def _model_cache_ready(path: Path | None) -> bool:
    return bool(
        path
        and path.is_dir()
        and any(
            (path / marker).is_file()
            for marker in ("config.json", "modules.json", "model.safetensors")
        )
    )


def _hybrid_heads_ready(path: Path | None) -> bool:
    return bool(
        path
        and all(
            (path / filename).is_file() and (path / filename).stat().st_size > 0
            for filename in ("sparse_linear.pt", "colbert_linear.pt")
        )
    )


def _path_fingerprint(path: Path) -> str:
    rows = []
    for marker in (
        "config.json",
        "modules.json",
        "model.safetensors",
        "pytorch_model.bin",
        "sparse_linear.pt",
        "colbert_linear.pt",
    ):
        candidate = path / marker
        if candidate.is_file():
            rows.append(f"{marker}:{candidate.stat().st_size}")
    return hashlib.sha256("|".join(rows).encode("utf-8")).hexdigest()[:16]


def preflight_local_components(env: dict[str, str]) -> PreflightResult:
    dense = _bool(env.get("RETRIEVAL_DENSE_ENABLED", "true"))
    sparse_native = _bool(env.get("RETRIEVAL_SPARSE_ENABLED", "true")) and _bool(
        env.get("MILVUS_SPARSE_INDEX", "true")
    )
    mmr = _bool(env.get("RETRIEVAL_MMR_ENABLED", "true")) and dense
    reranker = _bool(env.get("RERANKER_ENABLED", "true"))
    needs_embedding = dense or sparse_native or mmr
    fingerprints: dict[str, str] = {}
    if needs_embedding:
        embedding_path = _resolved_model_path(env.get("EMBEDDING_MODEL_PATH"))
        if not _model_cache_ready(embedding_path):
            return PreflightResult(False, "embedding_checkpoint_missing")
        if (
            importlib.util.find_spec("torch") is None
            or importlib.util.find_spec("FlagEmbedding") is None
        ):
            return PreflightResult(False, "embedding_dependency_missing")
        fingerprints["embedding"] = _path_fingerprint(embedding_path)
        if sparse_native:
            if not _hybrid_heads_ready(embedding_path):
                return PreflightResult(False, "embedding_hybrid_heads_missing")
            fingerprints["embedding_hybrid_heads"] = _path_fingerprint(embedding_path)
    if reranker:
        reranker_path = _resolved_model_path(env.get("RERANKER_MODEL_PATH"))
        if not _model_cache_ready(reranker_path):
            return PreflightResult(False, "reranker_checkpoint_missing")
        fingerprints["reranker"] = _path_fingerprint(reranker_path)
    return PreflightResult(True, fingerprints=fingerprints)


def _corpus_path(dataset: Path) -> Path:
    return dataset.with_name(dataset.stem + "_corpus.yaml")


def _dataset_identity(dataset: Path) -> str:
    manifest_path = dataset.with_name("manifest.json")
    if manifest_path.is_file():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            dataset_id = payload.get("dataset_id") if isinstance(payload, dict) else None
            if isinstance(dataset_id, str) and dataset_id.strip():
                return dataset_id.strip()
        except (OSError, ValueError):
            pass
    return dataset.stem


def _yaml_list_count(path: Path, key: str) -> int:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"{path.name} must contain a {key} list")
    return len(rows)


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


def _expected_corpus_snapshot(dataset: Path) -> dict[str, Any]:
    payload = yaml.safe_load(_corpus_path(dataset).read_text(encoding="utf-8")) or {}
    chunks = payload.get("chunks") if isinstance(payload, dict) else None
    if not isinstance(chunks, list):
        raise RuntimeError("benchmark corpus must contain a chunks list")
    by_id = {
        str(chunk["id"]): str(chunk.get("text", ""))
        for chunk in chunks
        if isinstance(chunk, dict) and chunk.get("id") is not None
    }
    return _snapshot_rows(list(by_id.items()))


def _required_active_stores(env: dict[str, str]) -> tuple[str, ...]:
    stores: list[str] = []
    if _needs_milvus(env):
        stores.append("milvus")
    if _bool(env.get("RETRIEVAL_SPARSE_ENABLED", "true")) and not _bool(
        env.get("MILVUS_SPARSE_INDEX", "true")
    ):
        stores.append("bm25")
    return tuple(stores)


def _verify_active_store_snapshot(spec: MatrixRunSpec, metrics: dict[str, Any]) -> None:
    expected = _expected_corpus_snapshot(spec.dataset)
    snapshot = metrics.get("active_store_snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("expected") != expected:
        raise RuntimeError("benchmark child corpus snapshot mismatch")
    stores = snapshot.get("stores")
    if not isinstance(stores, dict):
        raise RuntimeError("benchmark child omitted active store snapshots")
    for store in _required_active_stores(spec.variant.env):
        observed = stores.get(store)
        compared_keys = (
            ("row_count", "doc_ids_sha256")
            if store == "milvus"
            else ("row_count", "doc_ids_sha256", "content_sha256")
        )
        if not isinstance(observed, dict) or any(
            observed.get(key) != expected.get(key) for key in compared_keys
        ):
            raise RuntimeError(f"active {store} store snapshot mismatch")
    active_stages = metrics.get("active_index_stages")
    expected_stages: list[str] = []
    if _bool(spec.variant.env.get("RETRIEVAL_DENSE_ENABLED", "true")):
        expected_stages.append("milvus_dense")
    if _bool(spec.variant.env.get("RETRIEVAL_SPARSE_ENABLED", "true")):
        expected_stages.append(
            "milvus_native_sparse"
            if _bool(spec.variant.env.get("MILVUS_SPARSE_INDEX", "true"))
            else "bm25"
        )
    if active_stages != expected_stages:
        raise RuntimeError("benchmark child active index stages mismatch")
    milvus_path = Path(spec.env["MILVUS_DB_URI"])
    if _needs_milvus(spec.variant.env):
        if not milvus_path.is_file():
            raise RuntimeError("active policy required Milvus but no isolated store was written")
    elif milvus_path.exists():
        raise RuntimeError("inactive Milvus store was written")


def inspect_workload(
    datasets: list[Path],
    *,
    variant_count: int,
    order_count: int,
    repeats: int,
    output_root: Path,
    limits: WorkloadLimits | None = None,
) -> WorkloadManifest:
    limits = limits or WorkloadLimits()
    if not 1 <= len(datasets) <= limits.max_datasets:
        raise ValueError("dataset count exceeds workload limit")
    if not 1 <= variant_count <= limits.max_variants:
        raise ValueError("variant count exceeds workload limit")
    if not 3 <= repeats <= limits.max_repeats:
        raise ValueError("repeats exceeds workload limit")
    query_count = 0
    corpus_docs = 0
    corpus_bytes = 0
    for dataset in datasets:
        dataset = dataset.resolve()
        corpus = _corpus_path(dataset)
        if not dataset.is_file() or not corpus.is_file():
            raise ValueError(f"dataset bundle is incomplete: {dataset.name}")
        query_count += _yaml_list_count(dataset, "cases")
        corpus_docs += _yaml_list_count(corpus, "chunks")
        corpus_bytes += corpus.stat().st_size
    if corpus_docs > limits.max_corpus_docs:
        raise ValueError("corpus docs exceed workload limit")
    if corpus_bytes > limits.max_corpus_bytes:
        raise ValueError("corpus bytes exceed workload limit")
    run_count = len(datasets) * variant_count * order_count
    if run_count > limits.max_runs:
        raise ValueError("run count exceeds workload limit")
    estimated_output = max(corpus_bytes * run_count * 4, 1024 * run_count)
    if estimated_output > limits.max_output_bytes:
        raise ValueError("estimated output bytes exceed workload limit")
    output_root.mkdir(parents=True, exist_ok=True)
    free_disk = shutil.disk_usage(output_root).free
    if free_disk < limits.min_free_disk_bytes:
        raise ValueError("free disk is below workload limit")
    return WorkloadManifest(
        dataset_count=len(datasets),
        variant_count=variant_count,
        order_count=order_count,
        run_count=run_count,
        query_count=query_count,
        corpus_docs=corpus_docs,
        corpus_bytes=corpus_bytes,
        estimated_output_bytes=estimated_output,
        free_disk_bytes=free_disk,
    )


def fsync_directory(path: str | os.PathLike[str]) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(os.fspath(path), flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_json(path: str | os.PathLike[str], payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        fsync_directory(target.parent)
    finally:
        temporary.unlink(missing_ok=True)


def terminate_process_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return


def run_subprocess(
    command: list[str],
    *,
    env: dict[str, str],
    cwd: Path,
    timeout_seconds: float,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    terminate_group: Callable[[int], None] = terminate_process_group,
) -> ChildResult:
    started = time.perf_counter()
    process = popen_factory(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        shell=False,
        start_new_session=True,
    )
    timed_out = False
    try:
        output, _ = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        terminate_group(process.pid)
        try:
            output, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            output, _ = process.communicate()
    except BaseException:
        terminate_group(process.pid)
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
        raise
    return ChildResult(
        returncode=int(process.returncode if process.returncode is not None else -1),
        output=output or "",
        timed_out=timed_out,
        wall_ms=(time.perf_counter() - started) * 1000,
    )


def _dominates(left: dict[str, Any], right: dict[str, Any], cost_key: str) -> bool:
    return bool(
        left["quality"] >= right["quality"]
        and left[cost_key] <= right[cost_key]
        and (left["quality"] > right["quality"] or left[cost_key] < right[cost_key])
    )


def pareto_variants(rows: list[dict[str, Any]]) -> dict[str, Any]:
    excluded: dict[str, list[str]] = {}
    for row in rows:
        missing = [
            key
            for key in ("store_bytes", "warm_p95_ms")
            if not isinstance(row.get(key), (int, float))
        ]
        if missing:
            excluded[str(row["variant"])] = sorted(missing)

    def frontier(cost_key: str) -> list[str]:
        eligible = [
            row
            for row in rows
            if isinstance(row.get("quality"), (int, float))
            and isinstance(row.get(cost_key), (int, float))
        ]
        return sorted(
            str(row["variant"])
            for row in eligible
            if not any(_dominates(other, row, cost_key) for other in eligible if other is not row)
        )

    return {
        "quality_latency": frontier("warm_p95_ms"),
        "quality_resource": frontier("store_bytes"),
        "excluded": excluded,
    }


def pareto_by_dataset(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["dataset"]), []).append(row)
    return {dataset: pareto_variants(values) for dataset, values in sorted(grouped.items())}


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _worktree_fingerprint() -> str:
    digest = hashlib.sha256()
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT)
        diff = subprocess.check_output(["git", "diff", "--binary"], cwd=ROOT)
        status = subprocess.check_output(["git", "status", "--porcelain", "-z"], cwd=ROOT)
        digest.update(head)
        digest.update(diff)
        digest.update(status)
        for entry in status.split(b"\0"):
            if not entry.startswith(b"?? "):
                continue
            path = ROOT / entry[3:].decode("utf-8", errors="surrogateescape")
            if path.is_file():
                digest.update(entry)
                digest.update(path.read_bytes())
        lock = ROOT / "uv.lock"
        if lock.is_file():
            digest.update(lock.read_bytes())
        return digest.hexdigest()[:20]
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _verify_worktree_fingerprint(expected: str, observed: str) -> None:
    if expected == "unavailable" or observed == "unavailable" or observed != expected:
        raise RuntimeError("worktree changed or became unverifiable during benchmark")


def _safe_stem(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value)[:32]


def build_run_specs(
    datasets: list[Path],
    matrix: MatrixConfig,
    *,
    schedules: list[list[str]],
    output_root: Path,
    repeats: int,
) -> list[MatrixRunSpec]:
    variants = {variant.name: variant for variant in matrix.variants}
    specs: list[MatrixRunSpec] = []
    for dataset in datasets:
        dataset = dataset.resolve()
        dataset_hash = _file_sha256(dataset)
        if dataset_hash is None:
            raise ValueError(f"dataset does not exist: {dataset}")
        corpus_hash = _file_sha256(_corpus_path(dataset))
        stem = _safe_stem(_dataset_identity(dataset))
        for order_index, order in enumerate(schedules):
            order_name = f"order-{order_index + 1:02d}"
            for position, variant_name in enumerate(order, 1):
                variant = variants[variant_name]
                raw_id = json.dumps(
                    [dataset_hash, variant.name, variant.env, order_name, position],
                    sort_keys=True,
                )
                suffix = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:12]
                run_dir = output_root / f"{stem}_{variant.name}_{order_index + 1}_{suffix}"
                run_env = {
                    "COLLECTION_NAME": f"rbm_{stem}_{variant.name}_{suffix}"[:60],
                    "EMBEDDING_REGISTRY_DB": str(run_dir / "embedding_registry.db"),
                    "GRAPH_STORE_BACKUP_PATH": str(run_dir / "graph_store_backup.db"),
                    "GRAPH_STORE_DB_PATH": str(run_dir / "graph_store.db"),
                    "MILVUS_DB_URI": str(run_dir / "milvus.db"),
                    "PDF_ASSET_DIR": str(run_dir / "pdf_assets"),
                    "RAPTOR_DB_PATH": str(run_dir / "raptor.db"),
                    "RETRIEVAL_CACHE_NAMESPACE": f"rbm-{suffix}",
                    "VISUAL_INDEX_PATH": str(run_dir / "visual_index.db"),
                }
                specs.append(
                    MatrixRunSpec(
                        dataset=dataset,
                        dataset_sha256=dataset_hash,
                        corpus_sha256=corpus_hash,
                        variant=variant,
                        order=order_name,
                        position=position,
                        repeats=repeats,
                        run_dir=run_dir,
                        output_json=run_dir / "metrics.json",
                        log_path=run_dir / "benchmark.log",
                        env=run_env,
                    )
                )
    return specs


def _needs_milvus(env: dict[str, str]) -> bool:
    return _bool(env.get("RETRIEVAL_DENSE_ENABLED", "true")) or (
        _bool(env.get("RETRIEVAL_SPARSE_ENABLED", "true"))
        and _bool(env.get("MILVUS_SPARSE_INDEX", "true"))
    )


def _protocol_request(
    variant_env: dict[str, str],
    *,
    top_k: int,
    protocol: str,
) -> tuple[dict[str, str], int]:
    requested = dict(variant_env)
    if protocol == "public_quality":
        requested.update(
            {
                "RETRIEVAL_LEG_TOP_K": "200",
                "RETRIEVAL_CANDIDATE_K": "200",
                "RETRIEVAL_RERANK_K": "200",
                "RETRIEVAL_SELECTION_K": "100",
                "RETRIEVAL_FINAL_K": "100",
            }
        )
        top_k = max(100, top_k)
    return requested, top_k


def _attach_public_ir_metrics(spec: MatrixRunSpec, metrics: dict[str, Any]) -> None:
    qrels_path = spec.dataset.with_name("qrels.json")
    manifest_path = spec.dataset.with_name("manifest.json")
    if not qrels_path.is_file() or not manifest_path.is_file():
        raise RuntimeError("public_quality dataset bundle omitted qrels or manifest")
    from scripts.public_ir_metrics import evaluate_public_ir

    qrels = json.loads(qrels_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metrics["public_ir_metrics"] = evaluate_public_ir(
        qrels,
        metrics.get("ranked_run", []),
        manifest,
        metrics,
    )


def run_spec(
    spec: MatrixRunSpec,
    *,
    parent_env: dict[str, str],
    top_k: int,
    protocol: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    if spec.run_dir.exists():
        raise ValueError(f"isolated run path already exists: {spec.run_dir.name}")
    spec.run_dir.mkdir(parents=True, exist_ok=False)
    requested_env, top_k = _protocol_request(spec.variant.env, top_k=top_k, protocol=protocol)
    child_env = build_minimal_child_env(parent_env, requested_env, spec.env)
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_benchmark.py"),
        "--dataset",
        str(spec.dataset),
        "--top-k",
        str(top_k),
        "--repeats",
        str(spec.repeats),
        "--benchmark-protocol",
        protocol,
        "--output-json",
        str(spec.output_json),
    ]
    child = run_subprocess(
        command,
        env=child_env,
        cwd=ROOT,
        timeout_seconds=timeout_seconds,
    )
    spec.log_path.write_text(child.output, encoding="utf-8")
    if child.timed_out:
        raise TimeoutError(f"run timed out after {timeout_seconds}s")
    if child.returncode != 0:
        raise RuntimeError(f"benchmark child failed with exit {child.returncode}")
    if not spec.output_json.is_file():
        raise RuntimeError("benchmark child did not write metrics")
    metrics = json.loads(spec.output_json.read_text(encoding="utf-8"))
    effective = metrics.get("effective_retrieval_config")
    if not isinstance(effective, dict):
        raise RuntimeError("benchmark child omitted effective retrieval config")
    for key, requested in requested_env.items():
        if str(effective.get(key, "")).lower() != str(requested).lower():
            raise RuntimeError(f"effective config mismatch for {key}")
    _verify_active_store_snapshot(spec, metrics)
    if protocol == "public_quality":
        _attach_public_ir_metrics(spec, metrics)
    metrics["subprocess_wall_ms"] = child.wall_ms
    return {
        "dataset": _dataset_identity(spec.dataset),
        "dataset_sha256": spec.dataset_sha256,
        "corpus_sha256": spec.corpus_sha256,
        "variant": spec.variant.name,
        "order": spec.order,
        "position": spec.position,
        "requested_config": requested_env,
        "effective_config": effective,
        "status": "success",
        "metrics": metrics,
    }


def _order_report(runs: list[dict[str, Any]], tolerance: float = 1e-9) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for run in runs:
        if run.get("status") == "success":
            grouped.setdefault((run["dataset"], run["variant"]), []).append(run)
    comparisons = {}
    passed = True
    for (dataset, variant), values in sorted(grouped.items()):
        metrics = {}
        for key in QUALITY_KEYS:
            observed = [float(run["metrics"][key]) for run in values if key in run["metrics"]]
            if not observed:
                continue
            delta = max(observed) - min(observed)
            metrics[key] = {"min": min(observed), "max": max(observed), "delta": delta}
            passed = passed and delta <= tolerance
        comparisons[f"{dataset}/{variant}"] = metrics
    return {"passed": passed, "tolerance": tolerance, "comparisons": comparisons}


def _position_report(
    runs: list[dict[str, Any]],
    *,
    warning_ratio: float = 0.25,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        if run.get("status") != "success":
            continue
        key = f"{run['dataset']}/{run['variant']}"
        grouped.setdefault(key, []).append(
            {
                "position": run["position"],
                "warm_p95_ms": run["metrics"].get("warm_p95_ms"),
            }
        )
    comparisons: dict[str, Any] = {}
    any_warning = False
    for key, observations in sorted(grouped.items()):
        ordered = sorted(observations, key=lambda row: int(row["position"]))
        available = [
            row
            for row in ordered
            if isinstance(row.get("warm_p95_ms"), (int, float))
            and not isinstance(row.get("warm_p95_ms"), bool)
        ]
        values = [float(row["warm_p95_ms"]) for row in available]
        median = statistics.median(values) if values else None
        minimum = min(values) if values else None
        maximum = max(values) if values else None
        delta = maximum - minimum if minimum is not None and maximum is not None else None
        relative = delta / median if delta is not None and median not in (None, 0.0) else None
        warning = bool(relative is not None and relative > warning_ratio)
        any_warning = any_warning or warning
        comparisons[key] = {
            "positions": [int(row["position"]) for row in ordered],
            "available_positions": [int(row["position"]) for row in available],
            "min_ms": minimum,
            "max_ms": maximum,
            "median_ms": median,
            "delta_ms": delta,
            "relative_delta": relative,
            "warning": warning,
            "observations": ordered,
        }
    return {
        "warning": any_warning,
        "warning_ratio": warning_ratio,
        "comparisons": comparisons,
    }


def _reference_delta_report(rows: list[dict[str, Any]], reference_variant: str) -> dict[str, Any]:
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["dataset"]), {})[str(row["variant"])] = row
    datasets: dict[str, Any] = {}
    for dataset, variants in sorted(grouped.items()):
        reference = variants.get(reference_variant)
        variant_report: dict[str, Any] = {}
        for variant, row in sorted(variants.items()):
            metrics: dict[str, Any] = {}
            for key in REFERENCE_METRIC_KEYS:
                value = row.get(key)
                reference_value = reference.get(key) if reference is not None else None
                numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
                reference_numeric = isinstance(reference_value, (int, float)) and not isinstance(
                    reference_value, bool
                )
                delta = (
                    float(value) - float(reference_value) if numeric and reference_numeric else None
                )
                relative = (
                    delta / float(reference_value)
                    if delta is not None and float(reference_value) != 0.0
                    else None
                )
                metrics[key] = {
                    "value": value if numeric else None,
                    "reference": reference_value if reference_numeric else None,
                    "delta": delta,
                    "relative_delta": relative,
                }
            variant_report[variant] = metrics
        datasets[dataset] = {
            "reference_available": reference is not None,
            "variants": variant_report,
        }
    return {"reference_variant": reference_variant, "datasets": datasets}


def _aggregate_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for run in runs:
        if run.get("status") == "success":
            grouped.setdefault((run["dataset"], run["variant"]), []).append(run["metrics"])
    rows = []
    for (dataset, variant), metrics_list in sorted(grouped.items()):
        row: dict[str, Any] = {"dataset": dataset, "variant": variant}
        for key in REFERENCE_METRIC_KEYS:
            if key.startswith("public_"):
                continue
            observed = [
                float(metrics[key])
                for metrics in metrics_list
                if isinstance(metrics.get(key), (int, float))
                and not isinstance(metrics.get(key), bool)
            ]
            row[key] = statistics.median(observed) if observed else None
        public_metric_keys = {
            "public_ndcg_at_10": "nDCG@10",
            "public_rr_at_10": "RR@10",
            "public_recall_at_100": "Recall@100",
        }
        for output_key, metric_name in public_metric_keys.items():
            observed = []
            for metrics in metrics_list:
                report = metrics.get("public_ir_metrics")
                values = report.get("metrics") if isinstance(report, dict) else None
                value = values.get(metric_name) if isinstance(values, dict) else None
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    observed.append(float(value))
            row[output_key] = statistics.median(observed) if observed else None
        row["quality"] = (
            row["public_ndcg_at_10"] if row["public_ndcg_at_10"] is not None else row["median_ndcg"]
        )
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", required=True)
    parser.add_argument("--dataset", action="append", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument("--schedule", choices=("quick", "balanced"), default="balanced")
    parser.add_argument(
        "--protocol",
        choices=("production_performance", "public_quality"),
        default="production_performance",
    )
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--run-timeout", type=float, default=1800.0)
    parser.add_argument("--total-timeout", type=float, default=21600.0)
    parser.add_argument("--max-corpus-docs", type=int, default=100_000)
    parser.add_argument("--max-corpus-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--max-output-bytes", type=int, default=2 * 1024 * 1024 * 1024)
    parser.add_argument("--min-free-disk-gb", type=float, default=5.0)
    args = parser.parse_args(argv)

    output_root = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else Path(tempfile.mkdtemp(prefix="rag-benchmark-matrix-"))
    )
    try:
        matrix = load_matrix_config(args.matrix)
        names = [variant.name for variant in matrix.variants]
        schedules = quick_schedule(names) if args.schedule == "quick" else balanced_schedule(names)
        limits = WorkloadLimits(
            max_corpus_docs=args.max_corpus_docs,
            max_corpus_bytes=args.max_corpus_bytes,
            max_output_bytes=args.max_output_bytes,
            min_free_disk_bytes=int(args.min_free_disk_gb * 1024**3),
        )
        datasets = [Path(value) for value in args.dataset]
        workload = inspect_workload(
            datasets,
            variant_count=len(matrix.variants),
            order_count=len(schedules),
            repeats=args.repeats,
            output_root=output_root,
            limits=limits,
        )
        specs = build_run_specs(
            datasets,
            matrix,
            schedules=schedules,
            output_root=output_root,
            repeats=args.repeats,
        )
        preflight = {}
        for variant in matrix.variants:
            child_env = build_minimal_child_env(os.environ, variant.env, {})
            result = preflight_local_components(child_env)
            preflight[variant.name] = {
                "available": result.available,
                "reason": result.reason,
                "fingerprints": result.fingerprints,
            }
        unavailable = [name for name, value in preflight.items() if not value["available"]]
        worktree_fingerprint = _worktree_fingerprint()
        summary: dict[str, Any] = {
            "schema_version": 1,
            "status": "running",
            "schedule": args.schedule,
            "protocol": args.protocol,
            "reference_variant": matrix.reference_variant,
            "worktree_fingerprint": worktree_fingerprint,
            "workload": workload.__dict__,
            "preflight": preflight,
            "runs": [],
        }
        summary_path = output_root / "summary.json"
        atomic_write_json(summary_path, summary)
        if unavailable:
            summary["status"] = "unavailable"
            summary["unavailable_variants"] = unavailable
            atomic_write_json(summary_path, summary)
            return 2

        started = time.monotonic()
        for index, spec in enumerate(specs, 1):
            print(
                f"[{index}/{len(specs)}] {_dataset_identity(spec.dataset)} "
                f"{spec.order} pos={spec.position} {spec.variant.name}",
                flush=True,
            )
            if time.monotonic() - started >= args.total_timeout:
                summary["runs"].append(
                    {
                        "dataset": _dataset_identity(spec.dataset),
                        "variant": spec.variant.name,
                        "order": spec.order,
                        "position": spec.position,
                        "status": "failed",
                        "error": "total_timeout",
                    }
                )
                atomic_write_json(summary_path, summary)
                break
            try:
                _verify_worktree_fingerprint(worktree_fingerprint, _worktree_fingerprint())
                run = run_spec(
                    spec,
                    parent_env=dict(os.environ),
                    top_k=args.top_k,
                    protocol=args.protocol,
                    timeout_seconds=args.run_timeout,
                )
                _verify_worktree_fingerprint(worktree_fingerprint, _worktree_fingerprint())
            except Exception as exc:
                run = {
                    "dataset": _dataset_identity(spec.dataset),
                    "variant": spec.variant.name,
                    "order": spec.order,
                    "position": spec.position,
                    "status": "failed",
                    "error": type(exc).__name__,
                    "message": str(exc),
                }
            summary["runs"].append(run)
            atomic_write_json(summary_path, summary)
            if run.get("error") == "RuntimeError" and "worktree changed" in run.get("message", ""):
                break

        summary["order_independence"] = _order_report(summary["runs"])
        summary["position_effects"] = _position_report(summary["runs"])
        aggregate = _aggregate_rows(summary["runs"])
        summary["aggregate"] = aggregate
        summary["reference_deltas"] = _reference_delta_report(aggregate, matrix.reference_variant)
        summary["pareto"] = (
            {"available": True, "datasets": pareto_by_dataset(aggregate)}
            if args.schedule == "balanced"
            else {
                "available": False,
                "reason": "balanced_schedule_required",
                "datasets": {},
            }
        )
        failed = [run for run in summary["runs"] if run.get("status") != "success"]
        summary["status"] = (
            "failed" if failed or not summary["order_independence"]["passed"] else "complete"
        )
        summary["promotion_eligible"] = bool(
            summary["status"] == "complete"
            and args.schedule == "balanced"
            and args.protocol == "production_performance"
            and not summary["position_effects"]["warning"]
            and not subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=ROOT, text=True
            ).strip()
        )
        atomic_write_json(summary_path, summary)
        print(f"summary: {summary_path}")
        return 0 if summary["status"] == "complete" else 1
    except Exception as exc:
        print(f"Benchmark matrix failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
