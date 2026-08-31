"""
Metrics Integration Hooks

Factory functions that create lifecycle hooks for the agent harness.
These hooks automatically extract token usage, costs, and quality signals
from skill results and feed them into the MetricsCollector.
"""

from __future__ import annotations

from collections.abc import Callable

from langchain_core.messages import AIMessage

from agent.metrics.collector import MetricsCollector, get_metrics_collector
from agent.metrics.cost import CostCalculator
from agent.metrics.types import CostRecord, QualitySignal, TokenUsage
from agent.skills.base import SkillContext, SkillResult
from utils.log_utils import log

__all__ = [
    "create_token_tracking_hook",
    "create_quality_tracking_hook",
]


def create_token_tracking_hook(
    collector: MetricsCollector | None = None,
) -> Callable:
    """
    Create an after_skill hook that tracks token usage and costs.

    The hook:
    1. Checks if result.messages contains an AIMessage
    2. Extracts token usage from response_metadata
    3. Records TokenUsage and CostRecord via MetricsCollector

    Args:
        collector: Optional MetricsCollector override. Defaults to the
                   global singleton.

    Returns:
        A callable suitable for LifecycleManager.on_after_skill().
    """
    _collector = collector or get_metrics_collector()
    _cost_calc = CostCalculator()

    def token_tracking_hook(
        skill_name: str,
        context: SkillContext,
        result: SkillResult,
    ) -> None:
        # Find the AIMessage in the result
        ai_message: AIMessage | None = None
        for msg in result.messages:
            if isinstance(msg, AIMessage):
                ai_message = msg
                break

        if ai_message is None:
            return

        # Extract token usage from response_metadata
        metadata = getattr(ai_message, "response_metadata", {}) or {}
        raw_usage = metadata.get("token_usage") or metadata.get("usage") or {}

        if not raw_usage:
            return

        # Build TokenUsage from the raw dict
        prompt_tokens = raw_usage.get("prompt_tokens", 0)
        completion_tokens = raw_usage.get("completion_tokens", 0)
        total_tokens = raw_usage.get("total_tokens", prompt_tokens + completion_tokens)

        # Try to get model name from metadata or usage
        from utils.env_utils import LLM_MODEL

        model_name = metadata.get("model_name", LLM_MODEL)

        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            model_name=model_name,
        )

        # Record token usage
        _collector.record_token_usage(skill_name, usage)

        # Record cost
        cost_usd = _cost_calc.estimate_cost(usage)
        cost_record = CostRecord(
            skill_name=skill_name,
            token_usage=usage,
            estimated_cost_usd=cost_usd,
        )
        _collector.record_cost(cost_record)

        log.debug(f"TokenTracking: {skill_name} recorded {total_tokens} tokens, ${cost_usd:.6f}")

    return token_tracking_hook


def create_quality_tracking_hook(
    collector: MetricsCollector | None = None,
) -> Callable:
    """
    Create an after_skill hook that tracks quality signals.

    Extracts quality signals from result.metadata based on skill type:
    - grade skill: records is_relevant signal (1.0 or 0.0)
    - rewrite skill: records rewrite_attempt signal
    - generate skill: records answer_length and has_reasoning signals

    Args:
        collector: Optional MetricsCollector override. Defaults to the
                   global singleton.

    Returns:
        A callable suitable for LifecycleManager.on_after_skill().
    """
    _collector = collector or get_metrics_collector()

    def quality_tracking_hook(
        skill_name: str,
        context: SkillContext,
        result: SkillResult,
    ) -> None:
        meta = result.metadata or {}

        if skill_name == "grade":
            # Record relevance signal from grade skill
            is_relevant = meta.get("is_relevant")
            if is_relevant is not None:
                _collector.record_quality(
                    QualitySignal(
                        skill_name=skill_name,
                        signal_type="is_relevant",
                        value=1.0 if is_relevant else 0.0,
                    )
                )

        elif skill_name == "rewrite":
            # Record rewrite attempt
            _collector.record_quality(
                QualitySignal(
                    skill_name=skill_name,
                    signal_type="rewrite_attempt",
                    value=1.0,
                )
            )

        elif skill_name == "generate":
            # Record answer length
            answer = meta.get("answer", "")
            if answer:
                _collector.record_quality(
                    QualitySignal(
                        skill_name=skill_name,
                        signal_type="answer_length",
                        value=float(len(answer)),
                    )
                )

            # Record whether reasoning was present
            has_reasoning = meta.get("has_reasoning", False)
            _collector.record_quality(
                QualitySignal(
                    skill_name=skill_name,
                    signal_type="has_reasoning",
                    value=1.0 if has_reasoning else 0.0,
                )
            )

    return quality_tracking_hook
