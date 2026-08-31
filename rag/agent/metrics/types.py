"""
Metrics Types

Dataclasses for tracking token usage, costs, quality signals, and run metrics.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from utils.env_utils import LLM_MODEL


@dataclass
class TokenUsage:
    """Token usage from a single LLM call."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model_name: str = LLM_MODEL


@dataclass
class CostRecord:
    """Cost record for a single skill invocation."""

    skill_name: str
    token_usage: TokenUsage
    estimated_cost_usd: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class QualitySignal:
    """A quality signal extracted from a skill result."""

    skill_name: str
    signal_type: str
    value: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class RunMetrics:
    """Aggregated metrics for a single run."""

    total_tokens: int = 0
    total_cost_usd: float = 0.0
    quality_signals: list[QualitySignal] = field(default_factory=list)
    skill_durations: dict[str, float] = field(default_factory=dict)
