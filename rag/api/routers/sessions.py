"""
Sessions Router for Enterprise RAG Platform

Handles session management endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from utils.log_utils import log

router = APIRouter()


# =============================================================================
# Models
# =============================================================================


class SessionInfo(BaseModel):
    """Session information model."""

    session_id: str
    message_count: int
    title: str = ""
    created_at: float | None = None
    last_active: float | None = None


class SessionListResponse(BaseModel):
    """Session list response."""

    sessions: list[SessionInfo]
    total: int


class SessionCreateResponse(BaseModel):
    """Session creation response."""

    session_id: str
    message: str


# =============================================================================
# Dependencies
# =============================================================================


async def get_session_memory():
    """Get session memory instance."""
    from core.memory.redis_memory import get_session_memory

    return get_session_memory()


# =============================================================================
# Endpoints
# =============================================================================


@router.post("", response_model=SessionCreateResponse)
async def create_session():
    """Create a new session."""
    import uuid

    session_id = str(uuid.uuid4())

    return SessionCreateResponse(
        session_id=session_id,
        message="Session created successfully",
    )


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    skip: int = 0,
    limit: int = Query(20, ge=1, le=200),
    session_memory=Depends(get_session_memory),
):
    """List all active sessions."""
    try:
        sessions, total = await session_memory.list_sessions(skip, limit)
        return SessionListResponse(
            sessions=[
                SessionInfo(
                    session_id=s["session_id"],
                    message_count=s.get("message_count", 0),
                    title=s.get("title", ""),
                    created_at=s.get("created_at"),
                    last_active=s.get("last_active"),
                )
                for s in sessions
            ],
            total=total,
        )
    except Exception as e:
        log.error(f"Failed to list sessions: {e}")
        raise HTTPException(status_code=500, detail="服务暂时不可用，请稍后重试")


@router.get("/{session_id}", response_model=SessionInfo)
async def get_session(
    session_id: str,
    session_memory=Depends(get_session_memory),
):
    """Get session details."""
    try:
        info = await session_memory.get_session_info(session_id)

        if not info.get("exists", False):
            raise HTTPException(status_code=404, detail="Session not found")

        return SessionInfo(
            session_id=session_id,
            message_count=info.get("message_count", 0),
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to get session: {e}")
        raise HTTPException(status_code=500, detail="服务暂时不可用，请稍后重试")


@router.post("/{session_id}/extend")
async def extend_session(
    session_id: str,
    session_memory=Depends(get_session_memory),
):
    """Refresh a session's last-active timestamp."""
    try:
        if not await session_memory.session_exists(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        await session_memory.register_session(session_id)
        return {"status": "success", "message": f"Session {session_id} extended"}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to extend session: {e}")
        raise HTTPException(status_code=500, detail="服务暂时不可用，请稍后重试")


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    session_memory=Depends(get_session_memory),
):
    """Delete a session and its history."""
    try:
        await session_memory.clear_session(session_id)
        return {"status": "success", "message": f"Session {session_id} deleted"}

    except Exception as e:
        log.error(f"Failed to delete session: {e}")
        raise HTTPException(status_code=500, detail="服务暂时不可用，请稍后重试")
