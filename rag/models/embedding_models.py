"""Embedding model factory with environment-based configuration.

Provider selection (api-only-deploy, REQ-AO-001/010/011): ``get_embeddings()``
dispatches on ``EMBEDDING_PROVIDER`` (``auto`` | ``local`` | ``api``).
- ``local`` → ``HuggingFaceEmbeddings`` (needs torch; ``local-models`` extra).
- ``api``   → ``DashScopeEmbeddings`` (httpx only; zero torch).
- ``auto``  → ``local`` when torch + langchain_huggingface are importable, else
  ``api``. The API-only image therefore picks DashScope automatically.

The ``langchain_huggingface`` import is deliberately lazy (inside
``_get_local_embeddings``) so that ``import models.embedding_models`` succeeds
in a torch-less install; a missing extra raises a clear, actionable error at
use time rather than at module import.
"""

from __future__ import annotations

import os
from typing import Any

from utils.env_utils import (
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_DEVICE,
    EMBEDDING_NORMALIZE,
    resolve_embedding_settings,
)
from utils.log_utils import log

# Unified singleton (local or api instance). Typed as Any to avoid importing
# HuggingFaceEmbeddings at module load (it pulls torch).
_instance: Any = None


def is_embedding_model_cached() -> bool:
    """Return whether the configured local path contains a saved model."""
    settings = resolve_embedding_settings()
    if settings.provider != "local" or not settings.model_path:
        return False
    from pathlib import Path

    local_path = Path(settings.model_path)
    return local_path.is_dir() and any(
        (local_path / marker).is_file()
        for marker in ("modules.json", "config.json", "model.safetensors")
    )


def get_embedding_model_source() -> str:
    """Return the local model path when available, otherwise the model ID."""
    return resolve_embedding_settings().model_source


# =============================================================================
# Provider dispatch
# =============================================================================


def _resolve_provider() -> str:
    """Resolve the embedding provider from the live environment.

    F-05: reads ``os.getenv`` on every call (not the module-level constant) so
    tests can switch providers with ``monkeypatch.setenv`` + ``reset_embeddings``
    without coupling to import-time evaluation order.
    """
    raw = os.getenv("EMBEDDING_PROVIDER", "auto").strip().lower()
    if raw == "auto":
        return "local" if _torch_available() else "api"
    if raw not in {"local", "api"}:
        raise ValueError(f"EMBEDDING_PROVIDER must be one of auto|local|api, got {raw!r}")
    return raw


def _torch_available() -> bool:
    """True iff the local-inference stack (torch + langchain_huggingface) is
    importable. Used only to resolve ``auto``; never imports eagerly on the
    success path of ``local`` (which imports inside ``_get_local_embeddings``)."""
    try:
        import langchain_huggingface  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        return False
    return True


def get_embeddings() -> Any:
    """Get or create the configured embedding model singleton.

    Dispatches on ``EMBEDDING_PROVIDER`` (auto/local/api). Returns an object
    implementing the LangChain ``Embeddings`` interface (``embed_query`` /
    ``embed_documents``).
    """
    global _instance
    if _instance is None:
        provider = _resolve_provider()
        if provider == "local":
            _instance = _get_local_embeddings()
        else:
            _instance = _get_api_embeddings()
    return _instance


def _get_local_embeddings() -> Any:
    """Construct the local embedding singleton.

    Dispatches on the effective configured model family. BGE-M3 loads
    ``BGEM3Embeddings`` (dense+sparse+late-chunk) even when its cache directory
    has an opaque name; all others load ``HuggingFaceEmbeddings`` (dense only).
    The ``langchain_huggingface`` import is lazy + guarded so a torch-less
    install fails with an actionable message.
    """
    try:
        import langchain_huggingface  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "Local embedding inference requires the 'local-models' extra "
            "(torch + sentence-transformers). Either run "
            "`uv sync --extra local-models`, or set EMBEDDING_PROVIDER=api "
            "to use the DashScope embedding API instead."
        ) from exc

    settings = resolve_embedding_settings("local")
    model_source = settings.model_source

    if settings.is_bge_m3:
        # BGE-M3: use the dedicated adapter (FlagModel + AutoModel, dense+sparse).
        from models.bge_m3_embeddings import (
            BGEM3Embeddings,
            set_bge_m3_embeddings_instance,
        )

        log.info(f"Creating BGE-M3 embedding model: source={model_source}")
        return set_bge_m3_embeddings_instance(BGEM3Embeddings(model_path=model_source))

    from langchain_huggingface import HuggingFaceEmbeddings

    log.info(f"Creating local embedding model: source={model_source}, device={EMBEDDING_DEVICE}")
    return HuggingFaceEmbeddings(
        model_name=model_source,
        model_kwargs={"device": EMBEDDING_DEVICE},
        encode_kwargs={
            "normalize_embeddings": EMBEDDING_NORMALIZE,
            "batch_size": EMBEDDING_BATCH_SIZE,
        },
    )


def _get_api_embeddings() -> Any:
    """Construct the DashScope API embedding singleton.

    F-02: fail fast on an empty API key — the airgapped image sets
    EMBEDDING_PROVIDER=api + runtime-injected key, so an empty key here means a
    misconfiguration (e.g. a bare ``uv sync`` that auto-resolved to api). Surface
    it at first ``get_embeddings()`` call, not at the first HTTP 401.

    F-05: reads config live from ``os.getenv`` (not the module-level constants)
    so tests can drive provider switching with ``monkeypatch.setenv`` without
    coupling to import-time evaluation order.
    """
    api_key = os.getenv("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "EMBEDDING_PROVIDER resolved to 'api' but DASHSCOPE_API_KEY is empty. "
            "Either set DASHSCOPE_API_KEY (runtime secret), or — for local "
            "inference — run `uv sync --extra local-models` and set "
            "EMBEDDING_PROVIDER=local."
        )
    from models.dashscope_embeddings import DashScopeEmbeddings

    base_url = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com").rstrip("/")
    settings = resolve_embedding_settings("api")

    return DashScopeEmbeddings(
        api_key=api_key,
        base_url=base_url,
        model=settings.model,
        dimension=settings.dimension,
    )


def get_local_embeddings() -> Any:
    """Backwards-compatible alias → ``get_embeddings()``.

    Preserved so the 6 existing call sites need no forced rename (PM-08); the
    dispatch honours ``EMBEDDING_PROVIDER`` and may return either a local or an
    API-backed instance.
    """
    return get_embeddings()


def reset_embeddings(*, reset_bge: bool = True) -> None:
    """Reset the singleton so changed configuration can be applied in tests."""
    global _instance
    _instance = None
    if reset_bge:
        try:
            from models.bge_m3_embeddings import reset_bge_m3_embeddings

            reset_bge_m3_embeddings(reset_outer=False)
        except Exception:
            pass


if __name__ == "__main__":
    text = "这是一个本地部署的测试文本"
    vector = get_embeddings().embed_query(text)
    print(f"provider={_resolve_provider()}, source={get_embedding_model_source()}")
    print(f"向量维度: {len(vector)}")
