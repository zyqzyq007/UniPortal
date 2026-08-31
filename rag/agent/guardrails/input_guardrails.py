from __future__ import annotations

from agent.guardrails.prompts import INJECTION_PATTERNS
from agent.guardrails.types import GuardrailAction, GuardrailConfig, GuardrailResult
from utils.log_utils import log


def _topic_keywords() -> set[str]:
    """
    Topic keywords sourced from the active domain profile.

    Previously hardcoded to aviation vocabulary, this allow-list now reflects
    the configured domain (aviation_phm by default; empty for the general
    profile, which does not gate on domain vocabulary). This is the single
    most important de-coupling point: an aviation-only allow-list would block
    every off-domain knowledge base.
    """
    from core.prompts.domain_profile import get_active_profile

    return {kw.lower() for kw in get_active_profile().rag_keywords}


class InputGuardrail:
    """Validates incoming user messages before they reach the agent."""

    def __init__(self, config: GuardrailConfig | None = None):
        self._config = config or GuardrailConfig()

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_length(self, message: str) -> GuardrailResult:
        """BLOCK messages that exceed the configured length limit."""
        if len(message) > self._config.max_input_length:
            log.warning(
                f"InputGuardrail: message length {len(message)} exceeds "
                f"limit {self._config.max_input_length}"
            )
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                reason=f"输入长度({len(message)})超过限制({self._config.max_input_length})",
                confidence=1.0,
            )
        return GuardrailResult(action=GuardrailAction.ALLOW)

    def _check_injection(self, message: str) -> GuardrailResult:
        """BLOCK messages matching known prompt-injection patterns."""
        if not self._config.enable_injection_detection:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        for pattern in INJECTION_PATTERNS:
            match = pattern.search(message)
            if match:
                log.warning(f"InputGuardrail: injection pattern detected: {match.group()!r}")
                return GuardrailResult(
                    action=GuardrailAction.BLOCK,
                    reason=f"检测到潜在注入攻击: {match.group()!r}",
                    confidence=0.9,
                    metadata={"pattern": pattern.pattern},
                )
        return GuardrailResult(action=GuardrailAction.ALLOW)

    def _check_topic(self, message: str) -> GuardrailResult:
        """
        Validate that the message is at least loosely related to the active
        domain (per the profile's topic keywords). Ambiguous messages are
        ALLOWed; only clearly manipulative off-topic prompts are BLOCKed.

        When the active profile has no domain keywords (e.g. the general
        profile), this check allows everything through — topic gating is a
        domain-specific hardening, not a universal requirement.
        """
        if not self._config.enable_topic_check:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        keywords = _topic_keywords()
        # No domain keywords configured -> do not gate on vocabulary.
        if not keywords:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        lower = message.lower()

        # Check for topic overlap
        keyword_hits = sum(1 for kw in keywords if kw in lower)

        if keyword_hits > 0:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        # If the message also triggered injection patterns earlier it will
        # already be BLOCKed.  Here we only block clearly off-topic messages
        # that are also short and look like an attempt to redirect the system.
        # Ambiguous / casual questions are allowed through.
        manipulation_markers = {"hack", "exploit", "bypass", "绕过", "破解"}
        if any(m in lower for m in manipulation_markers):
            log.warning("InputGuardrail: off-topic with manipulation marker detected")
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                reason="话题超出系统范围且含有操控意图",
                confidence=0.7,
            )

        # Default: allow -- the safety / injection checks are the hard gate.
        return GuardrailResult(action=GuardrailAction.ALLOW)

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def validate(self, message: str) -> GuardrailResult:
        """Run all input checks in sequence; return the most restrictive result."""
        checks = [
            self._check_length(message),
            self._check_injection(message),
            self._check_topic(message),
        ]

        # If any check returns BLOCK, surface that immediately.
        for result in checks:
            if result.action == GuardrailAction.BLOCK:
                log.info(f"InputGuardrail: blocked input - {result.reason}")
                return result

        return GuardrailResult(action=GuardrailAction.ALLOW)
