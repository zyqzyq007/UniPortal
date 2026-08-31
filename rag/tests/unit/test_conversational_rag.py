#!/usr/bin/env python3
"""
F2 conversational RAG — regression guards for query condensation + history compression.

REQ-CR-003: condense_query resolves coreferences using history → standalone query.
REQ-CR-006: compress_history summarises old messages when above threshold.
REQ-CR-004: both degrade gracefully (never raise).

Run: pytest tests/unit/test_conversational_rag.py -v
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

sys.path.insert(0, ".")


# ===========================================================================
# REQ-CR-003 — Query condensation (coreference resolution)
# ===========================================================================


class TestCondenseQuery:
    def test_coreference_triggers_condensation(self):
        """A query with coreference markers + history → condense_query calls LLM."""
        from core.retrieval.query_transform import condense_query

        history = [
            HumanMessage(content="发动机振动异常怎么诊断？"),
            AIMessage(content="1. 检查传感器 2. 分析频率 3. 平衡校正"),
        ]
        with patch(
            "core.retrieval.query_transform._llm_invoke", return_value="分析振动频率的具体步骤"
        ):
            result = condense_query("那第二条具体怎么做？", history)
        assert "振动频率" in result or "频率" in result

    def test_no_coreference_passes_through(self):
        """A self-contained query (no coreference) passes through unchanged."""
        from core.retrieval.query_transform import condense_query

        history = [HumanMessage(content="之前的问题"), AIMessage(content="回答")]
        with patch("core.retrieval.query_transform._llm_invoke") as mock_llm:
            result = condense_query("液压系统压力标准是多少？", history)
        assert result == "液压系统压力标准是多少？"
        mock_llm.assert_not_called()  # no LLM call for self-contained query

    def test_no_history_passes_through(self):
        """No history → pass through (single-turn)."""
        from core.retrieval.query_transform import condense_query

        result = condense_query("那第二条呢？", [])
        assert result == "那第二条呢？"

    def test_llm_failure_degrades_to_original(self):
        """REQ-CR-004: LLM failure → original question (never raise)."""
        from core.retrieval.query_transform import condense_query

        history = [HumanMessage(content="问题"), AIMessage(content="回答")]
        with patch("core.retrieval.query_transform._llm_invoke", return_value=None):
            result = condense_query("那它怎么修？", history)
        assert result == "那它怎么修？"

    def test_coreference_detection(self):
        """_has_coreference detects Chinese + English coreference markers."""
        from core.retrieval.query_transform import _has_coreference

        assert _has_coreference("那第二条呢")
        assert _has_coreference("它怎么修")
        assert _has_coreference("上面的方法")
        assert _has_coreference("this method")
        assert not _has_coreference("液压系统压力标准")
        assert not _has_coreference("发动机振动诊断流程")


# ===========================================================================
# REQ-CR-006 — History compression
# ===========================================================================


class TestCompressHistory:
    def test_below_threshold_no_compression(self):
        """History at/below threshold → returned unchanged."""
        from core.memory.summarizer import compress_history

        history = [HumanMessage(content=f"msg {i}") for i in range(5)]
        result = asyncio.run(compress_history(history, threshold=10, recent_keep=6))
        assert len(result) == 5  # unchanged

    def test_above_threshold_triggers_summary(self):
        """History above threshold → old msgs summarised, recent kept verbatim."""
        from core.memory.summarizer import compress_history

        history = [HumanMessage(content=f"用户消息 {i}") for i in range(15)]
        mock_llm = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.content = "这是对话摘要"
        mock_llm.ainvoke = AsyncMock(return_value=mock_resp)

        with patch("models.llm_models.create_custom_llm", return_value=mock_llm):
            result = asyncio.run(compress_history(history, threshold=10, recent_keep=6))

        assert len(result) < len(history)  # compressed
        assert isinstance(result[0], SystemMessage)  # summary first
        assert "[对话摘要]" in result[0].content
        assert len(result) == 7  # 1 summary + 6 recent

    def test_llm_failure_degrades_to_truncation(self):
        """REQ-CR-004: summarisation failure → hard-truncate to recent (never raise)."""
        from core.memory.summarizer import compress_history

        history = [HumanMessage(content=f"msg {i}") for i in range(15)]
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM down"))

        with patch("models.llm_models.create_custom_llm", return_value=mock_llm):
            result = asyncio.run(compress_history(history, threshold=10, recent_keep=6))

        # Degraded to truncation: kept recent only.
        assert len(result) <= 6
        assert result[-1].content == "msg 14"  # most recent kept

    def test_empty_history_returns_empty(self):
        from core.memory.summarizer import compress_history

        result = asyncio.run(compress_history([]))
        assert result == []


# ===========================================================================
# REQ-CR-002 — harness accepts history parameter
# ===========================================================================


class TestHarnessHistoryParameter:
    def test_ainvoke_accepts_history(self):
        """harness.ainvoke signature accepts a history parameter."""
        import inspect

        from agent.harness.orchestrator import AgentHarness

        sig = inspect.signature(AgentHarness.ainvoke)
        assert "history" in sig.parameters, "ainvoke must accept history param"

    def test_astream_accepts_history(self):
        import inspect

        from agent.harness.orchestrator import AgentHarness

        sig = inspect.signature(AgentHarness.astream)
        assert "history" in sig.parameters, "astream must accept history param"

    def test_invoke_accepts_history(self):
        import inspect

        from agent.harness.orchestrator import AgentHarness

        sig = inspect.signature(AgentHarness.invoke)
        assert "history" in sig.parameters, "invoke must accept history param"


# ===========================================================================
# REQ-CR-005 — generate skill injects history into context
# ===========================================================================


class TestGenerateHistoryInjection:
    def test_inject_history_appends_to_context(self):
        """_inject_history appends a [对话历史] block when history present."""
        from agent.skills.generate.skill import GenerateSkill

        context = MagicMock()
        context.shared_state = {
            "conversation_history": [
                HumanMessage(content="发动机振动"),
                AIMessage(content="检查传感器"),
            ]
        }
        result = GenerateSkill._inject_history("检索到的文档内容", context)
        assert "[对话历史]" in result
        assert "检索到的文档内容" in result
        assert "发动机振动" in result

    def test_inject_history_noop_without_history(self):
        from agent.skills.generate.skill import GenerateSkill

        context = MagicMock()
        context.shared_state = {}
        result = GenerateSkill._inject_history("检索内容", context)
        assert result == "检索内容"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
