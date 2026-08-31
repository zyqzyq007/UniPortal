from __future__ import annotations

import math


def stable_sigmoid(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("score must be finite")
    if value >= 0:
        factor = math.exp(-value)
        return 1.0 / (1.0 + factor)
    factor = math.exp(value)
    return factor / (1.0 + factor)


def finite_real(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def raw_logit_probability(value: object) -> float | None:
    result = finite_real(value)
    return stable_sigmoid(result) if result is not None else None


def probability(value: object) -> float | None:
    result = finite_real(value)
    if result is None or not 0.0 <= result <= 1.0:
        return None
    return result
