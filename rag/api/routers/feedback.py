"""
Feedback and Escalation API Endpoints
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.routers.admin import require_admin
from utils.log_utils import log

router = APIRouter()


class FeedbackRequest(BaseModel):
    session_id: str = Field(..., description="Session ID")
    message_id: str = Field("", description="Message ID being feedbacked on")
    trace_id: str = Field(
        "", description="Trace ID linking to the captured inference (for the eval flywheel)"
    )
    feedback_type: str = Field(..., description="THUMBS_UP, THUMBS_DOWN, CORRECTION, FLAG")
    content: str = Field("", description="Feedback text")
    original_answer: str = Field("", description="Original answer (for corrections)")
    corrected_answer: str = Field("", description="Corrected answer (for corrections)")


class ResolveEscalationRequest(BaseModel):
    resolution: str = Field(..., description="Resolution notes")


@router.post("")
async def submit_feedback(request: FeedbackRequest):
    """Submit user feedback on a response."""
    from agent.feedback.collector import get_feedback_collector
    from agent.feedback.types import FeedbackEntry, FeedbackType

    try:
        ft = FeedbackType(request.feedback_type.lower())
    except ValueError:
        raise HTTPException(400, f"Invalid feedback_type: {request.feedback_type}")

    if ft == FeedbackType.CORRECTION and not request.corrected_answer.strip():
        raise HTTPException(400, "corrected_answer is required for CORRECTION feedback")

    collector = get_feedback_collector()
    entry = FeedbackEntry(
        session_id=request.session_id,
        message_id=request.message_id,
        feedback_type=ft,
        content=request.content,
        original_answer=request.original_answer,
        corrected_answer=request.corrected_answer,
    )
    entry_id = collector.record(entry)

    # If it's a correction, also store in memory
    if ft == FeedbackType.CORRECTION and request.corrected_answer:
        try:
            from agent.memory.extractor import MemoryExtractor
            from agent.memory.store import get_memory_store

            extractor = MemoryExtractor()
            mem = extractor.extract_correction(request.original_answer, request.corrected_answer)
            get_memory_store().store(mem)
        except Exception as e:
            log.warning(f"Failed to store correction in memory: {e}")

    # Evaluation flywheel: on negative feedback, promote the inference to the
    # candidate pool, re-evaluate it with the judge, and record retrieval
    # misses. Best-effort — never blocks feedback submission.
    NEGATIVE = {FeedbackType.THUMBS_DOWN, FeedbackType.CORRECTION, FeedbackType.FLAG}
    if ft in NEGATIVE:
        try:
            from agent.eval.flywheel import on_negative_feedback

            on_negative_feedback(
                trace_id=request.trace_id,
                message_id=request.message_id,
                feedback_type=ft.value,
                corrected_answer=request.corrected_answer,
            )
        except Exception as e:
            log.debug(f"Flywheel trigger skipped: {e}")

    return {"status": "ok", "id": entry_id}


@router.get("/stats/summary")
async def feedback_stats(_: None = Depends(require_admin)):
    """Get aggregate feedback statistics."""
    from agent.feedback.collector import get_feedback_collector

    return get_feedback_collector().get_stats()


@router.get("/escalations/pending")
async def pending_escalations(_: None = Depends(require_admin)):
    """List pending escalations (admin)."""
    from agent.feedback.escalation import get_escalation_manager

    mgr = get_escalation_manager()
    records = mgr.get_pending()
    return {
        "pending": [
            {
                "id": r.id,
                "session_id": r.session_id,
                "level": r.level.value,
                "reason": r.reason,
                "timestamp": r.timestamp,
            }
            for r in records
        ],
    }


@router.get("/{session_id}")
async def get_feedback(session_id: str):
    """Get feedback for a session."""
    from agent.feedback.collector import get_feedback_collector

    collector = get_feedback_collector()
    entries = collector.get_feedback(session_id)
    return {
        "session_id": session_id,
        "feedback": [
            {
                "id": e.id,
                "type": e.feedback_type.value,
                "content": e.content,
                "timestamp": e.timestamp,
            }
            for e in entries
        ],
    }


@router.post("/escalations/{escalation_id}/resolve")
async def resolve_escalation(
    escalation_id: str, request: ResolveEscalationRequest, _: None = Depends(require_admin)
):
    """Resolve an escalation."""
    from agent.feedback.escalation import get_escalation_manager

    mgr = get_escalation_manager()
    ok = mgr.resolve(escalation_id, request.resolution)
    if not ok:
        raise HTTPException(404, "Escalation not found")
    return {"status": "resolved", "id": escalation_id}
