#!/usr/bin/env python3
"""
Skill smoke tests.

Usage:
    python tests/test_skills.py              # Run all skill tests
    python tests/test_skills.py agent        # Test single skill
    python tests/test_skills.py --full       # Include LLM-invoking tests
"""

from __future__ import annotations

import os
import sys
import time

# Add project root to path
sys.path.insert(0, ".")


def test_registry():
    """Test SkillRegistry."""
    from agent.skills.base import BaseSkill, SkillContext, SkillResult, SkillStatus
    from agent.skills.registry import SkillRegistry

    registry = SkillRegistry()
    assert registry.list_skills() == []

    class DummySkill(BaseSkill):
        name = "dummy"
        description = "test skill"

        def execute(self, ctx):
            return SkillResult(status=SkillStatus.SUCCESS)

        async def aexecute(self, ctx):
            return SkillResult(status=SkillStatus.SUCCESS)

    registry.register(DummySkill())
    assert "dummy" in registry.list_skills()
    assert registry.get("dummy") is not None
    assert registry.get("nonexistent") is None

    print("  [PASS] registry")


def test_state():
    """Test AgentState and Grade."""
    from langchain_core.messages import HumanMessage

    from agent.context.state import AgentState, Grade, get_last_human_message

    # Grade
    g = Grade(binary_score="yes")
    assert g.is_relevant is True
    g2 = Grade(binary_score="no")
    assert g2.is_relevant is False
    g3 = Grade(binary_score="yes", answer="no")
    assert g3.is_relevant is True  # binary_score takes priority

    # get_last_human_message
    msgs = [HumanMessage(content="hello"), HumanMessage(content="world")]
    assert get_last_human_message(msgs).content == "world"

    print("  [PASS] state")


def test_context():
    """Test SkillContext."""
    from langchain_core.messages import HumanMessage

    from agent.skills.base import SkillContext

    ctx = SkillContext(
        messages=[HumanMessage(content="test")],
        session_id="s1",
        thread_id="t1",
        rewrite_count=0,
        max_rewrites=3,
    )
    assert ctx.messages[0].content == "test"
    assert ctx.is_rewrite_limit_reached is False

    ctx2 = SkillContext(
        messages=[],
        session_id="s2",
        thread_id="t2",
        rewrite_count=3,
        max_rewrites=3,
    )
    assert ctx2.is_rewrite_limit_reached is True

    print("  [PASS] context")


def test_harness_build():
    """Test AgentHarness graph construction."""
    from agent.harness import AgentHarness, HarnessConfig

    config = HarnessConfig(use_memory=False)
    harness = AgentHarness(config=config)
    harness.register_defaults()

    g = harness.graph
    assert "__start__" in g.nodes
    assert "agent" in g.nodes
    assert "retrieve" in g.nodes
    assert "generate" in g.nodes
    assert "rewrite" in g.nodes

    harness.close()
    print("  [PASS] harness_build")


def test_mcp_server():
    """Test MCPServer tool registration and LangChain conversion."""
    from agent.mcp.server import MCPServer, MCPServerConfig

    server = MCPServer()
    server.register_tool(
        name="test_tool",
        description="A test tool",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "query"}},
            "required": ["query"],
        },
        handler=lambda query: f"result: {query}",
    )

    tools = server.list_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "test_tool"

    lc_tools = server.get_tools_as_langchain()
    assert len(lc_tools) == 1
    assert lc_tools[0].name == "test_tool"

    print("  [PASS] mcp_server")


def test_mcp_retrieval_server():
    """Test MCPRetrievalServer registration."""
    from agent.mcp.retrieval_server import MCPRetrievalServer

    server = MCPRetrievalServer()
    tools = server.list_tools()
    assert len(tools) == 3
    names = {t["name"] for t in tools}
    assert "rag_retrieve" in names
    assert "rag_search_dense" in names
    assert "rag_search_sparse" in names

    print("  [PASS] mcp_retrieval_server")


# -- Full tests (require LLM) --
#
# These hit a live Ollama instance and the singleton harness's real SQLite
# checkpointer. They are skipped by default (the default unit suite has no
# Ollama and must not depend on / mutate singleton state). Run them explicitly
# against a live backend: ``pytest tests/unit/test_skills.py -m requires_ollama``
import pytest

try:
    pytest.importorskip  # noqa: B018 — marker availability sanity
except Exception:  # pragma: no cover
    pass

_requires_ollama = pytest.mark.requires_ollama
_ollama_available = bool(os.environ.get("OLLAMA_FULL_TESTS"))


@_requires_ollama
@pytest.mark.skipif(not _ollama_available, reason="needs OLLAMA_FULL_TESTS=1 and a live Ollama")
def test_full_thinking():
    """Full thinking mode test (requires Ollama)."""
    from agent.harness import get_agent_harness

    harness = get_agent_harness()
    result = harness.invoke("测试问题", mode="thinking")
    messages = result.get("messages", [])
    assert len(messages) > 0
    assert messages[-1].content

    harness.close()
    print(f"  [PASS] full_thinking ({len(messages)} messages)")


@_requires_ollama
@pytest.mark.skipif(not _ollama_available, reason="needs OLLAMA_FULL_TESTS=1 and a live Ollama")
def test_full_fast():
    """Full fast mode test (requires Ollama)."""
    from agent.harness import get_agent_harness

    harness = get_agent_harness()
    result = harness.invoke_fast("测试问题")
    assert result.get("_fast_mode") is True
    assert result["messages"][-1].content

    harness.close()
    print(f"  [PASS] full_fast ({len(result['messages'])} messages)")


if __name__ == "__main__":
    full = "--full" in sys.argv
    single = None
    for arg in sys.argv[1:]:
        if not arg.startswith("--"):
            single = arg

    tests = {
        "registry": test_registry,
        "state": test_state,
        "context": test_context,
        "harness_build": test_harness_build,
        "mcp_server": test_mcp_server,
        "mcp_retrieval_server": test_mcp_retrieval_server,
    }
    full_tests = {
        "full_thinking": test_full_thinking,
        "full_fast": test_full_fast,
    }

    if full:
        tests.update(full_tests)

    if single:
        if single in tests:
            tests = {single: tests[single]}
        else:
            print(f"Unknown test: {single}")
            sys.exit(1)

    print("Running skill tests...\n")
    passed = 0
    failed = 0
    for name, fn in tests.items():
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
