"""
Importance sampling for the inference store.

Controls how much of production traffic is captured. The default rate is
configurable via the ``EVAL_SAMPLE_RATE`` env var (0.0-1.0). Even when the
random rate rejects a request, "important" requests are always captured:

  - degraded responses (route == degraded)
  - low-intent-confidence / forced-rag responses
  - responses flagged by guardrails

This ensures negative-signal traffic — which matters most for the flywheel —
is never under-sampled.
"""

from __future__ import annotations

import os
import random
from typing import Any

__all__ = ["should_sample", "DEFAULT_SAMPLE_RATE"]


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return default


DEFAULT_SAMPLE_RATE = _env_float("EVAL_SAMPLE_RATE", 0.1)

# When EVAL_SAMPLE_RATE is 0 we still capture these important signals at this
# floor rate, so the flywheel never starves.
FLOOR_RATE = _env_float("EVAL_FLOOR_RATE", 0.05)

_rng = random.Random()


def should_sample(
    metadata: dict[str, Any],
    route: str,
    sample_rate: float = DEFAULT_SAMPLE_RATE,
) -> bool:
    """
    Decide whether to capture this request in the inference store.

    Args:
        metadata: response metadata dict (intent_confidence, force_rag, etc.)
        route: response route (rag / fast / general_chat / degraded)
        sample_rate: base random sample rate

    Returns:
        True if the request should be captured.
    """
    # Always capture important / negative signals.
    if route == "degraded":
        return True
    if metadata.get("force_rag"):
        return True
    # Low intent confidence is interesting for the flywheel.
    conf = metadata.get("intent_confidence")
    if isinstance(conf, (int, float)) and conf < 0.5:
        return True
    # Guardrail-blocked or flagged responses.
    if metadata.get("blocked") or metadata.get("flagged"):
        return True

    # Random sampling for the rest.
    # sample_rate <= 0 means the operator explicitly disabled sampling for
    # ordinary traffic (important signals above were already captured).
    if sample_rate <= 0.0:
        return False
    # Apply a floor so the flywheel never fully starves at very low rates.
    rate = max(sample_rate, FLOOR_RATE)
    if rate >= 1.0:
        return True
    return _rng.random() < rate
