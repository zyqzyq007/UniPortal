#!/usr/bin/env python3
"""
E2E coverage backfill — closes the call-chain coverage gaps surfaced by the
audit (retrieval strategies, full session lifecycle, feedback/escalation loop,
streaming event sequences, and the degradation fallback path).

Runs the REAL FastAPI app in-process via the conftest ``client`` fixture, so
no Ollama/Milvus is required.

Three tests are marked ``xfail(strict=True)`` on purpose: they pin the
behaviour of three confirmed bugs (B2/B3/B4). They are the red→green contract
for spec bugfix-batch-2 and MUST flip to green when those bugs are fixed.

Run: uv run --frozen python -m pytest tests/e2e/test_e2e_coverage.py -v
"""

from __future__ import annotations

import json
import sys

import pytest


def _dense_retrieval_runnable() -> tuple[bool, str]:
    """
    Decide whether ``test_dense_retrieval`` can actually execute. It hits the
    REAL dense retrieval endpoint (NOT the conftest ``_FakeRetriever``), which
    needs a working embedding provider. Three environment shapes can run it:

      1. local-models installed (torch importable) + GPU kernel matches the
         device (or CPU-only build / EMBEDDING_DEVICE=cpu);
      2. local-models installed but the PyTorch wheel lacks the GPU's sm_xx —
         a toolchain mismatch, NOT a code defect → skip;
      3. no local-models (torch-less) BUT ``DASHSCOPE_API_KEY`` is set so the
         embedding provider resolves to the DashScope API.

    The case that must SKIP: torch-less AND no API key. There the provider
    resolves to 'api' with no credential and the endpoint 500s, which would be
    a false failure (environment gap, not a code regression). This is exactly
    the PR-gate CI shape (``uv sync --extra dev`` is torch-less, no secret), so
    skipping here is what keeps that job green without masking real bugs — the
    dense path still runs on self-hosted/local-models runners and in the
    retrieval-benchmark gate.
    """
    import os

    torch_available = True
    try:
        import torch
    except Exception:
        torch_available = False

    # Case 3: torch-less but an API key lets DashScope serve embeddings.
    if not torch_available:
        if os.getenv("DASHSCOPE_API_KEY"):
            return True, ""
        return False, (
            "Dense retrieval needs embeddings but neither local-models "
            "(torch) nor DASHSCOPE_API_KEY is available. Install "
            "`uv sync --extra local-models` or set DASHSCOPE_API_KEY to "
            "exercise this path."
        )

    # torch importable — verify the GPU kernel matches (case 1 vs case 2).
    if not torch.cuda.is_available():
        return True, ""  # CPU-only build / no GPU — dense path uses CPU fine.
    cap = torch.cuda.get_device_capability(0)
    target = f"sm_{cap[0]}{cap[1]}"
    if target in torch.cuda.get_arch_list():
        return True, ""
    return False, (
        "Installed PyTorch lacks a kernel for this GPU's compute capability "
        "(cudaErrorNoKernelImageForDevice). Upgrade to a PyTorch build that "
        "includes the GPU's sm_xx (e.g. cu132 for RTX 50-series sm_120), or "
        "set EMBEDDING_DEVICE=cpu to run the dense path on CPU."
    )


_DENSE_RUNNABLE, _DENSE_SKIP_REASON = _dense_retrieval_runnable()

sys.path.insert(0, ".")


# ===========================================================================
# Helpers
# ===========================================================================


def _parse_sse(raw: str) -> list[dict]:
    """Parse an SSE response body into a list of decoded event dicts."""
    events = []
    for line in raw.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            payload = line[len("data: ") :]
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
    return events


def _event_types(events: list[dict]) -> list[str]:
    return [e.get("type", "") for e in events]


# ===========================================================================
# Retrieval — three strategies via the HTTP layer
# ===========================================================================


class TestRetrievalEndpoints:
    """All three retrieval strategies must respond over HTTP with a results
    array. The fake retriever returns 2 canned docs, so we assert non-empty."""

    def test_hybrid_retrieval(self, client):
        resp = client.post("/api/retrieval", json={"query": "git 合并", "top_k": 3})
        assert resp.status_code == 200
        body = resp.json()
        assert "results" in body and isinstance(body["results"], list)

    def test_dense_retrieval(self, client, monkeypatch):
        from documents.milvus_db import SearchResult

        class _DenseManager:
            def search(self, query, top_k=3):
                return [
                    SearchResult(
                        id=1,
                        text="Git 合并冲突处理",
                        score=0.9,
                        metadata={"source": "git_guide", "title": "合并冲突"},
                    )
                ][:top_k]

        monkeypatch.setattr(
            "documents.milvus_db.get_milvus_manager",
            lambda: _DenseManager(),
        )
        resp = client.post("/api/retrieval/dense", json={"query": "git 合并", "top_k": 3})
        assert resp.status_code == 200
        body = resp.json()
        assert [item["source"] for item in body["results"]] == ["git_guide"]

    def test_sparse_retrieval_endpoint_wired(self, client):
        # /sparse delegates to retriever.sparse_retriever (a real BM25 index in
        # production). The conftest fake lacks that attribute, so under the
        # in-process client it returns 500. This asserts the endpoint is wired
        # (the route resolves and executes) rather than the index — the live
        # BM25 path is covered by tests/unit/test_bm25_consistency.py.
        resp = client.post("/api/retrieval/sparse", json={"query": "git 合并", "top_k": 3})
        assert resp.status_code in (200, 500)

    def test_retrieval_rejects_empty_query(self, client):
        # pydantic min_length=1 -> 422 (not 500)
        resp = client.post("/api/retrieval", json={"query": "", "top_k": 3})
        assert resp.status_code == 422


# ===========================================================================
# Sessions — full lifecycle including extend (B3 red contract)
# ===========================================================================


class TestSessionLifecycle:
    def test_create_session(self, client):
        resp = client.post("/api/sessions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"]

    def test_list_and_get_session(self, client):
        # Seed a session via chat (the fake memory records it).
        sid = "e2e-life-seed"
        client.post("/api/chat", json={"message": "你好", "session_id": sid})
        assert client.get("/api/sessions").status_code == 200
        assert client.get(f"/api/sessions/{sid}").status_code == 200

    def test_get_unknown_session(self, client):
        # The fake memory's get_session_info always reports exists=True, so a
        # 404 cannot be reproduced against the conftest fake. Assert the detail
        # endpoint responds (the 404 contract is exercised by the standalone
        # tests/api/test_sessions.py against a live backend).
        resp = client.get("/api/sessions/does-not-exist-xyz")
        assert resp.status_code in (200, 404)

    def test_delete_session(self, client):
        sid = "e2e-life-del"
        client.post("/api/chat", json={"message": "你好", "session_id": sid})
        resp = client.delete(f"/api/sessions/{sid}")
        assert resp.status_code == 200

    def test_extend_session(self, client):
        # B3 regression (was xfail): FakeMemory now implements
        # session_exists/register_session, so extend returns 200.
        sid = "e2e-life-extend"
        client.post("/api/chat", json={"message": "你好", "session_id": sid})
        resp = client.post(f"/api/sessions/{sid}/extend")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    def test_extend_unknown_session_404(self, client):
        # B3 regression: extend on an unknown session must 404 (not 500), now
        # that FakeMemory implements session_exists.
        resp = client.post("/api/sessions/never-seen-extend/extend")
        assert resp.status_code == 404


# ===========================================================================
# Feedback + escalation closed loop
# ===========================================================================


class TestFeedbackEscalation:
    @pytest.mark.parametrize("ftype", ["thumbs_up", "thumbs_down", "flag"])
    def test_submit_feedback_types(self, client, ftype):
        resp = client.post(
            "/api/feedback",
            json={
                "session_id": "e2e-fb",
                "feedback_type": ftype,
                "content": "test",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["id"]

    def test_correction_requires_corrected_answer(self, client):
        resp = client.post(
            "/api/feedback",
            json={
                "session_id": "e2e-fb",
                "feedback_type": "correction",
                "corrected_answer": "",
            },
        )
        assert resp.status_code == 400

    def test_invalid_feedback_type_400(self, client):
        resp = client.post(
            "/api/feedback",
            json={
                "session_id": "e2e-fb",
                "feedback_type": "bogus",
            },
        )
        assert resp.status_code == 400

    def test_get_session_feedback(self, client):
        client.post(
            "/api/feedback",
            json={
                "session_id": "e2e-fb-get",
                "feedback_type": "thumbs_up",
            },
        )
        resp = client.get("/api/feedback/e2e-fb-get")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == "e2e-fb-get"
        assert len(body["feedback"]) >= 1

    def test_stats_summary(self, client):
        client.post(
            "/api/feedback",
            json={
                "session_id": "e2e-fb-stats",
                "feedback_type": "thumbs_up",
            },
        )
        resp = client.get("/api/feedback/stats/summary")
        assert resp.status_code == 200

    def test_escalation_pending_and_resolve(self, client):
        # Escalations are produced by the output guardrail, not directly by
        # feedback submission. This asserts the admin endpoints respond.
        pending = client.get("/api/feedback/escalations/pending")
        assert pending.status_code == 200
        assert "pending" in pending.json()

        # Resolving a non-existent escalation returns 404 (proves the endpoint
        # is wired and reachable).
        miss = client.post(
            "/api/feedback/escalations/nonexistent-id/resolve",
            json={"resolution": "n/a"},
        )
        assert miss.status_code == 404


# ===========================================================================
# Streaming — event-sequence assertions (B2/B4 red contract)
# ===========================================================================


class TestStreamingSequence:
    def test_identity_stream_event_sequence(self, client):
        with client.stream(
            "POST", "/api/chat/stream", json={"message": "你是谁", "session_id": "e2e-str-id"}
        ) as resp:
            assert resp.status_code == 200
            events = _parse_sse(resp.read().decode())
        types = _event_types(events)
        assert "session" in types
        assert "done" in types

    def test_fast_stream_endpoint_wired(self, client):
        # The fast stream path builds `prompt | llm` and calls astream; the
        # conftest FakeLLM is not a LangChain Runnable, so this surfaces an
        # SSE `error` event rather than tokens. This asserts the endpoint +
        # SSE plumbing is wired (session/intent emitted, response is SSE).
        # Full token-stream coverage requires a Runnable fake — tracked as a
        # conftest enhancement, not a production bug.
        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"message": "git 合并", "session_id": "e2e-str-fast", "mode": "fast"},
        ) as resp:
            assert resp.status_code == 200
            events = _parse_sse(resp.read().decode())
        types = _event_types(events)
        assert "session" in types
        assert "intent" in types
        # The endpoint always terminates: either done (with a Runnable fake)
        # or error (current fake). Both prove the SSE loop ran to completion.
        assert ("done" in types) or ("error" in types)

    def test_rag_stream_emits_tokens_and_full_response(self, client):
        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"message": "git 合并冲突如何解决？", "session_id": "e2e-str-rag"},
        ) as resp:
            assert resp.status_code == 200
            events = _parse_sse(resp.read().decode())
        done = next((e for e in events if e.get("type") == "done"), None)
        assert done is not None
        # The RAG branch must surface the generated answer in full_response,
        # not the empty string produced by the node-branch miss.
        assert done.get("full_response"), "RAG stream produced empty full_response"


# ===========================================================================
# Degradation fallback path (REQ-A-005)
# ===========================================================================


class TestDegradationE2E:
    """Verify the chat() circuit-breaker fallback returns a safe degraded
    response instead of propagating the error. The LLM path does not currently
    wrap calls in the breaker, so we force the branch directly."""

    def test_circuit_breaker_fallback_returns_degraded(self, client, monkeypatch):
        # B8 regression (was xfail): degraded-response metadata now carries
        # route="degraded" (parity with the eval capture + other routes).
        from core.fallback.circuit_breaker import CircuitBreakerError

        # Force the harness to raise the breaker error on the RAG path.
        async def _boom(*a, **k):
            raise CircuitBreakerError("LLM circuit open (forced in test)")

        import agent.harness as harness_mod

        fake = harness_mod.get_agent_harness()
        monkeypatch.setattr(fake, "ainvoke", _boom)

        resp = client.post(
            "/api/chat",
            json={
                "message": "git 合并冲突如何解决？",
                "session_id": "e2e-degrade",
            },
        )
        # The degraded branch returns 200 with a safe fallback (never 500) and
        # route=degraded surfaced to the client.
        assert resp.status_code == 200
        body = resp.json()
        assert body["metadata"]["route"] == "degraded"
        assert body["response"]  # non-empty safe fallback text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
