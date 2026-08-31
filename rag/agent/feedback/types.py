from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class FeedbackType(str, Enum):
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    CORRECTION = "correction"
    FLAG = "flag"


@dataclass
class FeedbackEntry:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    message_id: str = ""
    feedback_type: FeedbackType = FeedbackType.THUMBS_UP
    content: str = ""
    original_answer: str = ""
    corrected_answer: str = ""
    timestamp: float = field(default_factory=time.time)


class EscalationLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class EscalationRecord:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    level: EscalationLevel = EscalationLevel.NONE
    reason: str = ""
    answer: str = ""
    context_snapshot: dict = field(default_factory=dict)
    resolved: bool = False
    timestamp: float = field(default_factory=time.time)
