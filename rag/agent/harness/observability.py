"""
Observability

Provides skill-level tracing, timing, and event recording
for the agent harness. Records a trace per skill execution
that can be collected for debugging, metrics, or logging.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from utils.log_utils import log

__all__ = [
    "SkillTrace",
    "TraceCollector",
]


@dataclass
class SkillTrace:
    """
    A single trace record for one skill execution.

    Records timing, status, and metadata for observability.
    """

    skill_name: str
    start_time: float
    end_time: float = 0.0
    duration_ms: float = 0.0
    status: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def finish(
        self,
        status: str,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Finalize the trace with timing and status."""
        self.end_time = time.perf_counter()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.status = status
        self.error = error
        if metadata:
            self.metadata.update(metadata)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a plain dict for serialization."""
        return {
            "skill_name": self.skill_name,
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status,
            "error": self.error,
            "metadata": self.metadata,
        }


class TraceCollector:
    """
    Collects SkillTrace records across a single agent run.

    Used by the orchestrator to record every skill execution
    and provide a summary at the end of the run.

    Example:
        >>> collector = TraceCollector()
        >>> trace = collector.begin("agent")
        >>> # ... skill executes ...
        >>> trace.finish("success")
        >>> summary = collector.summary()
    """

    def __init__(self):
        self._traces: list[SkillTrace] = []
        self._run_start: float = 0.0
        self._run_end: float = 0.0

    # ------------------------------------------------------------------
    # Trace lifecycle
    # ------------------------------------------------------------------

    def begin_run(self) -> None:
        """Mark the start of an agent run."""
        self._traces.clear()
        self._run_start = time.perf_counter()
        self._run_end = 0.0

    def end_run(self) -> None:
        """Mark the end of an agent run."""
        self._run_end = time.perf_counter()

    def begin(self, skill_name: str) -> SkillTrace:
        """
        Begin a new skill trace.

        Args:
            skill_name: Name of the skill about to execute

        Returns:
            SkillTrace to be finished later
        """
        trace = SkillTrace(
            skill_name=skill_name,
            start_time=time.perf_counter(),
        )
        self._traces.append(trace)
        return trace

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    @property
    def traces(self) -> list[SkillTrace]:
        """Get all recorded traces."""
        return list(self._traces)

    @property
    def total_duration_ms(self) -> float:
        """Total run duration in milliseconds."""
        if self._run_end > 0:
            return (self._run_end - self._run_start) * 1000
        return 0.0

    def summary(self) -> dict[str, Any]:
        """
        Get a summary of all traces in this run.

        Returns:
            Dict with total_time, skill_count, skills list, and any errors.
        """
        skill_summaries = [t.to_dict() for t in self._traces]
        errors = [t.to_dict() for t in self._traces if t.status == "failure"]

        return {
            "total_duration_ms": round(self.total_duration_ms, 2),
            "skill_count": len(self._traces),
            "skills": skill_summaries,
            "errors": errors,
            "success": len(errors) == 0,
        }

    def get_skill_trace(self, skill_name: str) -> SkillTrace | None:
        """Get the last trace for a given skill name."""
        for trace in reversed(self._traces):
            if trace.skill_name == skill_name:
                return trace
        return None

    # ------------------------------------------------------------------
    # Logging integration
    # ------------------------------------------------------------------

    def log_summary(self) -> None:
        """Log a summary of the run."""
        s = self.summary()
        log.info(
            f"Trace summary: {s['skill_count']} skills, "
            f"{s['total_duration_ms']:.0f}ms total, "
            f"success={s['success']}"
        )
        for skill in s["skills"]:
            log.debug(
                f"  {skill['skill_name']}: {skill['duration_ms']:.0f}ms, status={skill['status']}"
            )


# ------------------------------------------------------------------
# Module-level convenience
# ------------------------------------------------------------------

_global_collector: TraceCollector | None = None


def get_trace_collector() -> TraceCollector:
    """Get or create the global trace collector."""
    global _global_collector
    if _global_collector is None:
        _global_collector = TraceCollector()
    return _global_collector
