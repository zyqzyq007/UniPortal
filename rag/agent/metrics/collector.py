"""
Metrics Collector

Central collector for token usage, costs, and quality signals emitted during
skill execution. Provides the WRITE side consumed by
``agent/metrics/integration.py`` (which hooks skill results into the collector).

NOTE: this collector previously also exposed read/aggregation APIs
(``get_run_metrics`` / ``reset_run`` / ``get_cumulative_stats``) plus cumulative
counters, but they had ZERO callers — nothing ever read the collected data, so
``reset_run`` never ran and cumulative counters stayed at zero forever (a
metrics write-black-hole). Those dead read APIs and cumulative counters have
been removed for honesty. The recording methods remain (they log at debug); if
a metrics consumer (e.g. an admin /metrics endpoint) is added later, reintroduce
a read API together with its integration point — do not add a reader without a
caller.
"""

from __future__ import annotations

from agent.metrics.types import CostRecord, QualitySignal, TokenUsage
from utils.log_utils import log

__all__ = ["MetricsCollector", "get_metrics_collector"]


class MetricsCollector:
    """
    Collects token usage, costs, quality signals, and per-skill durations during
    skill execution. Recording is live (driven by ``integration.py``); read-out
    is intentionally absent until a consumer is wired.
    """

    def __init__(self) -> None:
        self._run_tokens: int = 0
        self._run_cost: float = 0.0
        self._run_quality_signals: list[QualitySignal] = []
        self._run_skill_durations: dict[str, float] = {}
        self._cost_records: list[CostRecord] = []

    # ------------------------------------------------------------------
    # Recording (used by agent/metrics/integration.py)
    # ------------------------------------------------------------------

    def record_token_usage(self, skill_name: str, usage: TokenUsage) -> None:
        """Record token usage for a skill. Accumulates into run totals."""
        self._run_tokens += usage.total_tokens
        log.debug(
            f"Metrics: {skill_name} used {usage.total_tokens} tokens "
            f"(prompt={usage.prompt_tokens}, completion={usage.completion_tokens})"
        )

    def record_cost(self, record: CostRecord) -> None:
        """Store a cost record. Accumulates into run totals."""
        self._run_cost += record.estimated_cost_usd
        self._cost_records.append(record)
        log.debug(f"Metrics: {record.skill_name} cost ${record.estimated_cost_usd:.6f}")

    def record_quality(self, signal: QualitySignal) -> None:
        """Append a quality signal to the current run."""
        self._run_quality_signals.append(signal)
        log.debug(
            f"Metrics: {signal.skill_name} quality signal {signal.signal_type}={signal.value}"
        )

    def record_duration(self, skill_name: str, duration_ms: float) -> None:
        """Store per-skill execution timing for the current run."""
        self._run_skill_durations[skill_name] = duration_ms
        log.debug(f"Metrics: {skill_name} took {duration_ms:.1f}ms")


# ----------------------------------------------------------------------
# Module-level singleton
# ----------------------------------------------------------------------

_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """Get or create the global MetricsCollector singleton."""
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector
