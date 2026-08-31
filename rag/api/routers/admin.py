"""
Admin Router for Enterprise RAG Platform

Handles system administration and monitoring endpoints.

Security: sensitive endpoints (config, inference detail, circuit-breaker
reset, degradation mode) are gated by :func:`require_admin`, which checks an
``X-Admin-Key`` header against the ``ADMIN_API_KEY`` env var. In development,
an unconfigured key permits only localhost (127.0.0.1/::1); production disables
that fallback and startup requires a key. Read-only health/metrics remain open.
"""

from __future__ import annotations

import ipaddress
import os
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

router = APIRouter()


def require_admin(
    request: Request,
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> None:
    """
    Gate sensitive admin endpoints.

    - If ``ADMIN_API_KEY`` is set: the request must carry a matching
      ``X-Admin-Key`` header. The comparison uses ``hmac.compare_digest`` on the
      raw bytes (constant-time for equal-length inputs). The configured key is
      consumed as-is — no ``.strip()`` at compare time, which would both leak
      the key length and silently mutate a key with intentional surrounding
      bytes. (The configured value is stripped once at config load.)
    - If unset in local development: only loopback clients are allowed.
    - If unset in production: fail closed even for loopback clients.

    Raises 401 on missing/mismatched key, 403 on non-loopback without a key.
    """
    import hmac

    configured = os.getenv("ADMIN_API_KEY", "").strip()
    deployment_env = os.getenv("DEPLOYMENT_ENV", "").strip().lower()
    client_host = None
    try:
        client = request.client
        client_host = client.host if client else None
    except Exception:  # noqa: BLE001
        client_host = None

    if configured:
        # Constant-time comparison. A missing header compares against an empty
        # string (rejected). We do NOT strip the supplied header here — the
        # configured key was already stripped above, and stripping the input
        # would re-introduce a length oracle.
        supplied = x_admin_key or ""
        if not hmac.compare_digest(supplied, configured):
            raise HTTPException(status_code=401, detail="invalid or missing admin key")
        return

    if deployment_env == "production":
        raise HTTPException(status_code=401, detail="admin key is required in production")

    # No key configured -> allow loopback (and the in-process Starlette test
    # client, whose client.host is the literal "testclient") so local dev and
    # the test suite keep working. Production MUST set ADMIN_API_KEY to lock
    # these down.
    if client_host:
        if client_host == "testclient":
            return
        try:
            ip = ipaddress.ip_address(client_host)
            if ip.is_loopback:
                return
        except ValueError:
            pass
    raise HTTPException(
        status_code=403,
        detail="admin endpoints require ADMIN_API_KEY or a loopback client",
    )


@router.get("/health")
async def health_check():
    """Detailed health check."""
    from core.fallback.circuit_breaker import get_llm_circuit, get_retriever_circuit

    llm_circuit = get_llm_circuit()
    retriever_circuit = get_retriever_circuit()

    # Check services
    services = {
        "llm": {
            "status": "healthy" if llm_circuit.state.value == "closed" else "degraded",
            "circuit": llm_circuit.state.value,
            "stats": llm_circuit.stats,
        },
        "retriever": {
            "status": "healthy" if retriever_circuit.state.value == "closed" else "degraded",
            "circuit": retriever_circuit.state.value,
            "stats": retriever_circuit.stats,
        },
    }

    # Check vector database
    manager = None
    try:
        from documents.milvus_db import get_milvus_manager

        manager = get_milvus_manager()
        health = manager.health_check()
        milvus_status = (
            "unhealthy"
            if not health.get("connected")
            else "degraded"
            if health.get("embedding_compatible") is False
            else "healthy"
        )
        services["milvus"] = {
            "status": milvus_status,
            "details": health,
        }
    except Exception as e:
        services["milvus"] = {
            "status": "unhealthy",
            "error": str(e),
        }
    finally:
        if manager is not None:
            try:
                manager.close()
            except Exception:
                pass

    from utils.env_utils import RERANKER_ENABLED

    if RERANKER_ENABLED:
        from core.retrieval.reranker import get_reranker

        reranker_status = get_reranker().status()
        services["reranker"] = {
            "status": (
                "healthy"
                if reranker_status["loaded"]
                else "degraded"
                if reranker_status["load_error"]
                else "ready"
                if reranker_status["cached"]
                else "cold"
            ),
            "details": reranker_status,
        }

    # Overall status
    all_operational = all(
        s.get("status") in ("healthy", "degraded", "ready", "cold") for s in services.values()
    )
    milvus_degraded = services.get("milvus", {}).get("status") == "degraded"

    from utils.env_utils import runtime_config_fingerprint

    return {
        "status": "healthy" if all_operational and not milvus_degraded else "degraded",
        "services": services,
        "runtime_config": runtime_config_fingerprint(),
    }


@router.get("/metrics")
async def get_metrics():
    """Get system metrics."""
    import gc
    import platform
    import time

    result = {
        "timestamp": time.time(),
        "memory": {},
        "gc": {},
        "python": {
            "version": platform.python_version(),
        },
    }

    # Memory usage - with error handling
    try:
        import psutil

        process = psutil.Process()
        memory_info = process.memory_info()
        result["memory"] = {
            "rss_mb": memory_info.rss / 1024 / 1024,
            "vms_mb": memory_info.vms / 1024 / 1024,
        }
    except ImportError:
        result["memory"] = {"error": "psutil not installed"}
    except Exception as e:
        result["memory"] = {"error": str(e)}

    # GC stats - with error handling
    try:
        gc_stats_list = gc.get_stats()
        if gc_stats_list:
            result["gc"] = {
                f"gen_{i}": {
                    "collections": stat[0],
                    "collected": stat[1],
                    "uncollectable": stat[2],
                }
                for i, stat in enumerate(gc_stats_list)
            }
        else:
            result["gc"] = {"info": "no stats available"}
    except Exception as e:
        result["gc"] = {"error": str(e)}

    return result


@router.get("/circuit-breakers")
async def get_circuit_breakers():
    """Get circuit breaker status."""
    from core.fallback.circuit_breaker import get_llm_circuit, get_retriever_circuit

    return {
        "llm": get_llm_circuit().stats,
        "retriever": get_retriever_circuit().stats,
    }


@router.post("/circuit-breakers/{name}/reset")
async def reset_circuit_breaker(
    name: Literal["llm", "retriever"], _: None = Depends(require_admin)
):
    """Reset a circuit breaker."""
    from core.fallback.circuit_breaker import get_llm_circuit, get_retriever_circuit

    if name == "llm":
        get_llm_circuit().reset()
        return {"status": "success", "message": "LLM circuit breaker reset"}
    elif name == "retriever":
        get_retriever_circuit().reset()
        return {"status": "success", "message": "Retriever circuit breaker reset"}


@router.get("/degradation")
async def get_degradation_status():
    """Get degradation handler status."""
    from core.fallback.degradation import get_degradation_handler

    handler = get_degradation_handler()
    return handler.get_stats()


@router.post("/degradation/mode/{mode}")
async def set_degradation_mode(
    mode: Literal["full", "cached", "simplified", "offline"],
    _: None = Depends(require_admin),
):
    """Set degradation mode."""
    from core.fallback.degradation import FallbackMode, get_degradation_handler

    handler = get_degradation_handler()
    new_mode = FallbackMode(mode)
    handler.mode = new_mode
    return {"status": "success", "mode": new_mode.value}


@router.get("/config")
async def get_config(_: None = Depends(require_admin)):
    """Get current configuration."""
    from utils.env_utils import (
        COLLECTION_NAME,
        DASHSCOPE_BASE_URL,
        EMBEDDING_BATCH_SIZE,
        EMBEDDING_DEVICE,
        EMBEDDING_NORMALIZE,
        LLM_MAX_RETRIES,
        LLM_MAX_TOKENS,
        LLM_MODEL,
        LLM_TEMPERATURE,
        LLM_TIMEOUT,
        MILVUS_URI,
        OTEL_CONSOLE_EXPORTER,
        OTEL_ENABLED,
        OTEL_EXPORTER_OTLP_ENDPOINT,
        OTEL_SAMPLE_RATE,
        OTEL_SERVICE_NAME,
        PDF_ASSET_DIR,
        PDF_EXTRACT_TABLES,
        PDF_OCR_DPI,
        PDF_OCR_ENABLED,
        PDF_OCR_ENGINE,
        PDF_OCR_LANG,
        PDF_OCR_MIN_TEXT_CHARS,
        RERANKER_BATCH_SIZE,
        RERANKER_CANDIDATE_TOP_K,
        RERANKER_DEVICE,
        RERANKER_ENABLED,
        RERANKER_MODEL,
        RERANKER_MODEL_PATH,
        RERANKER_TOP_K,
        RERANKER_WARMUP,
        resolve_embedding_settings,
        runtime_config_fingerprint,
    )

    embedding_settings = resolve_embedding_settings()

    return {
        "runtime_config": runtime_config_fingerprint(),
        "llm": {
            "model": LLM_MODEL,
            "temperature": LLM_TEMPERATURE,
            "max_tokens": LLM_MAX_TOKENS,
            "timeout": LLM_TIMEOUT,
            "max_retries": LLM_MAX_RETRIES,
        },
        "embedding": {
            "model": embedding_settings.model,
            "model_source": embedding_settings.model_source,
            "provider": embedding_settings.provider,
            "local_path": embedding_settings.model_path,
            "dimension": embedding_settings.dimension,
            "device": EMBEDDING_DEVICE,
            "normalize": EMBEDDING_NORMALIZE,
            "batch_size": EMBEDDING_BATCH_SIZE,
            "api_base_url": (DASHSCOPE_BASE_URL if embedding_settings.provider == "api" else None),
        },
        "reranker": {
            "enabled": RERANKER_ENABLED,
            "model": RERANKER_MODEL,
            "local_path": RERANKER_MODEL_PATH,
            "device": RERANKER_DEVICE,
            "warmup": RERANKER_WARMUP,
            "candidate_top_k": RERANKER_CANDIDATE_TOP_K,
            "top_k": RERANKER_TOP_K,
            "batch_size": RERANKER_BATCH_SIZE,
        },
        "opentelemetry": {
            "enabled": OTEL_ENABLED,
            "service_name": OTEL_SERVICE_NAME,
            "endpoint": OTEL_EXPORTER_OTLP_ENDPOINT,
            "sample_rate": OTEL_SAMPLE_RATE,
            "console_exporter": OTEL_CONSOLE_EXPORTER,
        },
        "milvus": {
            "uri": MILVUS_URI,
            "collection": COLLECTION_NAME,
        },
        "pdf_ingestion": {
            "extract_tables": PDF_EXTRACT_TABLES,
            "ocr_enabled": PDF_OCR_ENABLED,
            "ocr_engine": PDF_OCR_ENGINE,
            "ocr_lang": PDF_OCR_LANG,
            "ocr_dpi": PDF_OCR_DPI,
            "ocr_min_text_chars": PDF_OCR_MIN_TEXT_CHARS,
            "asset_dir": PDF_ASSET_DIR,
        },
        "session": {
            "ttl": 3600,
            "max_messages": 50,
        },
    }


# =============================================================================
# Evaluation flywheel endpoints
# =============================================================================


@router.get("/eval/runs")
async def eval_runs(limit: int = Query(20, ge=1, le=200), _: None = Depends(require_admin)):
    """List recent evaluation run summaries (history.jsonl)."""
    from agent.eval import load_history

    summaries = load_history(limit=limit)
    return {"runs": [s.to_dict() for s in summaries]}


@router.get("/eval/runs/{run_id}")
async def eval_run_detail(run_id: str, _: None = Depends(require_admin)):
    """Full per-case detail for one eval run."""
    import json
    import re
    from pathlib import Path

    from fastapi import HTTPException

    # Defence-in-depth against path traversal: the run_id is user-controlled
    # and flows into a filesystem path. Reject anything outside the safe
    # allowlist BEFORE touching the filesystem (route converter alone does not
    # decode %2f, so an encoded '/' could otherwise reach here).
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise HTTPException(400, "Invalid run_id")
    runs_dir = Path("data/eval/runs").resolve()
    path = runs_dir / f"{run_id}.json"
    if not path.resolve().is_relative_to(runs_dir):
        raise HTTPException(400, "Invalid run_id")
    if not path.exists():
        raise HTTPException(404, f"Run not found: {run_id}")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/eval/candidates")
async def eval_candidates(_: None = Depends(require_admin)):
    """List candidates promoted from production feedback (awaiting golden promotion)."""
    from agent.eval import list_candidates

    cands = list_candidates()
    return {
        "total": len(cands),
        "candidates": [
            {
                "candidate_id": c.candidate_id,
                "feedback_type": c.feedback_type,
                "source": c.source,
                "query": c.query,
                "has_correction": bool(c.corrected_answer.strip()),
                "created_at": c.created_at,
            }
            for c in cands
        ],
    }


@router.get("/inferences")
async def inferences(limit: int = 50, offset: int = 0, _: None = Depends(require_admin)):
    """Browse sampled production inferences."""
    from agent.eval import get_inference_store

    store = get_inference_store()
    recs = store.list_sampled(limit=limit, offset=offset)
    stats = store.stats()
    return {
        "stats": stats,
        "inferences": [
            {
                "trace_id": r.trace_id,
                "message_id": r.message_id,
                "session_id": r.session_id,
                "query": r.query[:200],
                "route": r.route,
                "intent": r.intent,
                "source_count": len(r.retrieved_docs),
                "latency_ms": r.latency_ms,
                "created_at": r.created_at,
            }
            for r in recs
        ],
    }


@router.get("/inferences/{trace_id}")
async def inference_detail(trace_id: str, _: None = Depends(require_admin)):
    """Full detail (incl. retrieved docs + answer) for one inference."""
    from fastapi import HTTPException

    from agent.eval import get_inference_store

    rec = get_inference_store().get(trace_id)
    if rec is None:
        raise HTTPException(404, f"Inference not found: {trace_id}")
    return {
        "trace_id": rec.trace_id,
        "message_id": rec.message_id,
        "session_id": rec.session_id,
        "query": rec.query,
        "retrieved_docs": rec.retrieved_docs,
        "answer": rec.answer,
        "reasoning": rec.reasoning,
        "route": rec.route,
        "prompt_profile": rec.prompt_profile,
        "intent": rec.intent,
        "latency_ms": rec.latency_ms,
        "token_usage": rec.token_usage,
        "git_commit": rec.git_commit,
        "created_at": rec.created_at,
    }


@router.get("/retrieval-misses")
async def retrieval_misses(limit: int = Query(50, ge=1, le=500), _: None = Depends(require_admin)):
    """Retrieval-miss signals for offline tuning (low-faithfulness feedback)."""
    from agent.eval import get_retrieval_misses

    return {"misses": get_retrieval_misses(limit=limit)}
