from __future__ import annotations

from collections.abc import Callable

from agent.guardrails.input_guardrails import InputGuardrail
from agent.guardrails.output_guardrails import OutputGuardrail
from agent.guardrails.types import GuardrailAction, GuardrailConfig, GuardrailResult
from utils.log_utils import log


class GuardrailBlockError(Exception):
    """Raised when an input guardrail blocks a message."""


class GuardrailManager:
    """
    Central facade for the guardrail subsystem.

    Provides:
    - ``check_input`` / ``check_output`` for explicit guardrail calls.
    - ``create_before_hook`` / ``create_after_hook`` for integration with the
      agent harness lifecycle.
    """

    def __init__(self, config: GuardrailConfig | None = None):
        self._config = config or GuardrailConfig()
        self._input = InputGuardrail(self._config)
        self._output = OutputGuardrail(self._config)

    # ------------------------------------------------------------------
    # Direct API
    # ------------------------------------------------------------------

    def check_input(self, message: str) -> GuardrailResult:
        """Validate a user message.  Returns the check result."""
        return self._input.validate(message)

    def check_output(
        self,
        answer: str,
        sources: list[str] | None = None,
        contexts: list[str] | None = None,
        cached_faith: float | None = None,
    ) -> GuardrailResult:
        """Validate an agent response.  Returns the check result.

        ``cached_faith`` is an optional grounding-faithfulness fraction that
        was already computed upstream (by the generate skill). When provided it
        short-circuits the semantic grounding check so the judge is not invoked
        a second time on the hot path.
        """
        return self._output.validate(answer, sources, contexts=contexts, cached_faith=cached_faith)

    # ------------------------------------------------------------------
    # Harness hook factories
    # ------------------------------------------------------------------

    def create_before_hook(self) -> Callable:
        """
        Return a ``before`` hook compatible with the harness lifecycle.

        Signature: ``(skill_name: str, context: SkillContext) -> None``

        Raises ``GuardrailBlockError`` when the input is blocked.
        """

        def _before_hook(skill_name: str, context) -> None:  # type: ignore[annots]
            # Extract last human message
            last_human = None
            for msg in reversed(context.messages):
                if hasattr(msg, "type") and msg.type == "human":
                    last_human = msg
                    break
                # LangChain HumanMessage
                if msg.__class__.__name__ == "HumanMessage":
                    last_human = msg
                    break

            if last_human is None:
                return

            content = last_human.content if hasattr(last_human, "content") else str(last_human)
            result = self.check_input(content)

            if result.action == GuardrailAction.BLOCK:
                log.warning(
                    f"GuardrailManager: blocked input for skill '{skill_name}' - {result.reason}"
                )
                raise GuardrailBlockError(result.reason)

        return _before_hook

    def create_after_hook(self) -> Callable:
        """
        Return an ``after`` hook compatible with the harness lifecycle.

        Signature: ``(skill_name: str, context, result: SkillResult) -> None``

        Only activates when ``skill_name == "generate"``.
        - SANITIZE: modifies ``result.messages[-1].content`` in-place.
        - ESCALATE: attaches metadata to ``result``.
        """

        def _after_hook(skill_name: str, context, result) -> None:  # type: ignore[annots]
            if skill_name != "generate":
                return

            if not result or not result.messages:
                return

            last_msg = result.messages[-1]
            content = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

            # Gather sources (names) and contexts (actual chunk text) from
            # shared_state. contexts enable the semantic grounding check.
            sources: list[str] | None = None
            contexts: list[str] | None = None
            if hasattr(context, "shared_state"):
                sources = context.shared_state.get("sources")
                contexts = context.shared_state.get("retrieved_contexts")
            # The generate skill already computed grounding faithfulness via the
            # same judge; reuse it to avoid a duplicate per-claim judge round
            # trip on the hot path.
            cached_faith = None
            if hasattr(context, "shared_state"):
                cached_faith = context.shared_state.get("grounding_faithfulness")

            guard_result = self.check_output(
                content, sources, contexts=contexts, cached_faith=cached_faith
            )

            if guard_result.action == GuardrailAction.SANITIZE:
                if guard_result.sanitized_content is not None:
                    log.info(f"GuardrailManager: sanitizing output - {guard_result.reason}")
                    last_msg.content = guard_result.sanitized_content
                # Persist grounding metadata onto the result for confidence calc.
                if hasattr(result, "metadata") and "grounding" in guard_result.metadata:
                    result.metadata["grounding"] = guard_result.metadata["grounding"]

            elif guard_result.action == GuardrailAction.ESCALATE:
                log.warning(f"GuardrailManager: escalating output - {guard_result.reason}")
                # If the verdict also carries redacted content (e.g. an ESCALATE
                # hallucination that contained PII), apply the redaction to the
                # served message so raw PII is never delivered on the escalation
                # path either. Composes with ESCALATE rather than replacing it.
                if guard_result.sanitized_content is not None and hasattr(last_msg, "content"):
                    last_msg.content = guard_result.sanitized_content
                if hasattr(result, "metadata"):
                    result.metadata["guardrail_escalation"] = {
                        "reason": guard_result.reason,
                        "confidence": guard_result.confidence,
                        **guard_result.metadata,
                    }

        return _after_hook
