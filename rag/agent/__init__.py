"""
Agent Module - Industrial-grade Agent Architecture

Provides Harness + Skills + MCP architecture for the RAG platform.

Layer structure:
- agent.skills:  BaseSkill, SkillRegistry, and all concrete skills
- agent.context: SkillContext, SkillResult, SkillStatus
- agent.mcp:     MCPServer, MCPRetrievalServer, MCPClient
- agent.harness: AgentHarness, Planner, LifecycleManager, TraceCollector
"""

from agent.skills.base import BaseSkill, SkillContext, SkillResult, SkillStatus
from agent.skills.registry import SkillRegistry

__all__ = [
    "BaseSkill",
    "SkillContext",
    "SkillResult",
    "SkillStatus",
    "SkillRegistry",
]


# Lazy import to avoid circular dependencies
def __getattr__(name: str):
    if name == "AgentHarness":
        from agent.harness.orchestrator import AgentHarness

        return AgentHarness
    if name == "HarnessConfig":
        from agent.harness.orchestrator import HarnessConfig

        return HarnessConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
