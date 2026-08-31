from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class MemoryType(str, Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    EPISODE = "episode"
    CORRECTION = "correction"


@dataclass
class MemoryEntry:
    id: str = ""
    memory_type: MemoryType = MemoryType.FACT
    content: str = ""
    metadata: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    access_count: int = 0
    relevance_score: float = 1.0


@dataclass
class MemoryQuery:
    query: str = ""
    memory_types: list[MemoryType] | None = None
    limit: int = 5
    min_relevance: float = 0.0
