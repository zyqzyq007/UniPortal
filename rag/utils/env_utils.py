"""Application configuration loaded from environment variables."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Explicit process/container environment variables take precedence over `.env`.
load_dotenv(override=False)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value not in (None, "") else default


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value not in (None, "") else default


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_path(name: str, default: str) -> str:
    value = os.getenv(name, default)
    if not value:
        return ""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path.resolve())


def _detect_device() -> str:
    """Resolve 'auto' to a concrete torch device. cuda only when the installed
    wheel actually ships a kernel for this GPU's compute capability — else a
    cu126 wheel on sm_120 (RTX 50-series) silently fails with
    cudaErrorNoKernelImageForDevice. Mirrors
    tests/e2e/test_e2e_coverage.py:_gpu_kernel_supported so probe + skip agree.
    Any failure degrades silently to cpu (never raises).
    """
    try:
        import torch

        if torch.cuda.is_available():
            cap = torch.cuda.get_device_capability(0)
            if f"sm_{cap[0]}{cap[1]}" in torch.cuda.get_arch_list():
                return "cuda"
    except Exception:  # noqa: BLE001 — probe MUST degrade silently
        pass
    return "cpu"


def _resolve_device(name: str, default: str) -> str:
    """Read a device env var; resolve 'auto' to cuda/cpu. The exported value is
    always a concrete device (cuda/cpu), never the literal 'auto', so downstream
    device= consumers (HuggingFaceEmbeddings, CrossEncoder) need no changes."""
    value = os.getenv(name, default)
    if value.strip().lower() == "auto":
        return _detect_device()
    return value


# LLM: any OpenAI-compatible endpoint.
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "ollama")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3:14b")
LLM_TEMPERATURE = _get_float("LLM_TEMPERATURE", 0.0)
LLM_MAX_TOKENS = _get_int("LLM_MAX_TOKENS", 4096)
LLM_TIMEOUT = _get_float("LLM_TIMEOUT", 60.0)
LLM_MAX_RETRIES = _get_int("LLM_MAX_RETRIES", 1)


@dataclass(frozen=True)
class EmbeddingSettings:
    provider: str
    model: str
    model_path: str
    model_source: str
    dimension: int
    sparse_enabled: bool
    is_bge_m3: bool


def _is_bge_m3_model(value: str) -> bool:
    normalized = str(value or "").strip().lower().rstrip("/")
    return normalized == "baai/bge-m3" or normalized.rsplit("/", 1)[-1] in {
        "bge-m3",
        "bge_m3",
    }


def _is_model_cache(path: str) -> bool:
    if not path:
        return False
    candidate = Path(path)
    return candidate.is_dir() and any(
        (candidate / marker).is_file()
        for marker in ("modules.json", "config.json", "model.safetensors")
    )


def resolve_embedding_settings(provider: str | None = None) -> EmbeddingSettings:
    effective_provider = (provider or os.getenv("EMBEDDING_PROVIDER", "auto")).strip().lower()
    if effective_provider == "auto":
        try:
            import langchain_huggingface  # noqa: F401
            import torch  # noqa: F401

            effective_provider = "local"
        except ImportError:
            effective_provider = "api"
    if effective_provider not in {"local", "api"}:
        raise ValueError(
            f"EMBEDDING_PROVIDER must be one of auto|local|api, got {effective_provider!r}"
        )
    local = effective_provider == "local"
    model = (os.getenv("EMBEDDING_MODEL") or "").strip() or (
        "BAAI/bge-m3" if local else "text-embedding-v3"
    )
    is_bge_m3 = local and _is_bge_m3_model(model)

    raw_dimension = os.getenv("EMBEDDING_DIMENSION")
    if raw_dimension not in (None, ""):
        dimension = int(raw_dimension)
    elif is_bge_m3:
        dimension = 1024
    elif local:
        raise ValueError("EMBEDDING_DIMENSION is required for a non-default local embedding model")
    else:
        dimension = 512
    if dimension <= 0:
        raise ValueError("EMBEDDING_DIMENSION must be a positive integer")

    default_path = "models/local_models/bge-m3" if is_bge_m3 else ""
    model_path = _get_path("EMBEDDING_MODEL_PATH", default_path) if local else ""
    default_m3_path = str((PROJECT_ROOT / "models/local_models/bge-m3").resolve())
    if local and not is_bge_m3 and model_path == default_m3_path:
        raise ValueError("A non-BGE-M3 model cannot reuse the default BGE-M3 EMBEDDING_MODEL_PATH")
    model_source = model_path if local and _is_model_cache(model_path) else model

    sparse_enabled = _get_bool("MILVUS_SPARSE_INDEX", is_bge_m3)
    if sparse_enabled and not is_bge_m3:
        raise ValueError(
            "native sparse (MILVUS_SPARSE_INDEX=true) is supported only by local BGE-M3"
        )
    return EmbeddingSettings(
        provider=effective_provider,
        model=model,
        model_path=model_path,
        model_source=model_source,
        dimension=dimension,
        sparse_enabled=sparse_enabled,
        is_bge_m3=is_bge_m3,
    )


_EMBEDDING_SETTINGS = resolve_embedding_settings()
EMBEDDING_MODEL = _EMBEDDING_SETTINGS.model
EMBEDDING_MODEL_PATH = _EMBEDDING_SETTINGS.model_path
EMBEDDING_DIMENSION = _EMBEDDING_SETTINGS.dimension
EMBEDDING_DEVICE = _resolve_device("EMBEDDING_DEVICE", "auto")
EMBEDDING_NORMALIZE = _get_bool("EMBEDDING_NORMALIZE", True)
EMBEDDING_BATCH_SIZE = _get_int("EMBEDDING_BATCH_SIZE", 8)

# BGE-M3 specific (docs/specs/retrieval-backend-modernization). When the
# configured EMBEDDING_MODEL is BGE-M3, these tune its loading. F-04: BGEM3Embeddings
# holds a single AutoModel (not BGEM3FlagModel), reused by encode_hybrid (dense +
# sparse) and encode_late_chunked (last_hidden_state). F-06: FlashAttention2 cuts
# the 8K-token attention peak from ~4.3GB to ~tens of MB; when unavailable,
# max_length auto-lowers to 2048 and late chunking throughput drops.
BGE_M3_USE_FP16 = _get_bool("BGE_M3_USE_FP16", True)
BGE_M3_MAX_LENGTH = _get_int("BGE_M3_MAX_LENGTH", 8192)
BGE_M3_DEVICE = _resolve_device("BGE_M3_DEVICE", "auto")
BGE_M3_FLASH_ATTENTION = _get_bool("BGE_M3_FLASH_ATTENTION", True)

# Milvus native sparse vector (docs/specs/retrieval-backend-modernization, F-02).
# When true, the collection gains a SPARSE_FLOAT_VECTOR field indexed with
# SPARSE_INVERTED_INDEX, and HybridRetriever's sparse leg uses Milvus sparse_search
# (BGE-M3 lexical_weights) instead of the self-implemented in-memory BM25. F-01:
# filter goes through search(filter=), a first-class param — NOT hybrid_search's
# top-level filter which pymilvus 2.5.18 silently drops. False reverts to BM25.
MILVUS_SPARSE_INDEX = _EMBEDDING_SETTINGS.sparse_enabled

# Late chunking (docs/specs/retrieval-backend-modernization §3.5). Embed the full
# parent section (≤8192 tokens) to get token-level last_hidden_state, then
# mean-pool per chunk span — each chunk embedding carries global section context.
# F-05: only dense is late-chunked; sparse is per-chunk encoded (lexical BoW
# needs per-doc term frequency). F-06: ingest-time forward is serialised by a
# semaphore to avoid stacking multiple 8K forwards. F-08: span reconstruction
# uses sequential cursor search with per-chunk fallback.
LATE_CHUNKING_ENABLED = _get_bool("LATE_CHUNKING_ENABLED", True)
LATE_CHUNKING_MIN_TOKENS = _get_int("LATE_CHUNKING_MIN_TOKENS", 256)
INGEST_EMBEDDING_CONCURRENCY = _get_int("INGEST_EMBEDDING_CONCURRENCY", 1)

# Embedding provider selection (api-only-deploy). ``auto`` resolves to ``local``
# when torch + langchain_huggingface are importable, otherwise ``api`` — this
# makes the airgapped API-only image (torch absent) pick DashScope automatically.
# Note (design §2.3, F-06): ``_detect_device`` short-circuiting on ``api`` is NOT
# how REQ-AO-001 closes; the real closure is the dep restructure (local-models
# extra) + lazy import. Existing ``try: import torch except: cpu`` already degrades
# safely, so EMBEDDING_DEVICE/RERANKER_DEVICE resolve to "cpu" in torch-less images.
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "auto").strip().lower()
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com").rstrip("/")

# Optional cross-encoder reranker. Default on (REQ-RD-001): a Chinese-capable
# cross-encoder is part of the shipped retrieval stack, not an opt-in extra.
# The default model is the local bge-reranker-v2-m3 directory so air-gapped
# deploys load from disk instead of hitting Hugging Face (REQ-RD-002/003).
RERANKER_ENABLED = _get_bool("RERANKER_ENABLED", True)
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
RERANKER_MODEL_PATH = _get_path(
    "RERANKER_MODEL_PATH", "models/local_models/reranker/bge-reranker-v2-m3"
)
RERANKER_DEVICE = _resolve_device("RERANKER_DEVICE", "auto")
RERANKER_WARMUP = _get_bool("RERANKER_WARMUP", False)
RERANKER_CANDIDATE_TOP_K = _get_int("RERANKER_CANDIDATE_TOP_K", 10)
RERANKER_TOP_K = _get_int("RERANKER_TOP_K", 5)
RERANKER_BATCH_SIZE = _get_int("RERANKER_BATCH_SIZE", 8)

# GraphRAG retrieval leg (docs/specs/graphrag). Default OFF — the graph leg is
# opt-in so existing deployments are byte-for-byte unaffected (REQ-GR-008). When
# off, no extraction LLM calls fire and no graph_store writes occur. The weight
# feeds RRF as the third leg's contribution (normalised with dense+sparse);
# 0.4 is a conservative starting point for eval-flywheel calibration.
GRAPH_RAG_ENABLED = _get_bool("GRAPH_RAG_ENABLED", False)
GRAPH_RAG_WEIGHT = _get_float("GRAPH_RAG_WEIGHT", 0.4)
GRAPH_RAG_TOP_K = _get_int("GRAPH_RAG_TOP_K", 5)
# Extraction uses temperature 0 for determinism (golden-test contract).
GRAPH_RAG_EXTRACT_TEMPERATURE = _get_float("GRAPH_RAG_EXTRACT_TEMPERATURE", 0.0)
# Cap chunks-per-doc sent to the extractor to bound Ollama load (STRIDE DoS).
GRAPH_RAG_MAX_CHUNKS_PER_DOC = _get_int("GRAPH_RAG_MAX_CHUNKS_PER_DOC", 200)

# Intent-routing confidence gate (Bug2 Layer ②). A rag_query classified below
# this confidence falls back to general_chat (avoids misrouting ambiguous
# capability/general questions into retrieval). NOTE: prior placeholder — the
# project has no calibration data yet (defender F-06); tuned via hard rag_query
# golden regression cases. Domain-query override (_looks_like_domain_query) is a
# stronger signal and still forces RAG regardless of confidence.
LOW_INTENT_THRESHOLD = _get_float("LOW_INTENT_THRESHOLD", 0.5)

# OpenTelemetry: disabled by default for local development.
OTEL_ENABLED = _get_bool("OTEL_ENABLED", False)
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "rag-platform")
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
OTEL_SAMPLE_RATE = _get_float("OTEL_SAMPLE_RATE", 1.0)
OTEL_CONSOLE_EXPORTER = _get_bool("OTEL_CONSOLE_EXPORTER", False)


# Storage. Do not use the name `MILVUS_URI`; pymilvus reserves it for servers.
def resolve_milvus_uri() -> str:
    return os.getenv("MILVUS_DB_URI") or os.getenv("MILVUS_URI") or "./milvus_data.db"


MILVUS_URI = resolve_milvus_uri()


def runtime_config_fingerprint() -> dict[str, str | int]:
    settings = resolve_embedding_settings()
    payload = {
        "schema_version": 1,
        "profile": os.getenv("DOMAIN_PROFILE", "general"),
        "embedding_provider": settings.provider,
        "embedding_model": settings.model,
        "embedding_dimension": settings.dimension,
        "collection": os.getenv("COLLECTION_NAME", "rag_knowledge_base"),
        "sparse_enabled": settings.sparse_enabled,
        "reranker_enabled": _get_bool("RERANKER_ENABLED", True),
        "reranker_model": os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
        "graph_enabled": _get_bool("GRAPH_RAG_ENABLED", False),
        "late_chunking_enabled": _get_bool("LATE_CHUNKING_ENABLED", True),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "schema_version": 1,
        "fingerprint": hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12],
    }


COLLECTION_NAME = os.getenv("COLLECTION_NAME", "rag_knowledge_base")

# Vector index tuning. AUTOINDEX is the safe default (works on Milvus Lite).
# Switch to HNSW / IVF_FLAT on a standalone Milvus server for tunable
# recall-vs-latency trade-offs. Index build + search params are JSON env vars.
MILVUS_INDEX_TYPE = os.getenv("MILVUS_INDEX_TYPE", "AUTOINDEX")
MILVUS_INDEX_PARAMS = os.getenv("MILVUS_INDEX_PARAMS", "")  # e.g. {"M":16,"efConstruction":200}
MILVUS_SEARCH_PARAMS = os.getenv("MILVUS_SEARCH_PARAMS", "")  # e.g. {"ef":64} or {"nprobe":10}

# PDF ingestion. OCR is opt-in because local OCR engines add non-trivial
# dependencies and memory usage.
PDF_EXTRACT_TABLES = _get_bool("PDF_EXTRACT_TABLES", True)
PDF_OCR_ENABLED = _get_bool("PDF_OCR_ENABLED", False)
PDF_OCR_ENGINE = os.getenv("PDF_OCR_ENGINE", "paddleocr")
PDF_OCR_LANG = os.getenv("PDF_OCR_LANG", "ch")
PDF_OCR_DPI = _get_int("PDF_OCR_DPI", 220)
PDF_OCR_MIN_TEXT_CHARS = _get_int("PDF_OCR_MIN_TEXT_CHARS", 20)
PDF_ASSET_DIR = _get_path("PDF_ASSET_DIR", "data/document_assets")
