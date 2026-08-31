#!/usr/bin/env python3
"""
Stage 1 audit bugfix tests — B1 (path traversal) + B2 (admin auth gating).

B2: the eval run/candidate/retrieval-miss endpoints and the feedback
escalation endpoints MUST be gated by require_admin, consistent with the
already-gated /inferences endpoints. An anonymous caller (no X-Admin-Key when
ADMIN_API_KEY is configured) MUST get 401.

B1: eval_run_detail builds a path from the user-supplied run_id. A traversal
attempt (.., slashes) MUST be rejected with 400 before any filesystem read.

Run: pytest tests/unit/test_audit_stage1_auth.py -v
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")


# Endpoints that MUST be admin-gated (B2). Grouped for parametrisation.
ADMIN_GATED = [
    ("/api/admin/eval/runs", "GET"),
    ("/api/admin/eval/candidates", "GET"),
    ("/api/admin/retrieval-misses", "GET"),
    ("/api/feedback/escalations/pending", "GET"),
]


@pytest.fixture
def client_strict_admin(
    tmp_data_dir, fake_llm, fake_retriever, fake_harness, fake_session_memory, monkeypatch
):
    """A TestClient with ADMIN_API_KEY configured, carrying NO key header so
    require_admin must reject non-loopback requests.

    The Starlette TestClient client.host is the literal "testclient", which the
    loopback fallback in require_admin trusts. To actually exercise the
    configured-key rejection path we monkeypatch the require_admin to a version
    that ignores the "testclient" bypass. Simpler: we just verify the
    dependency is wired by checking that WITH a wrong key the endpoints 401
    (the header is supplied but mismatched), which proves require_admin runs.
    """
    import agent.harness as harness_mod

    monkeypatch.setattr(harness_mod, "get_agent_harness", lambda *a, **k: fake_harness)

    import core.intent.classifier as intent_mod

    monkeypatch.setattr(
        intent_mod, "get_intent_classifier", lambda *a, **k: _FakeIntentClassifier(fake_llm)
    )

    import core.retrieval.hybrid_retriever as hr_mod

    monkeypatch.setattr(hr_mod, "get_hybrid_retriever", lambda *a, **k: fake_retriever)

    import models.llm_models as llm_mod

    monkeypatch.setattr(llm_mod, "get_llm", lambda *a, **k: fake_llm)
    monkeypatch.setattr(llm_mod, "create_custom_llm", lambda *a, **k: fake_llm)

    from types import SimpleNamespace

    import core.fast_mode as fast_mod

    async def _fake_fast_generate_async(query, **kwargs):
        return SimpleNamespace(
            answer="ok",
            sources=[],
            retrieval_count=0,
            retrieval_time_ms=1.0,
            generation_time_ms=1.0,
        )

    monkeypatch.setattr(fast_mod, "fast_generate_async", _fake_fast_generate_async)

    monkeypatch.setattr("utils.env_utils.RERANKER_WARMUP", False)
    monkeypatch.setattr("utils.env_utils.RERANKER_ENABLED", False)

    from api.main import app
    from api.routers.chat import get_session_memory as chat_get
    from api.routers.sessions import get_session_memory as sess_get

    app.dependency_overrides[chat_get] = lambda: fake_session_memory
    app.dependency_overrides[sess_get] = lambda: fake_session_memory

    # Configure a real admin key so the gate is active, and send a WRONG key.
    monkeypatch.setenv("ADMIN_API_KEY", "correct-stage1-key")
    from fastapi.testclient import TestClient

    client = TestClient(app, headers={"X-Admin-Key": "WRONG-KEY"}, raise_server_exceptions=True)
    with client:
        yield client
    app.dependency_overrides.clear()


class _FakeIntentClassifier:
    _RAG_KEYWORDS = frozenset(["git", "合并", "冲突", "部署", "配置"])
    _CHAT_KEYWORDS = frozenset(["你好", "你是谁"])

    def __init__(self, fake_llm):
        self._llm = fake_llm

    def _keyword(self, query):
        from core.intent.classifier import IntentResult, IntentType

        text = query.lower()
        if any(kw in text for kw in self._RAG_KEYWORDS):
            return IntentResult(intent=IntentType.RAG_QUERY, confidence=0.9, reasoning="kw")
        if any(kw in text for kw in self._CHAT_KEYWORDS):
            return IntentResult(intent=IntentType.GENERAL_CHAT, confidence=0.9, reasoning="kw")
        return None

    async def aclassify(self, query):
        from core.intent.classifier import IntentResult, IntentType

        return self._keyword(query) or IntentResult(
            intent=IntentType.GENERAL_CHAT, confidence=0.7, reasoning="fake"
        )

    def classify(self, query):
        from core.intent.classifier import IntentResult, IntentType

        return self._keyword(query) or IntentResult(
            intent=IntentType.GENERAL_CHAT, confidence=0.7, reasoning="fake"
        )


# ---------------------------------------------------------------------------
# B2 — admin-gated endpoints reject a wrong/missing key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path,method", ADMIN_GATED)
def test_b2_admin_endpoints_reject_wrong_key(client_strict_admin, path, method):
    """When ADMIN_API_KEY is configured, a mismatched key MUST yield 401.

    This proves require_admin is wired into the endpoint (a missing gate would
    return 200 regardless of the key).
    """
    resp = client_strict_admin.request(method, path)
    assert resp.status_code == 401, (
        f"{method} {path} returned {resp.status_code}, expected 401 (admin gate missing)"
    )


def test_b2_feedback_resolve_rejects_wrong_key(client_strict_admin):
    """POST resolve_escalation mutates state; it MUST be admin-gated."""
    resp = client_strict_admin.post(
        "/api/feedback/escalations/nonexistent-id/resolve",
        json={"resolution": "fixed"},
    )
    assert resp.status_code == 401, (
        f"resolve_escalation returned {resp.status_code}, expected 401 (admin gate missing)"
    )


# ---------------------------------------------------------------------------
# B1 — eval_run_detail path traversal is blocked
# ---------------------------------------------------------------------------


def test_b1_eval_run_detail_rejects_traversal(client):
    """A run_id failing the safe-id allowlist MUST be rejected with 400 BEFORE
    any filesystem read.

    Starlette's {run_id} converter rejects embedded '/' (so encoded %2F never
    reaches the endpoint), but it DOES let through other out-of-allowlist
    characters (`.`, spaces, `;`). These reach the endpoint and must be rejected
    there as defence-in-depth before any path is built or read.
    """
    # These all match the {run_id} route (no '/') and thus reach the endpoint.
    # Without the allowlist they'd build a path and attempt a filesystem read.
    for bad in ("...", "a.b", "a;b"):
        resp = client.get(f"/api/admin/eval/runs/{bad}")
        assert resp.status_code == 400, (
            f"run_id={bad!r} -> {resp.status_code}, expected 400 (rejected by allowlist "
            f"before filesystem read); body={resp.text[:200]}"
        )


def test_b1_eval_run_detail_accepts_valid_id(client):
    """A clean run_id MUST still work (format: ^[A-Za-z0-9_-]+$)."""
    # A non-existent but well-formed id returns 404 (not 400).
    resp = client.get("/api/admin/eval/runs/valid_run_id_123")
    assert resp.status_code == 404, f"valid run_id returned {resp.status_code}, expected 404"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
