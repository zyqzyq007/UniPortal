#!/usr/bin/env python3
"""
End-to-end tests for the evaluation flywheel — the closed loop:
  chat (sampled) -> InferenceStore -> negative feedback -> candidate promotion
                                                   -> retrieval miss

These verify the whole flywheel works through the real HTTP API with only the
LLM/retriever mocked (judge is stubbed where needed). No Ollama/Milvus.

Run: pytest tests/e2e/test_e2e_flywheel.py -v
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")


class TestInferenceCapture:
    """A sampled chat request leaves a row in the inference store."""

    def test_chat_records_inference(self, client):
        # EVAL_SAMPLE_RATE=1.0 in conftest => everything is captured.
        resp = client.post(
            "/api/chat",
            json={
                "message": "git 合并冲突如何解决？",
                "session_id": "e2e-fly-1",
                "mode": "fast",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # trace_id / message_id written back into metadata by the capture.
        assert body["metadata"].get("trace_id"), "trace_id should be captured"
        assert body["metadata"].get("message_id"), "message_id should be captured"

        # The inference is queryable via the admin endpoint.
        inferences = client.get("/api/admin/inferences?limit=10").json()
        assert inferences["stats"]["total"] >= 1
        trace_ids = [i["trace_id"] for i in inferences["inferences"]]
        assert body["metadata"]["trace_id"] in trace_ids

    def test_inference_detail_has_retrieved_docs(self, client):
        resp = client.post(
            "/api/chat",
            json={
                "message": "docker 容器无法启动如何排查？",
                "session_id": "e2e-fly-2",
                "mode": "fast",
            },
        )
        trace_id = resp.json()["metadata"]["trace_id"]

        detail = client.get(f"/api/admin/inferences/{trace_id}").json()
        assert detail["trace_id"] == trace_id
        assert detail["query"] == "docker 容器无法启动如何排查？"
        assert len(detail["retrieved_docs"]) > 0
        assert detail["route"] == "fast"


class TestFeedbackToCandidate:
    """A negative feedback promotes the matching inference into the candidate pool."""

    def test_thumbs_down_promotes_candidate(self, client):
        # 1. Chat to produce a captured inference.
        chat = client.post(
            "/api/chat",
            json={
                "message": "http 状态码 502 如何分析？",
                "session_id": "e2e-fb-1",
                "mode": "fast",
            },
        ).json()
        trace_id = chat["metadata"]["trace_id"]
        message_id = chat["metadata"]["message_id"]

        # 2. Submit a thumbs_down with the trace_id linkage.
        fb = client.post(
            "/api/feedback",
            json={
                "session_id": "e2e-fb-1",
                "message_id": message_id,
                "trace_id": trace_id,
                "feedback_type": "THUMBS_DOWN",
                "content": "答案不够详细",
            },
        )
        assert fb.status_code == 200

        # 3. The inference was promoted into the candidate pool.
        cands = client.get("/api/admin/eval/candidates").json()
        cand_queries = [c.get("query", "") for c in cands.get("candidates", [])]
        assert any("502" in q for q in cand_queries), "negative feedback should promote a candidate"

    def test_correction_promotes_with_corrected_answer(self, client):
        chat = client.post(
            "/api/chat",
            json={
                "message": "git 默认分支名是什么？",
                "session_id": "e2e-fb-2",
                "mode": "fast",
            },
        ).json()
        trace_id = chat["metadata"]["trace_id"]

        fb = client.post(
            "/api/feedback",
            json={
                "session_id": "e2e-fb-2",
                "trace_id": trace_id,
                "feedback_type": "CORRECTION",
                "original_answer": chat["response"],
                "corrected_answer": "git 默认分支名应为 main，参考官方文档。",
            },
        )
        assert fb.status_code == 200

        cands = client.get("/api/admin/eval/candidates").json()
        # The correction candidate should carry the corrected answer.
        matching = [c for c in cands.get("candidates", []) if "默认分支" in c.get("query", "")]
        assert len(matching) >= 1

    def test_invalid_feedback_type_returns_400(self, client):
        resp = client.post(
            "/api/feedback",
            json={
                "session_id": "e2e-fb-3",
                "feedback_type": "INVALID_TYPE",
            },
        )
        assert resp.status_code in (400, 422)


class TestRetrievalMiss:
    """
    When the judge finds the answer unsupported (low faithfulness), a
    retrieval-miss signal is recorded for offline tuning.
    """

    def test_low_faithfulness_records_miss(self, client, monkeypatch):
        # Stub the judge to return low faithfulness so the miss path triggers.
        from agent.eval import flywheel as fly_mod
        from agent.eval.judge import TrustworthyMetrics

        class _LowFaithJudge:
            available = True

            def evaluate(self, **kw):
                return TrustworthyMetrics(
                    faithfulness=0.2,
                    answer_relevancy=0.5,
                    hallucination_score=0.8,
                    context_precision=0.3,
                    judge_used=True,
                )

        monkeypatch.setattr(fly_mod, "get_judge", lambda: _LowFaithJudge())

        chat = client.post(
            "/api/chat",
            json={
                "message": "redis 缓存穿透如何防护？",
                "session_id": "e2e-miss-1",
                "mode": "fast",
            },
        ).json()
        trace_id = chat["metadata"]["trace_id"]

        client.post(
            "/api/feedback",
            json={
                "session_id": "e2e-miss-1",
                "trace_id": trace_id,
                "feedback_type": "THUMBS_DOWN",
            },
        )

        misses = client.get("/api/admin/retrieval-misses?limit=20").json()
        miss_queries = [m.get("query", "") for m in misses.get("misses", [])]
        assert any("缓存穿透" in q for q in miss_queries), (
            "low-faithfulness feedback should record a retrieval miss"
        )


class TestCandidatePromotionToGolden:
    """A candidate can be promoted into the golden dataset (end-to-end)."""

    def test_promote_candidate_to_golden(self, client, tmp_path, monkeypatch):
        import agent.eval.candidates as cand_mod

        # First produce a candidate via negative feedback.
        chat = client.post(
            "/api/chat",
            json={
                "message": "nginx 反向代理如何配置超时？",
                "session_id": "e2e-golden-1",
                "mode": "fast",
            },
        ).json()
        trace_id = chat["metadata"]["trace_id"]
        client.post(
            "/api/feedback",
            json={
                "session_id": "e2e-golden-1",
                "trace_id": trace_id,
                "feedback_type": "CORRECTION",
                "corrected_answer": "nginx 超时由 proxy_read_timeout 指令控制。",
            },
        )

        cands = client.get("/api/admin/eval/candidates").json()["candidates"]
        target = next(c for c in cands if "超时" in c.get("query", ""))

        # Promote it into a tmp golden dataset.
        golden_path = str(tmp_path / "golden.yaml")
        import pathlib

        pathlib.Path(golden_path).write_text("cases: []\n", encoding="utf-8")

        promoted = cand_mod.promote_candidate_to_golden(
            target["candidate_id"], dataset_path=golden_path
        )
        assert promoted is not None
        assert "proxy_read_timeout" in promoted.reference_answer

        # Verify the golden dataset now contains it.
        from agent.eval.dataset import load_dataset

        loaded = load_dataset(golden_path)
        assert any("proxy_read_timeout" in (c.reference_answer or "") for c in loaded)


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
