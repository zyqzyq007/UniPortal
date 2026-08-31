from __future__ import annotations

import re

from agent.guardrails.prompts import SAFETY_DISCLAIMER
from agent.guardrails.types import GuardrailAction, GuardrailConfig, GuardrailResult
from utils.log_utils import log


class OutputGuardrail:
    """Validates and post-processes agent responses before they reach the user."""

    def __init__(self, config: GuardrailConfig | None = None):
        self._config = config or GuardrailConfig()

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_safety_disclaimer(self, answer: str) -> GuardrailResult:
        """Ensure the answer carries a safety disclaimer when appropriate."""
        if not self._config.enable_safety_check:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        # If the answer already mentions risk or a safety note, it is fine.
        if "风险" in answer or "安全提示" in answer or "仅供参考" in answer:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        # Append the disclaimer via SANITIZE.
        return GuardrailResult(
            action=GuardrailAction.SANITIZE,
            reason="缺少安全免责声明",
            sanitized_content=answer + SAFETY_DISCLAIMER,
            confidence=1.0,
        )

    def _check_structure(self, answer: str) -> GuardrailResult:
        """
        Check that substantive answers (> 50 chars) follow the expected
        structured format for the active domain.

        The expected section markers come from the domain profile's
        ``section_template``; when the profile defines no sections (e.g. the
        general profile), this check is a no-op (free-form answers are fine).
        """
        if not self._config.enable_structure_check:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        from core.prompts.domain_profile import get_active_profile

        profile = get_active_profile()
        sections = profile.section_template
        # No section template -> do not enforce structure (general profile).
        if not sections:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        if len(answer) <= 50:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        # An answer is "structured" if it contains the leading section marker.
        has_conclusion = any(f"【{s}】" in answer or s in answer for s in sections[:2])

        # Truncation signal (Stage C, REQ-RC-007): if the answer has a leading
        # section but is missing the *last* sections (信息缺口/依据来源), it was
        # likely cut mid-generation. Append the structure hint so the user sees
        # the expected completion and the gap is visible (was: leading-only check
        # let truncated answers pass silently).
        last_sections = sections[-2:] if len(sections) >= 2 else sections
        has_completion = any(f"【{s}】" in answer or s in answer for s in last_sections)

        if has_conclusion and has_completion:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        if has_conclusion and not has_completion:
            # Leading section present but ending missing -> truncated; nudge.
            hint = profile.structure_hint
            if hint:
                return GuardrailResult(
                    action=GuardrailAction.SANITIZE,
                    reason="回答疑似被截断(缺少末段结构)",
                    sanitized_content=answer + hint,
                    confidence=0.7,
                )
            return GuardrailResult(action=GuardrailAction.ALLOW)

        # Short / unstructured answer -- append the profile's structure hint
        # (empty hint => no append, just allow).
        hint = profile.structure_hint
        if not hint:
            return GuardrailResult(action=GuardrailAction.ALLOW)
        return GuardrailResult(
            action=GuardrailAction.SANITIZE,
            reason="回答缺少结构化内容",
            sanitized_content=answer + hint,
            confidence=0.8,
        )

    def _check_hallucination(
        self,
        answer: str,
        sources: list[str] | None = None,
        contexts: list[str] | None = None,
        cached_faith: float | None = None,
    ) -> GuardrailResult:
        """
        Verify the answer is grounded in the retrieved evidence.

        Two modes, in priority order:
          1. Semantic grounding (NLI) — when ``contexts`` are available and
             ``enable_grounding_check`` is on, reuse the eval LLMJudge to check
             that the answer's hard claims are entailed by the contexts. This
             is the trustworthy path. When ``cached_faith`` is provided (the
             generate skill already ran the judge), it is used directly instead
             of re-invoking the judge — avoids a duplicate per-claim round trip.
          2. Legacy regex check — falls back when grounding is disabled or the
             judge is unavailable. Compares cited source names against the
             actual sources list (best-effort substring match).
        """
        if not self._config.enable_hallucination_check:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        # --- Mode 1: semantic grounding (NLI) ---
        if self._config.enable_grounding_check and (contexts or cached_faith is not None):
            try:
                # Use the cached verdict when available; otherwise compute it.
                supported = total = None
                if cached_faith is not None:
                    faith = cached_faith
                    meta = {"grounding": {"faithfulness": faith, "cached": True}}
                else:
                    from agent.guardrails.grounding_guardrail import check_grounding

                    result = check_grounding(answer, contexts or [])
                    if not result.available:
                        # judge unavailable — fall through to regex.
                        raise RuntimeError("grounding degraded")
                    faith = result.faithfulness
                    supported, total = result.supported, result.total
                    meta = {"grounding": result.to_dict()}

                if faith <= self._config.grounding_escalate_threshold:
                    # Fully unsupported hard claims — escalate.
                    detail = f" ({supported}/{total} grounded)" if supported is not None else ""
                    return GuardrailResult(
                        action=GuardrailAction.ESCALATE,
                        reason=(f"答案硬声明未经检索内容支持 (faithfulness={faith:.2f}{detail})"),
                        confidence=0.8,
                        metadata=meta,
                    )
                if faith < self._config.grounding_threshold:
                    # Partially unsupported — append a caveat.
                    caveat = (
                        "\n\n> ⚠️ 提示：本回答部分结论未经知识库直接验证，请核对原始资料后再行决策。"
                    )
                    return GuardrailResult(
                        action=GuardrailAction.SANITIZE,
                        reason=(f"部分硬声明未经支持 (faithfulness={faith:.2f})"),
                        sanitized_content=answer + caveat,
                        confidence=0.7,
                        metadata=meta,
                    )
                # Well grounded.
                return GuardrailResult(
                    action=GuardrailAction.ALLOW,
                    metadata=meta,
                )
            except Exception as e:  # noqa: BLE001 - never block on grounding
                log.debug(f"Grounding check unavailable, falling back to regex: {e}")

        # --- Mode 2: legacy regex check (fallback) ---
        # If no sources provided, we cannot verify -- allow through.
        if not sources:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        # Extract the "依据来源" / "参考" / "引用" section from the answer.
        source_section = ""
        for marker in ("依据来源", "参考来源", "参考资料", "引用"):
            idx = answer.find(marker)
            if idx != -1:
                source_section = answer[idx:]
                break

        if not source_section:
            # No source section at all -- not a hallucination concern.
            return GuardrailResult(action=GuardrailAction.ALLOW)

        # Check whether any source mentioned in the answer is NOT in the
        # actual sources list.  We do a loose substring check.
        mismatched = []
        # Extract potential source references (e.g. document names / IDs).
        # Simple heuristic: look for quoted strings or bracketed references.
        cited_refs = re.findall(r"[《\[](.*?)[》\]]", source_section)
        if not cited_refs:
            cited_refs = re.findall(r"来源[：:]\s*(.+?)(?:\n|$)", source_section)

        for cited in cited_refs:
            cited_lower = cited.strip().lower()
            if not any(cited_lower in src.lower() or src.lower() in cited_lower for src in sources):
                mismatched.append(cited)

        if mismatched:
            log.warning(
                f"OutputGuardrail: potential hallucination - mismatched sources: {mismatched}"
            )
            return GuardrailResult(
                action=GuardrailAction.ESCALATE,
                reason=f"回答引用了不存在的来源: {mismatched}",
                confidence=0.7,
                metadata={"mismatched_sources": mismatched},
            )

        return GuardrailResult(action=GuardrailAction.ALLOW)

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def validate(
        self,
        answer: str,
        sources: list[str] | None = None,
        contexts: list[str] | None = None,
        cached_faith: float | None = None,
    ) -> GuardrailResult:
        """Run all output checks in sequence; return the most restrictive result."""
        # Priority order: BLOCK > ESCALATE > SANITIZE > ALLOW
        worst = GuardrailResult(action=GuardrailAction.ALLOW)

        # 1. Hallucination check (can produce ESCALATE)
        result = self._check_hallucination(
            answer, sources, contexts=contexts, cached_faith=cached_faith
        )
        if result.action == GuardrailAction.ESCALATE:
            worst = result
        elif result.action.value > worst.action.value:
            worst = result

        # 2. Safety disclaimer (can produce SANITIZE)
        result = self._check_safety_disclaimer(answer)
        if result.action == GuardrailAction.SANITIZE and worst.action == GuardrailAction.ALLOW:
            worst = result
            answer = result.sanitized_content or answer  # use sanitized for subsequent checks

        # 3. Structure check (can produce SANITIZE -- use potentially sanitized content)
        result = self._check_structure(answer)
        if result.action == GuardrailAction.SANITIZE and worst.action == GuardrailAction.ALLOW:
            worst = result

        # 4. PII redaction (P3.1): redact any PII in the answer before it
        #    reaches the user. Composes with the worst action found so far
        #    rather than pre-empting it: a hallucinated answer (ESCALATE) that
        #    also contains PII must STAY ESCALATE *and* be redacted, so the
        #    served/escalated text never leaks the PII. Previously this branch
        #    returned early and silently discarded an ESCALATE verdict.
        if self._config.enable_pii_check:
            from agent.guardrails.pii import detect_pii, redact_pii

            pii_matches = detect_pii(answer)
            if pii_matches:
                redacted = redact_pii(answer)
                log.info(
                    f"OutputGuardrail: redacting {len(pii_matches)} PII "
                    f"({', '.join(m.kind for m in pii_matches)})"
                )
                # Attach the redacted content + PII metadata to whichever action
                # was worst so far. ESCALATE stays ESCALATE (the safety signal
                # is preserved) but carries the redacted payload; SANITIZE/ALLOW
                # are promoted to a SANITIZE carrying the redacted text. Either
                # way the consumer applies `sanitized_content` to the served
                # message (see GuardrailManager.create_after_hook).
                pii_meta = {"pii": [m.kind for m in pii_matches]}
                if worst.action == GuardrailAction.ESCALATE:
                    worst.sanitized_content = redacted
                    worst.metadata = {**worst.metadata, **pii_meta}
                else:
                    worst = GuardrailResult(
                        action=GuardrailAction.SANITIZE,
                        reason=f"redacted {len(pii_matches)} PII occurrence(s)",
                        sanitized_content=redacted,
                        confidence=1.0,
                        metadata=pii_meta,
                    )
                answer = redacted  # downstream checks see the redacted text

        if worst.action != GuardrailAction.ALLOW:
            log.info(f"OutputGuardrail: {worst.action.value} - {worst.reason}")

        return worst
