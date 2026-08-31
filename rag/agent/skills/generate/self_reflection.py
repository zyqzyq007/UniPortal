"""
Self-reflection on captured reasoning (P2.6).

Qwen3's reasoning trace is currently captured and shown to the user but never
fed back into quality control. This module does a lightweight self-reflection
pass: when the reasoning expresses uncertainty (hedging words, contradiction
markers) AND the answer makes hard claims, it flags the answer for a caveat.

This is deliberately cheap (regex over the reasoning string, no extra LLM
call) so it adds no latency to the hot path. A future enhancement could do a
full self-consistency check via a second LLM call.
"""

from __future__ import annotations

import re

from agent.eval.judge import is_hard_claim, split_claims

__all__ = ["reflect_on_reasoning", "SelfReflectionResult"]


class SelfReflectionResult:
    def __init__(self, confident: bool, signal: str = "", caveat: str = ""):
        self.confident = confident
        self.signal = signal
        self.caveat = caveat  # text to append if not confident

    def to_dict(self) -> dict:
        return {"confident": self.confident, "signal": self.signal, "caveat": self.caveat}


# Markers that the model itself is unsure during reasoning.
_HEDGE_RE = re.compile(
    r"(?i)不确定|可能|也许|大概|似乎|推测|猜测|不肯定|存疑|"
    r"unsure|uncertain|maybe|perhaps|might|guess|unclear"
)
_CONTRADICTION_RE = re.compile(r"(?i)矛盾|冲突|不一致|相反|but also|however|on the other hand")


def reflect_on_reasoning(
    answer: str,
    reasoning: str,
    grounding_faithfulness: float | None = None,
) -> SelfReflectionResult:
    """
    Inspect the reasoning trace for uncertainty signals.

    Args:
        answer: the generated answer.
        reasoning: the captured Qwen3 reasoning trace.
        grounding_faithfulness: optional NLI faithfulness score (from grounding).

    Returns a SelfReflectionResult. ``confident=False`` means the answer
    should carry a caveat; the caveat text is in ``result.caveat``.
    """
    if not reasoning or not reasoning.strip():
        return SelfReflectionResult(confident=True, signal="no reasoning captured")

    # Only reflect when the answer makes hard claims (values/steps/conclusions)
    # — soft answers don't need the uncertainty check.
    claims = split_claims(answer)
    has_hard_claims = any(is_hard_claim(c) for c in claims)
    if not has_hard_claims:
        return SelfReflectionResult(confident=True, signal="no hard claims")

    hedged = bool(_HEDGE_RE.search(reasoning))
    contradicted = bool(_CONTRADICTION_RE.search(reasoning))
    low_grounding = grounding_faithfulness is not None and grounding_faithfulness < 0.5

    if contradicted:
        return SelfReflectionResult(
            confident=False,
            signal="reasoning contains contradiction",
            caveat="\n\n> ⚠️ 提示：模型推理过程存在不确定性，请重点核对上述结论。",
        )
    if hedged and (low_grounding or grounding_faithfulness is None):
        return SelfReflectionResult(
            confident=False,
            signal="reasoning expresses uncertainty",
            caveat="\n\n> 💡 提示：本结论的推理过程存在不确定性，建议交叉验证。",
        )
    return SelfReflectionResult(confident=True, signal="reasoning consistent")
