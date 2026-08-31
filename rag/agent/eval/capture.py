"""
Capture helper: a single function the chat router calls to (maybe) record an
inference. Keeps the router's three response paths (general_chat / rag / fast /
degraded) DRY and minimises the diff to existing code.

Usage in the router (right before returning the ChatResponse):

    from agent.eval.capture import maybe_capture_inference
    maybe_capture_inference(
        request=request,
        request_message=request.message,
        answer=answer,
        sources=sources,
        reasoning=reasoning_text,
        route=route,
        prompt_profile=prompt_profile,
        intent=intent_str,
        metadata=metadata_dict,
        latency_ms=processing_time,
        trace_id=getattr(request, "state", None) and request.state.trace_id,
        session_id=session_id,
    )
"""

from __future__ import annotations

from typing import Any

from agent.eval.history import get_git_commit
from agent.eval.inference_store import InferenceRecord, get_inference_store
from agent.eval.sampler import should_sample
from utils.log_utils import log

__all__ = ["maybe_capture_inference"]

# Cache the git commit for the process lifetime.
_git_commit: str | None = None


def _cached_commit() -> str:
    global _git_commit
    if _git_commit is None:
        _git_commit = get_git_commit()
    return _git_commit


def _sources_to_docs(sources: list[Any]) -> list[dict[str, Any]]:
    """Normalise SourceDocument-like objects into plain dicts."""
    docs = []
    for s in sources or []:
        if hasattr(s, "model_dump"):
            docs.append(s.model_dump())
        elif isinstance(s, dict):
            docs.append(s)
        else:
            docs.append(
                {
                    "content": getattr(s, "content", ""),
                    "source": getattr(s, "source", None),
                    "title": getattr(s, "title", None),
                    "score": getattr(s, "score", 0.0),
                }
            )
    return docs


def maybe_capture_inference(
    *,
    request_message: str,
    answer: str,
    sources: list[Any],
    reasoning: str,
    route: str,
    prompt_profile: str,
    intent: str,
    metadata: dict[str, Any],
    latency_ms: float,
    trace_id: str,
    session_id: str,
    token_usage: dict[str, Any] | None = None,
) -> str | None:
    """
    Sample and persist an inference record. Returns the captured trace_id
    (also written into metadata['trace_id'] / metadata['message_id'] so the
    response carries it back to the client for feedback linkage), or None
    if the request was not sampled.
    """
    try:
        if not should_sample(metadata, route):
            return None

        record = InferenceRecord(
            trace_id=trace_id or "",
            message_id=metadata.get("message_id", "") or "",
            session_id=session_id or "",
            query=request_message,
            retrieved_docs=_sources_to_docs(sources),
            answer=answer,
            reasoning=reasoning or "",
            route=route,
            prompt_profile=prompt_profile,
            intent=intent,
            latency_ms=latency_ms,
            token_usage=token_usage or {},
            git_commit=_cached_commit(),
            sampled=True,
        )
        store = get_inference_store()
        tid = store.record(record)
        # Reflect ids back into metadata so the client can reference them
        # when submitting feedback.
        metadata["trace_id"] = tid
        metadata["message_id"] = record.message_id
        return tid
    except Exception as e:  # noqa: BLE001 - capture must never break chat
        log.warning(f"inference capture failed: {e}")
        return None
