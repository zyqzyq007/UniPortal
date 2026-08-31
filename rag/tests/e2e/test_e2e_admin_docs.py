#!/usr/bin/env python3
"""
End-to-end tests for admin / documents / feedback / health endpoints through
the real FastAPI app (singletons mocked).

Run: pytest tests/e2e/test_e2e_admin_docs.py -v
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")


# ===========================================================================
# Health
# ===========================================================================


class TestHealth:
    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in ("healthy", "degraded")
        assert set(body["runtime_config"]) == {"schema_version", "fingerprint"}

    def test_admin_health(self, client):
        resp = client.get("/api/admin/health")
        # May be 200 or 503 depending on skill health checks; just assert it responds.
        assert resp.status_code in (200, 503)

    def test_admin_config(self, client):
        resp = client.get("/api/admin/config")
        assert resp.status_code == 200


# ===========================================================================
# Admin eval endpoints
# ===========================================================================


class TestAdminEval:
    def test_eval_runs_empty_initially(self, client):
        resp = client.get("/api/admin/eval/runs?limit=5")
        assert resp.status_code == 200
        body = resp.json()
        assert "runs" in body

    def test_candidates_endpoint(self, client):
        resp = client.get("/api/admin/eval/candidates")
        assert resp.status_code == 200
        body = resp.json()
        assert "total" in body
        assert "candidates" in body

    def test_inferences_endpoint(self, client):
        # Produce an inference first.
        client.post(
            "/api/chat",
            json={
                "message": "git 合并冲突如何解决？",
                "session_id": "e2e-admin-inf",
                "mode": "fast",
            },
        )
        resp = client.get("/api/admin/inferences?limit=5")
        assert resp.status_code == 200
        body = resp.json()
        assert body["stats"]["total"] >= 1
        assert "by_route" in body["stats"]

    def test_retrieval_misses_endpoint(self, client):
        resp = client.get("/api/admin/retrieval-misses?limit=10")
        assert resp.status_code == 200
        assert "misses" in resp.json()

    def test_eval_run_detail_404_for_unknown(self, client):
        resp = client.get("/api/admin/eval/runs/does_not_exist")
        assert resp.status_code == 404


# ===========================================================================
# Feedback
# ===========================================================================


class TestFeedbackFlow:
    def test_thumbs_up(self, client):
        # Need a session first.
        chat = client.post(
            "/api/chat",
            json={
                "message": "你好",
                "session_id": "e2e-fb-up",
            },
        ).json()
        resp = client.post(
            "/api/feedback",
            json={
                "session_id": "e2e-fb-up",
                "message_id": chat["metadata"]["message_id"],
                "feedback_type": "THUMBS_UP",
            },
        )
        assert resp.status_code == 200

    def test_correction_requires_corrected_answer(self, client):
        resp = client.post(
            "/api/feedback",
            json={
                "session_id": "e2e-fb-correction",
                "feedback_type": "CORRECTION",
                "original_answer": "原答案",
            },
        )
        # Missing corrected_answer => 400.
        assert resp.status_code == 400

    def test_feedback_stats(self, client):
        client.post(
            "/api/chat",
            json={
                "message": "你好",
                "session_id": "e2e-fb-stats",
            },
        )
        client.post(
            "/api/feedback",
            json={
                "session_id": "e2e-fb-stats",
                "feedback_type": "THUMBS_UP",
            },
        )
        resp = client.get("/api/feedback/stats/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert "total" in body or "positive_rate" in str(body)

    def test_feedback_by_session(self, client):
        sid = "e2e-fb-bysession"
        client.post("/api/chat", json={"message": "你好", "session_id": sid})
        client.post(
            "/api/feedback",
            json={
                "session_id": sid,
                "feedback_type": "FLAG",
                "content": "test flag",
            },
        )
        resp = client.get(f"/api/feedback/{sid}")
        assert resp.status_code == 200


# ===========================================================================
# Documents
# ===========================================================================


class TestDocuments:
    def test_upload_markdown(self, client, monkeypatch):
        """Upload a small markdown file; the background indexing is mocked."""
        import uuid as _uuid

        import api.routers.documents as docs_mod

        def _fake_process(doc_id, file_path, filename, file_hash):
            registry = docs_mod.get_document_registry()
            registry.update_status(doc_id, "indexed", 3)

        monkeypatch.setattr(docs_mod, "_process_document", _fake_process)

        # Unique filename AND content to avoid dedup (registry persists across tests).
        token = _uuid.uuid4().hex[:8]
        content = f"# 测试文档\n\ngit 合并冲突排查要点。唯一标识:{token}\n\ndocker 部署步骤。"
        resp = client.post(
            "/api/documents/upload",
            files={"file": (f"test_{token}.md", content.encode("utf-8"), "text/markdown")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "processing"
        assert token in body["filename"]

    def test_upload_rejects_unsupported_type(self, client):
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("test.xyz", b"content", "application/octet-stream")},
        )
        assert resp.status_code == 400

    def test_document_list_and_detail(self, client, monkeypatch):
        import uuid as _uuid

        import api.routers.documents as docs_mod

        def _fake_process(doc_id, file_path, filename, file_hash):
            docs_mod.get_document_registry().update_status(doc_id, "indexed", 2)

        monkeypatch.setattr(docs_mod, "_process_document", _fake_process)

        token = _uuid.uuid4().hex[:8]
        unique = f"# test\n\n唯一内容:{token}"
        upload = client.post(
            "/api/documents/upload",
            files={"file": (f"list_test_{token}.md", unique.encode("utf-8"), "text/markdown")},
        ).json()
        doc_id = upload["id"]

        # List.
        listing = client.get("/api/documents")
        assert listing.status_code == 200

        # Detail.
        detail = client.get(f"/api/documents/{doc_id}")
        assert detail.status_code == 200


# ===========================================================================
# Sessions
# ===========================================================================


class TestSessions:
    def test_list_sessions(self, client):
        client.post("/api/chat", json={"message": "你好", "session_id": "e2e-sess-1"})
        resp = client.get("/api/sessions")
        assert resp.status_code == 200

    def test_session_detail(self, client):
        sid = "e2e-sess-detail"
        client.post("/api/chat", json={"message": "你好", "session_id": sid})
        resp = client.get(f"/api/sessions/{sid}")
        assert resp.status_code == 200

    def test_clear_session(self, client):
        sid = "e2e-sess-clear"
        client.post("/api/chat", json={"message": "你好", "session_id": sid})
        resp = client.delete(f"/api/chat/session/{sid}")
        assert resp.status_code == 200


# ===========================================================================
# Retrieval endpoint
# ===========================================================================


class TestRetrievalAPI:
    def test_hybrid_retrieval(self, client):
        resp = client.post(
            "/api/retrieval",
            json={
                "query": "合并",
                "top_k": 3,
            },
        )
        # May return results or empty depending on mock; just assert it responds.
        assert resp.status_code in (200, 404, 422)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
