"""
Session Context

Encapsulates session-level metadata for an agent run.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

__all__ = ["SessionContext"]


@dataclass
class SessionContext:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    thread_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    mode: str = "thinking"
    user_id: str | None = None
    # Derived from the active domain profile (was a hardcoded "phm_diagnosis_v1").
    # Lazy import keeps the dataclass dependency-free at module import time.
    prompt_profile: str = field(default_factory=lambda: _active_prompt_profile_generate())


def _active_prompt_profile_generate() -> str:
    """Return the active profile's generate label (domain-adaptive default)."""
    from core.prompts.domain_profile import get_active_profile

    return get_active_profile().prompt_profile_generate
