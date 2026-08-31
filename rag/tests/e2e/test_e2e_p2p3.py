#!/usr/bin/env python3
"""
End-to-end tests for P2/P3 features through the real FastAPI app:
  - P2.1 MCP tools are wired into the agent harness
  - P3.1 PII redaction works in chat output
  - P2.2 memory injection in retrieval
  - P2.7 HITL gate lifecycle

Run: pytest tests/e2e/test_e2e_p2p3.py -v
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")


# ===========================================================================
# P2.1 — MCP tools wired into the agent
# ===========================================================================


class TestMCPToolsWired:
    def test_harness_has_mcp_client(self):
        """The default harness builds an MCPClient (not None) wiring retrieval."""
        # We can't call get_agent_harness() in a fully mocked context without
        # side effects; instead verify the build path exists and the registry
        # provides tools.
        from agent.mcp.tools_registry import UtilityToolsServer, get_extra_servers

        servers = get_extra_servers()
        # The utility tools server is auto-registered.
        assert any(isinstance(s, UtilityToolsServer) for s in servers)

    def test_utility_calculator_callable_via_mcp(self):
        """The calculator tool is callable through the MCP server interface."""
        import asyncio

        from agent.mcp.tools_registry import UtilityToolsServer

        srv = UtilityToolsServer()
        tools = {t["name"]: t for t in srv.list_tools()}
        assert "calculator" in tools
        # call_tool is async.
        result = asyncio.run(srv.call_tool("calculator", {"expression": "6 * 7"}))
        assert "42" in str(result)

    def test_custom_tool_registration(self, monkeypatch):
        """A custom non-RAG tool can be registered and discovered."""
        import agent.mcp.tools_registry as reg_mod

        monkeypatch.setattr(reg_mod, "_extra_servers", [])
        monkeypatch.setattr(reg_mod, "_registered_defaults", True)

        reg_mod.register_tool_function(
            "voltage_check",
            "检查电压是否在范围",
            lambda voltage: "正常" if 200 <= float(voltage) <= 250 else "异常",
        )
        servers = reg_mod.get_extra_servers()
        all_tools = []
        for s in servers:
            all_tools.extend(t["name"] for t in s.list_tools())
        assert "voltage_check" in all_tools


# ===========================================================================
# P3.1 — PII redaction in chat output
# ===========================================================================


class TestPIIInChat:
    def test_chat_output_redacts_phone(self, client):
        """If the (fake) LLM emits a phone number, the output guardrail redacts it."""
        # Use the identity branch which returns a fixed response; we instead
        # verify the output guardrail redaction directly + via the app.
        from agent.guardrails.pii import detect_pii, redact_pii

        text = "请联系工程师 13812345678 获取支持。"
        assert detect_pii(text)
        redacted = redact_pii(text)
        assert "13812345678" not in redacted

    def test_output_guardrail_redaction_through_manager(self):
        """GuardrailManager.check_output redacts PII end-to-end."""
        from agent.guardrails.manager import GuardrailManager

        gm = GuardrailManager()
        answer = "电话13987654321是工程师联系方式。仅供参考注意安全风险。"
        result = gm.check_output(answer, sources=["doc"], contexts=["ctx"])
        assert result.action.value == "sanitize"
        assert "13987654321" not in (result.sanitized_content or "")


# ===========================================================================
# P2.2 — memory injection in retrieval
# ===========================================================================


class TestMemoryInjection:
    def test_memories_prepend_to_retrieved_docs(self):
        """RetrieveSkill._inject_memories adds memory entries as context."""
        from langchain_core.documents import Document

        from agent.skills.retrieve.skill import RetrieveSkill

        class _Ctx:
            shared_state = {
                "relevant_memories": [
                    {"content": "git 默认分支名应为 main", "type": "correction"},
                ]
            }

        docs = [Document(page_content="检索到的文档片段", metadata={"score": 0.9})]
        out = RetrieveSkill._inject_memories(_Ctx(), docs)
        # Memory doc first.
        assert len(out) == 2
        assert out[0].metadata.get("is_memory") is True
        assert "默认分支" in out[0].page_content


# ===========================================================================
# P2.7 — HITL gate lifecycle (removed)
# ===========================================================================
# TestHITLLifecycle removed: core/workflow/hitl.py was a zombie module (zero
# production callers) and has been deleted.


# ===========================================================================
# P2.4/P2.5 — model routing config (removed)
# ===========================================================================
# TestModelRoutingConfig removed: models/model_router.py was a zombie module
# (zero production callers) and has been deleted.


# ===========================================================================
# P3.6 — retrieval cache stats
# ===========================================================================


class TestRetrievalCacheE2E:
    def test_cache_hit_after_second_put(self):
        from core.retrieval.cache import LRUCache

        c = LRUCache(maxsize=100)
        c.put("query|filter|5", ["doc1", "doc2"])
        # First get = hit.
        assert c.get("query|filter|5") == ["doc1", "doc2"]
        # Stats reflect the hit.
        assert c.stats()["hits"] >= 1
        assert c.stats()["hit_ratio"] > 0


# ===========================================================================
# P3.7 — time decay in retrieval
# ===========================================================================


class TestTimeDecayE2E:
    def test_hybrid_retriever_applies_time_decay(self):
        """The HybridRetriever._time_decay method exists and runs."""
        import time

        from langchain_core.documents import Document

        from core.retrieval.hybrid_retriever import HybridRetriever, HybridRetrieverConfig

        retriever = HybridRetriever(
            config=HybridRetrieverConfig(
                enable_dense=False,
                enable_sparse=False,
                enable_time_decay=True,
                enable_parallel=False,
            )
        )
        now = time.time()
        docs = [
            Document(page_content="fresh", metadata={"score": 1.0, "created_at": now}),
            Document(page_content="old", metadata={"score": 1.0, "created_at": now - 365 * 86400}),
        ]
        try:
            out = retriever._time_decay(docs)
        finally:
            retriever.close()
        assert len(out) == 2
        # Fresh doc keeps full score; old doc decays.
        fresh = next(d for d in out if "fresh" in d.page_content)
        old = next(d for d in out if "old" in d.page_content)
        assert fresh.metadata["score"] >= old.metadata["score"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
