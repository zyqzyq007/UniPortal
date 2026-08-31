#!/usr/bin/env python3
"""
Unit tests for P2 (Agent autonomy) + P3 (Engineering polish) enhancements.

Covers:
  - P2.1/P2.3 MCP tool registry + utility tools
  - P2.2 memory semantic retrieval + injection
  - P2.4/P2.5 model routing + fallback
  - P2.6 self-reflection
  - P2.7 HITL gate + workflow DSL
  - P3.1 PII detection + redaction
  - P3.2 prompt A/B testing
  - P3.3 prompt optimizer
  - P3.4 cancellation
  - P3.6 retrieval cache
  - P3.7 time decay

Run: pytest tests/unit/test_p2p3.py -v
"""

from __future__ import annotations

import sys

import pytest
from langchain_core.documents import Document

sys.path.insert(0, ".")


# ===========================================================================
# P2.1 / P2.3 — MCP tool registry + utility tools
# ===========================================================================


class TestMCPToolRegistry:
    def test_utility_server_registers_calculator(self):
        from agent.mcp.tools_registry import UtilityToolsServer

        srv = UtilityToolsServer()
        tools = srv.list_tools()
        names = [t["name"] for t in tools]
        assert "calculator" in names
        assert "unit_convert" in names

    def test_calculator_basic(self):
        from agent.mcp.tools_registry import UtilityToolsServer

        s = UtilityToolsServer()
        assert s.calculate("2 + 3") == "5"
        assert s.calculate("2 * (3 + 4)") == "14"
        assert s.calculate("sqrt(16)") == "4.0"

    def test_calculator_rejects_injection(self):
        from agent.mcp.tools_registry import UtilityToolsServer

        s = UtilityToolsServer()
        # Disallowed characters => error, not code execution.
        assert "错误" in s.calculate("__import__('os')")

    def test_unit_convert_temperature(self):
        from agent.mcp.tools_registry import UtilityToolsServer

        s = UtilityToolsServer()
        result = s.convert_unit("100℃", "℉")
        assert "212" in result

    def test_unit_convert_length(self):
        from agent.mcp.tools_registry import UtilityToolsServer

        s = UtilityToolsServer()
        result = s.convert_unit("1 m", "cm")
        assert "100" in result

    def test_register_custom_tool_function(self, monkeypatch):
        import agent.mcp.tools_registry as reg_mod

        monkeypatch.setattr(reg_mod, "_extra_servers", [])
        monkeypatch.setattr(reg_mod, "_registered_defaults", True)

        def my_tool(x: str) -> str:
            return f"echo:{x}"

        reg_mod.register_tool_function("echo", "echo tool", my_tool)
        servers = reg_mod.get_extra_servers()
        tool_names = []
        for srv in servers:
            tool_names.extend(t["name"] for t in srv.list_tools())
        assert "echo" in tool_names


# ===========================================================================
# P2.2 — memory semantic retrieval + injection
# ===========================================================================


class TestMemoryInjection:
    def test_inject_memories_prepends(self):
        from agent.skills.retrieve.skill import RetrieveSkill

        class _Ctx:
            shared_state = {
                "relevant_memories": [
                    {"content": "git 默认分支名应为 main", "type": "correction"},
                ]
            }

        docs = [Document(page_content="检索到的文档内容", metadata={"score": 0.8})]
        out = RetrieveSkill._inject_memories(_Ctx(), docs)
        assert len(out) == 2
        # Memory first.
        assert "默认分支" in out[0].page_content
        assert out[0].metadata.get("is_memory") is True

    def test_inject_memories_noop_without_state(self):
        from agent.skills.retrieve.skill import RetrieveSkill

        docs = [Document(page_content="x")]
        assert RetrieveSkill._inject_memories(type("C", (), {"shared_state": None})(), docs) == docs

    def test_memory_store_semantic_fallback_to_like(self, tmp_path, monkeypatch):
        """Semantic retrieve falls back to LIKE when embeddings unavailable."""
        from agent.memory.store import MemoryStore
        from agent.memory.types import MemoryEntry, MemoryQuery

        store = MemoryStore(str(tmp_path / "mem.db"))
        store.store(MemoryEntry(id="m1", content="git 默认分支 main"))
        # retrieve should work (LIKE fallback if no embeddings).
        results = store.retrieve(MemoryQuery(query="分支"))
        assert len(results) >= 1
        store.close()


# ===========================================================================
# P2.4 / P2.5 — model routing + fallback
# ===========================================================================

# TestModelRouter removed: models/model_router.py was a zombie module (zero
# production callers) and has been deleted.


# ===========================================================================
# P2.6 — self-reflection
# ===========================================================================


class TestSelfReflection:
    def test_confident_when_reasoning_consistent(self):
        from agent.skills.generate.self_reflection import reflect_on_reasoning

        # Hard claim + clear reasoning => confident.
        r = reflect_on_reasoning(
            "git 默认分支名应为 main。",
            "根据官方文档，git 默认分支为 main，这是明确的。",
        )
        assert r.confident is True

    def test_not_confident_on_hedged_reasoning(self):
        from agent.skills.generate.self_reflection import reflect_on_reasoning

        r = reflect_on_reasoning(
            "git 默认分支名应为 main。",
            "我猜测可能大概是这个值，不太确定。",
        )
        assert r.confident is False
        assert r.caveat  # caveat provided

    def test_not_confident_on_contradiction(self):
        from agent.skills.generate.self_reflection import reflect_on_reasoning

        r = reflect_on_reasoning(
            "超时应为 30 秒。",
            "文档说30秒但另一方面又说不超过60秒，存在矛盾。",
        )
        assert r.confident is False

    def test_no_hard_claims_is_confident(self):
        from agent.skills.generate.self_reflection import reflect_on_reasoning

        r = reflect_on_reasoning(
            "请进一步检查该系统。",
            "不确定具体原因。",
        )
        assert r.confident is True  # soft answer, no caveat needed


# ===========================================================================
# P2.7 — HITL gate + workflow DSL (removed)
# ===========================================================================
# TestHITLGate / TestWorkflowDSL removed: core/workflow/hitl.py was a zombie
# module (zero production callers) and has been deleted.


# ===========================================================================
# P3.1 — PII detection + redaction
# ===========================================================================


class TestPII:
    def test_detect_phone(self):
        from agent.guardrails.pii import detect_pii

        assert [m.kind for m in detect_pii("电话13812345678")] == ["phone"]

    def test_detect_email(self):
        from agent.guardrails.pii import detect_pii

        assert [m.kind for m in detect_pii("联系abc@test.com")] == ["email"]

    def test_detect_id_card(self):
        from agent.guardrails.pii import detect_pii

        matches = [m.kind for m in detect_pii("身份证110101199003071234")]
        assert "id_card" in matches

    def test_no_false_positive(self):
        from agent.guardrails.pii import detect_pii

        assert detect_pii("数据库连接池配置优化") == []

    def test_redact(self):
        from agent.guardrails.pii import redact_pii

        out = redact_pii("电话13812345678请回拨")
        assert "13812345678" not in out
        assert "已脱敏" in out


class TestOutputGuardrailPII:
    def test_output_redacts_pii(self):
        from agent.guardrails.output_guardrails import OutputGuardrail

        og = OutputGuardrail()
        result = og.validate(
            "联系工程师电话13812345678获取支持。",
            sources=["doc"],
            contexts=["ctx"],
        )
        assert result.action.value == "sanitize"
        assert "13812345678" not in (result.sanitized_content or "")


# ===========================================================================
# P3.2 / P3.3 / P3.4 — prompt A/B testing, prompt optimizer, cancellation
# (removed)
# ===========================================================================
# TestABTesting / TestPromptOptimizer / TestCancellation removed: the
# underlying modules (core/prompts/ab_testing.py, core/prompts/optimizer.py,
# core/concurrency/cancellation.py) were zombies (zero production callers) and
# have been deleted.


# ===========================================================================
# P3.6 — retrieval cache
# ===========================================================================


class TestRetrievalCache:
    def test_lru_eviction(self):
        from core.retrieval.cache import LRUCache

        c = LRUCache(maxsize=2)
        c.put("a", 1)
        c.put("b", 2)
        c.put("c", 3)  # evicts 'a'
        assert c.get("a") is None
        assert c.get("b") == 2
        assert c.get("c") == 3

    def test_hit_miss_stats(self):
        from core.retrieval.cache import LRUCache

        c = LRUCache(maxsize=10)
        c.put("k", "v")
        c.get("k")  # hit
        c.get("nope")  # miss
        stats = c.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert 0 < stats["hit_ratio"] < 1

    def test_cached_embedding(self):
        from core.retrieval.cache import CachedEmbeddingFunction, LRUCache

        class _Base:
            def __init__(self):
                self.calls = 0

            def embed_query(self, text):
                self.calls += 1
                return [1.0, 2.0]

            def embed_documents(self, texts):
                return [[1.0] for _ in texts]

        base = _Base()
        cached = CachedEmbeddingFunction(base)
        cached.embed_query("hello")
        cached.embed_query("hello")  # cached, no new call
        assert base.calls == 1


# ===========================================================================
# P3.7 — time decay
# ===========================================================================


class TestTimeDecay:
    def test_fresh_doc_unchanged(self):
        import time

        from core.retrieval.time_decay import apply_time_decay

        now = time.time()
        doc = Document(page_content="fresh", metadata={"score": 1.0, "created_at": now})
        out = apply_time_decay([doc], now=now)
        assert out[0].metadata["score"] == pytest.approx(1.0)

    def test_old_doc_decayed(self):
        import time

        from core.retrieval.time_decay import apply_time_decay

        now = time.time()
        # 360 days old, half-life 180 => factor ~0.25
        old_ts = now - 360 * 86400
        doc = Document(page_content="old", metadata={"score": 1.0, "created_at": old_ts})
        out = apply_time_decay([doc], half_life_days=180, now=now)
        assert out[0].metadata["score"] < 0.5
        assert out[0].metadata["score"] > 0.05  # floored at 0.1

    def test_no_timestamp_passthrough(self):
        from core.retrieval.time_decay import apply_time_decay

        doc = Document(page_content="nots", metadata={"score": 0.8})
        out = apply_time_decay([doc])
        assert out[0].metadata["score"] == 0.8


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
