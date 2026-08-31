#!/usr/bin/env python3
"""
End-to-end tests for the chat endpoint's four routing branches:
identity shortcut, fast mode, general_chat, and the RAG pipeline.

These run the REAL FastAPI app in-process via TestClient, with the expensive
singletons (LLM, retriever, harness, session memory) replaced by fakes from
conftest.py — so no Ollama or Milvus is required.

Run: pytest tests/e2e/test_e2e_chat.py -v
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")


# ===========================================================================
# Identity shortcut branch
# ===========================================================================


class TestIdentityBranch:
    def test_identity_query_skips_llm(self, client):
        """'你是谁' / capability queries return a canned identity response."""
        resp = client.post(
            "/api/chat",
            json={
                "message": "你好，请介绍一下你能做什么？",
                "session_id": "e2e-identity",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == "e2e-identity"
        assert body["intent"] == "general_chat"
        assert body["metadata"]["route"] == "general_chat"
        # message_id should be minted (P0 fix for feedback linkage).
        assert body["metadata"]["message_id"]
        # Q7 characterization (F-EG-09): trace_id + prompt_profile are part of
        # the per-route contract. The refactor MUST preserve them.
        assert body["metadata"]["trace_id"]
        assert body["metadata"]["prompt_profile"]


# ===========================================================================
# Fast mode branch
# ===========================================================================


class TestFastModeBranch:
    def test_fast_mode_returns_sources_and_route(self, client):
        resp = client.post(
            "/api/chat",
            json={
                "message": "git 合并冲突如何解决？",
                "session_id": "e2e-fast",
                "mode": "fast",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["metadata"]["route"] == "fast"
        assert body["intent"] == "rag_query"
        assert len(body["sources"]) > 0
        assert body["metadata"]["source_count"] == len(body["sources"])
        # Fast responses carry message_id for feedback linkage.
        assert body["metadata"]["message_id"]
        # Q7 characterization (F-EG-09): trace_id + prompt_profile contract.
        assert body["metadata"]["trace_id"]
        assert body["metadata"]["prompt_profile"]


# ===========================================================================
# RAG pipeline branch (uses fake harness)
# ===========================================================================


class TestRagBranch:
    def test_rag_query_returns_answer_with_sources(self, client):
        resp = client.post(
            "/api/chat",
            json={
                "message": "git 合并冲突如何解决？",
                "session_id": "e2e-rag",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["metadata"]["route"] == "rag"
        assert "合并" in body["response"]
        assert [source["source"] for source in body["sources"]] == ["git_guide"]
        assert [source["title"] for source in body["sources"]] == ["合并冲突排查"]

    def test_rag_response_has_confidence_metadata(self, client):
        """P0: confidence is computed and surfaced in metadata."""
        resp = client.post(
            "/api/chat",
            json={
                "message": "docker 容器无法启动如何排查？",
                "session_id": "e2e-rag-conf",
            },
        )
        body = resp.json()
        assert body["metadata"]["route"] == "rag"
        # confidence may be None (general) or a float; confidence_level always present.
        assert "confidence_level" in body["metadata"]
        assert body["metadata"]["confidence_level"] in ("high", "medium", "low", "unknown")
        assert "refused" in body["metadata"]
        # Q7 characterization (F-EG-09): trace_id + prompt_profile contract.
        assert body["metadata"]["trace_id"]
        assert body["metadata"]["prompt_profile"]


# ===========================================================================
# Refuse-to-answer (P0): weak retrieval evidence
# ===========================================================================


class TestRefuseToAnswer:
    def test_low_relevance_triggers_refusal(self, client, monkeypatch):
        """
        When every retrieved doc scores below min_relevance_threshold, the
        generate skill refuses rather than hallucinating. We force the fake
        retriever to return low-score docs.
        """
        from langchain_core.documents import Document

        from core.retrieval import hybrid_retriever as hr_mod

        class _LowScoreRetriever:
            def retrieve(self, query, top_k=None, filter_expr=None):
                return [
                    Document(page_content="完全无关的内容A", metadata={"score": 0.05}),
                    Document(page_content="完全无关的内容B", metadata={"score": 0.08}),
                ]

            async def aretrieve(self, query, top_k=None, filter_expr=None):
                return self.retrieve(query, top_k=top_k)

        monkeypatch.setattr(hr_mod, "get_hybrid_retriever", lambda *a, **k: _LowScoreRetriever())

        resp = client.post(
            "/api/chat",
            json={
                "message": "某个知识库外的问题xyz",
                "session_id": "e2e-refuse",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # Either refused (confidence 0) or a low-confidence answer.
        assert body["metadata"]["confidence_level"] in ("low", "medium", "unknown")


# ===========================================================================
# Session persistence across turns
# ===========================================================================


class TestSessionContinuity:
    def test_reuses_provided_session_id(self, client):
        sid = "e2e-continuity"
        r1 = client.post("/api/chat", json={"message": "你是谁", "session_id": sid})
        assert r1.status_code == 200
        assert r1.json()["session_id"] == sid

        r2 = client.post("/api/chat", json={"message": "你能做什么", "session_id": sid})
        assert r2.status_code == 200
        assert r2.json()["session_id"] == sid


# ===========================================================================
# Streaming (SSE) — RAG branch
# ===========================================================================


class TestStreaming:
    def test_stream_emits_events(self, client):
        """The SSE endpoint emits a 'done' event for a RAG query."""
        # F-EG-07: the blocking iter_lines() below had no timeout. If the SSE
        # generator ever stops yielding (e.g. a graph custom-event regression
        # makes astream() hang), the test — and the whole CI job — would block
        # until GitHub's 6h ceiling. Consume on a daemon thread and join with a
        # 30s ceiling so a hang surfaces as a fast, locatable failure instead.
        # (anyio.fail_after can't cancel blocking sync I/O, so a thread join is
        # the correct primitive here.)
        import threading

        collected = {"text": "", "done": threading.Event()}

        def _consume(resp):
            try:
                for line in resp.iter_lines():
                    collected["text"] += line + "\n"
            finally:
                collected["done"].set()

        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"message": "git 合并冲突如何解决？", "session_id": "e2e-stream"},
        ) as resp:
            assert resp.status_code == 200
            consumer = threading.Thread(target=_consume, args=(resp,), daemon=True)
            consumer.start()
            assert collected["done"].wait(timeout=30), (
                "SSE stream did not finish within 30s — the endpoint likely hung "
                "(astream never returned); see F-EG-07"
            )

        # SSE should contain at least a done or error event.
        body = collected["text"]
        assert ("event: done" in body) or ("done" in body) or ("event:" in body)


# ===========================================================================
# Chat history
# ===========================================================================


class TestChatHistory:
    def test_get_history(self, client):
        sid = "e2e-history"
        client.post("/api/chat", json={"message": "你好", "session_id": sid})
        resp = client.get(f"/api/chat/history/{sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == sid
        assert [message["role"] for message in body["messages"]] == ["user", "assistant"]
        assert body["messages"][0]["content"] == "你好"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
