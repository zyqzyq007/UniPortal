from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


class GuardrailAction(str, Enum):
    """Possible outcomes from a guardrail check."""

    ALLOW = "allow"
    BLOCK = "block"
    SANITIZE = "sanitize"
    ESCALATE = "escalate"


@dataclass
class GuardrailResult:
    """Result returned by every guardrail check."""

    action: GuardrailAction
    reason: str = ""
    sanitized_content: str | None = None
    confidence: float = 1.0
    metadata: dict = field(default_factory=dict)


@dataclass
class GuardrailConfig:
    """Configuration for the guardrail subsystem."""

    max_input_length: int = 2000
    enable_injection_detection: bool = True
    enable_topic_check: bool = True
    enable_safety_check: bool = True
    enable_hallucination_check: bool = True
    enable_structure_check: bool = True
    # Online grounding (NLI) hallucination check on the generation hot path.
    # When enabled and contexts are available, _check_hallucination uses the
    # LLMJudge instead of the legacy regex; on judge failure it degrades to
    # the regex path so responses are never blocked.
    enable_grounding_check: bool = _env_bool("GROUNDING_CHECK_ENABLED", True)
    grounding_threshold: float = _env_float("GROUNDING_THRESHOLD", 0.5)
    # Faithfulness below this triggers ESCALATE (human review) rather than the
    # softer SANITIZE (append a caveat). Defaults to "fully unsupported".
    grounding_escalate_threshold: float = _env_float("GROUNDING_ESCALATE_THRESHOLD", 0.0)
    # PII detection / redaction (P3.1).
    enable_pii_check: bool = _env_bool("PII_CHECK_ENABLED", True)
    pii_redact_output: bool = _env_bool("PII_REDACT_OUTPUT", True)
