"""
Online grounding guardrail — lightweight NLI hallucination check on the
generation hot path.

Unlike the offline ``agent/eval/judge.py`` (full RAGAS-style faithfulness over
all claims), this is a fast online variant focused on "hard claims" (values,
steps, conclusions) — the statements most dangerous to hallucinate in a
structured-domain-answer setting. It reuses the judge's claim-extraction and
entailment machinery so behaviour is consistent between online enforcement
and offline eval.

Reliability contract (critical for the hot path):
  - NEVER raises. On any failure (judge down, parse error, timeout) it returns
    ``None`` so the caller falls back to the legacy regex hallucination check.
  - Reuses the shared ``LLMJudge`` singleton (with its own circuit breaker), so
    repeated judge failures degrade gracefully process-wide.
"""

from __future__ import annotations

import asyncio

from utils.log_utils import log

__all__ = ["GroundingResult", "GroundingGuardrail", "check_grounding"]


class GroundingResult:
    """Outcome of an online grounding check."""

    def __init__(
        self,
        faithfulness: float | None,
        supported: int = 0,
        total: int = 0,
        unsupported_claims: list[str] | None = None,
        degraded: bool = False,
        reason: str = "",
    ):
        self.faithfulness = faithfulness
        self.supported = supported
        self.total = total
        self.unsupported_claims = unsupported_claims or []
        # True when the judge was unavailable and no verdict could be produced.
        self.degraded = degraded
        self.reason = reason

    @property
    def available(self) -> bool:
        """False when the check could not run at all (judge down)."""
        return self.faithfulness is not None

    def to_dict(self) -> dict:
        return {
            "faithfulness": self.faithfulness,
            "supported": self.supported,
            "total": self.total,
            "unsupported_claims": self.unsupported_claims,
            "degraded": self.degraded,
            "reason": self.reason,
        }


class GroundingGuardrail:
    """
    Lightweight online grounding check reusing the eval LLMJudge.

    Construction is cheap; the judge is the shared singleton (lazy). Use
    ``check_grounding(answer, contexts)`` for the module-level convenience.
    """

    def __init__(self, judge=None):
        self._judge = judge

    @property
    def judge(self):
        if self._judge is None:
            try:
                from agent.eval.judge import get_judge

                self._judge = get_judge()
            except Exception as e:  # noqa: BLE001 - judge is optional
                log.debug(f"GroundingGuardrail: judge unavailable: {e}")
                self._judge = None
        return self._judge

    def check(
        self,
        answer: str,
        contexts: list[str],
    ) -> GroundingResult:
        """
        Check how well the answer's hard claims are grounded in the contexts.

        Returns a GroundingResult. ``result.available`` is False when the judge
        could not run (caller should fall back to regex checks). Never raises.
        """
        if not answer.strip() or not any(c.strip() for c in contexts):
            return GroundingResult(
                faithfulness=None, degraded=True, reason="empty answer or contexts"
            )

        judge = self.judge
        if judge is None or not judge.available:
            return GroundingResult(
                faithfulness=None, degraded=True, reason="judge unavailable (circuit open)"
            )

        try:
            # Reuse the judge's claim extraction + entailment, scoped to hard
            # claims (values/steps/conclusions) — the dangerous ones.
            from agent.eval.judge import is_hard_claim, split_claims

            claims = split_claims(answer)
            hard_claims = [c for c in claims if is_hard_claim(c)]
            if not hard_claims:
                # No hard claims => nothing dangerous to hallucinate. Treat as
                # fully grounded (1.0) so we don't penalise safe, soft answers.
                return GroundingResult(
                    faithfulness=1.0,
                    supported=0,
                    total=0,
                    reason="no hard claims to verify",
                )

            context_blob = "\n\n".join(
                f"[片段{i + 1}] {c.strip()}" for i, c in enumerate(contexts) if c.strip()
            )
            supported = 0
            unsupported: list[str] = []
            judged = 0
            for claim in hard_claims:
                verdict = judge.entail(claim, context_blob)
                if verdict is None:
                    continue  # unavailable != unsupported
                judged += 1
                if verdict.supported:
                    supported += 1
                else:
                    unsupported.append(claim)

            if judged == 0:
                return GroundingResult(
                    faithfulness=None,
                    degraded=True,
                    reason="judge could not evaluate any claim",
                )

            faith = supported / judged
            return GroundingResult(
                faithfulness=faith,
                supported=supported,
                total=judged,
                unsupported_claims=unsupported,
                reason=f"{supported}/{judged} hard claims grounded",
            )
        except Exception as e:  # noqa: BLE001 - hot path must not crash
            log.warning(f"GroundingGuardrail check failed: {e}")
            return GroundingResult(faithfulness=None, degraded=True, reason=f"error: {e}")

    async def acheck(
        self,
        answer: str,
        contexts: list[str],
    ) -> GroundingResult:
        """
        Async grounding check that fans out the per-claim entailment calls
        concurrently via ``asyncio.gather``.

        This is the variant the async/streaming generate path should use: the
        sync ``check`` issues one blocking judge round-trip per hard claim,
        which freezes the event loop for N claims. ``acheck`` overlaps them.

        Same reliability contract as ``check``: never raises, returns a
        degraded ``GroundingResult`` on any failure.
        """
        if not answer.strip() or not any(c.strip() for c in contexts):
            return GroundingResult(
                faithfulness=None, degraded=True, reason="empty answer or contexts"
            )

        judge = self.judge
        if judge is None or not judge.available:
            return GroundingResult(
                faithfulness=None, degraded=True, reason="judge unavailable (circuit open)"
            )

        try:
            from agent.eval.judge import is_hard_claim, split_claims

            claims = split_claims(answer)
            hard_claims = [c for c in claims if is_hard_claim(c)]
            if not hard_claims:
                return GroundingResult(
                    faithfulness=1.0,
                    supported=0,
                    total=0,
                    reason="no hard claims to verify",
                )

            context_blob = "\n\n".join(
                f"[片段{i + 1}] {c.strip()}" for i, c in enumerate(contexts) if c.strip()
            )

            # Fan out all claims concurrently; isolate per-claim failures.
            verdicts = await asyncio.gather(
                *[judge.aentail(c, context_blob) for c in hard_claims],
                return_exceptions=True,
            )

            supported = 0
            unsupported: list[str] = []
            judged = 0
            for claim, verdict in zip(hard_claims, verdicts):
                if isinstance(verdict, Exception) or verdict is None:
                    continue  # unavailable != unsupported
                judged += 1
                if verdict.supported:
                    supported += 1
                else:
                    unsupported.append(claim)

            if judged == 0:
                return GroundingResult(
                    faithfulness=None,
                    degraded=True,
                    reason="judge could not evaluate any claim",
                )

            faith = supported / judged
            return GroundingResult(
                faithfulness=faith,
                supported=supported,
                total=judged,
                unsupported_claims=unsupported,
                reason=f"{supported}/{judged} hard claims grounded (async)",
            )
        except Exception as e:  # noqa: BLE001 - hot path must not crash
            log.warning(f"GroundingGuardrail acheck failed: {e}")
            return GroundingResult(faithfulness=None, degraded=True, reason=f"error: {e}")


_guardrail: GroundingGuardrail | None = None


def check_grounding(answer: str, contexts: list[str]) -> GroundingResult:
    """Module-level convenience: check grounding via the shared guardrail."""
    global _guardrail
    if _guardrail is None:
        _guardrail = GroundingGuardrail()
    return _guardrail.check(answer, contexts)


async def acheck_grounding(answer: str, contexts: list[str]) -> GroundingResult:
    """Async module-level convenience: concurrent grounding check."""
    global _guardrail
    if _guardrail is None:
        _guardrail = GroundingGuardrail()
    return await _guardrail.acheck(answer, contexts)
