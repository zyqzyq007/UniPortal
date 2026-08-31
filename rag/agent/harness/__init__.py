"""
Agent Harness Package

Provides the orchestration layer:
- AgentHarness: Main orchestrator that builds graphs and executes skills
- HarnessConfig: Configuration for the harness
- Planner: Determines execution plan (thinking vs fast)
- LifecycleManager: Hook system for before/after/error events
- TraceCollector: Skill-level observability and timing
"""

from agent.harness.lifecycle import HookType, LifecycleHook, LifecycleManager
from agent.harness.observability import SkillTrace, TraceCollector
from agent.harness.orchestrator import AgentHarness, HarnessConfig
from agent.harness.planner import ExecutionPlan, Planner, PlanType

__all__ = [
    "AgentHarness",
    "HarnessConfig",
    "Planner",
    "ExecutionPlan",
    "PlanType",
    "LifecycleManager",
    "LifecycleHook",
    "HookType",
    "TraceCollector",
    "SkillTrace",
    "get_agent_harness",
]

# Module-level singleton
_harness: AgentHarness | None = None


def get_agent_harness(config: HarnessConfig | None = None) -> AgentHarness:
    """Get or create the singleton AgentHarness with default skills and hooks."""
    global _harness
    if _harness is None or config is not None:
        _harness = AgentHarness(config=config)
        _harness.register_defaults()

        # Register lifecycle hooks from all modules
        _register_hooks(_harness)
    return _harness


def _register_hooks(harness: AgentHarness) -> None:
    """Register all lifecycle hooks for guardrails, metrics, memory, and escalation."""
    lc = harness.lifecycle

    # Guardrails (priority 1 = runs first)
    try:
        from agent.guardrails import GuardrailManager

        gm = GuardrailManager()
        lc.on_before_skill(gm.create_before_hook(), name="guardrail_input", priority=1)
        lc.on_after_skill(gm.create_after_hook(), name="guardrail_output", priority=1)
    except Exception as e:
        from utils.log_utils import log

        log.warning(f"Guardrail hooks not registered: {e}")

    # Metrics (token tracking + quality signals)
    try:
        from agent.metrics.integration import (
            create_quality_tracking_hook,
            create_token_tracking_hook,
        )

        lc.on_after_skill(create_token_tracking_hook(), name="metrics_tokens", priority=50)
        lc.on_after_skill(create_quality_tracking_hook(), name="metrics_quality", priority=50)
    except Exception as e:
        from utils.log_utils import log

        log.warning(f"Metrics hooks not registered: {e}")

    # Memory (store facts after generate, enrich context before agent)
    try:
        from agent.memory.lifecycle import (
            create_memory_enrichment_hook,
            create_memory_store_hook,
        )

        lc.on_after_skill(create_memory_store_hook(), name="memory_store", priority=80)
        lc.on_before_skill(create_memory_enrichment_hook(), name="memory_enrich", priority=80)
    except Exception as e:
        from utils.log_utils import log

        log.warning(f"Memory hooks not registered: {e}")

    # Escalation (confidence-based)
    try:
        from agent.feedback.lifecycle import create_escalation_hook

        lc.on_after_skill(create_escalation_hook(), name="escalation", priority=90)
    except Exception as e:
        from utils.log_utils import log

        log.warning(f"Escalation hooks not registered: {e}")
