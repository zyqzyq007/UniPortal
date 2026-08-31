#!/usr/bin/env python3
"""
Unit tests for the flywheel: inference capture, sampling, candidate promotion,
and the negative-feedback trigger. These do NOT invoke the real LLM.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, ".")


# ---------------------------------------------------------------------------
# Sampler
# ---------------------------------------------------------------------------


class TestSampler:
    def test_always_samples_degraded(self):
        from agent.eval.sampler import should_sample

        assert should_sample({}, "degraded", sample_rate=0.0) is True

    def test_always_samples_forced_rag(self):
        from agent.eval.sampler import should_sample

        assert should_sample({"force_rag": True}, "general_chat", sample_rate=0.0) is True

    def test_always_samples_low_confidence(self):
        from agent.eval.sampler import should_sample

        assert should_sample({"intent_confidence": 0.2}, "rag", sample_rate=0.0) is True

    def test_never_samples_when_rate_zero(self):
        from agent.eval.sampler import should_sample

        # High-confidence, non-degraded, no force_rag: rate 0 => never.
        assert should_sample({"intent_confidence": 0.9}, "rag", sample_rate=0.0) is False

    def test_samples_when_rate_one(self):
        from agent.eval.sampler import should_sample

        assert should_sample({"intent_confidence": 0.9}, "rag", sample_rate=1.0) is True


# ---------------------------------------------------------------------------
# InferenceStore
# ---------------------------------------------------------------------------


class TestInferenceStore:
    def test_record_and_get(self, tmp_path):
        from agent.eval.inference_store import InferenceRecord, InferenceStore

        store = InferenceStore(str(tmp_path / "inf.db"))
        rec = InferenceRecord(
            trace_id="t1",
            message_id="m1",
            session_id="s1",
            query="git 合并冲突如何解决？",
            retrieved_docs=[{"source": "docA", "content": "合并冲突排查要点"}],
            answer="需手动编辑冲突标记后提交。",
            route="rag",
            prompt_profile="general_v1",
            intent="rag_query",
            latency_ms=123.4,
        )
        tid = store.record(rec)
        assert tid == "t1"

        got = store.get("t1")
        assert got is not None
        assert got.query == "git 合并冲突如何解决？"
        assert got.route == "rag"
        assert len(got.retrieved_docs) == 1
        assert got.retrieved_docs[0]["source"] == "docA"

        # message_id lookup
        assert store.get_by_message("m1").trace_id == "t1"
        # session lookup
        rows = store.get_by_session("s1")
        assert len(rows) == 1

        store.close()

    def test_stats(self, tmp_path):
        from agent.eval.inference_store import InferenceRecord, InferenceStore

        store = InferenceStore(str(tmp_path / "inf.db"))
        store.record(InferenceRecord(trace_id="t1", route="rag", query="q1"))
        store.record(InferenceRecord(trace_id="t2", route="fast", query="q2"))
        s = store.stats()
        assert s["total"] == 2
        assert s["by_route"].get("rag") == 1
        store.close()


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


class TestCandidates:
    def test_promote_and_list_and_golden(self, tmp_path, monkeypatch):
        from agent.eval import candidates as cand_mod
        from agent.eval.inference_store import InferenceRecord

        # Redirect candidate dir + dataset to tmp.
        monkeypatch.setattr(cand_mod, "CANDIDATES_DIR", tmp_path / "cands")
        dataset_path = str(tmp_path / "golden.yaml")
        Path(dataset_path).write_text("cases: []\n", encoding="utf-8")

        inference = InferenceRecord(
            trace_id="t1",
            message_id="m1",
            session_id="s1",
            query="docker 容器无法启动如何排查？",
            answer="容器启动失败。",
            retrieved_docs=[{"source": "docker_doc", "content": "容器日志"}],
        )

        # Correction: corrected_answer becomes the golden reference.
        cand = cand_mod.promote_to_candidate(
            inference,
            feedback_type="correction",
            corrected_answer="需查看容器日志定位失败原因。",
        )
        assert cand is not None
        assert cand.corrected_answer.startswith("需查看")

        listed = cand_mod.list_candidates()
        assert len(listed) == 1
        assert listed[0].feedback_type == "correction"

        # Promote to golden dataset.
        promoted = cand_mod.promote_candidate_to_golden(
            cand.candidate_id, dataset_path=dataset_path
        )
        assert promoted is not None
        assert promoted.reference_answer.startswith("需查看")

        # Candidate file is consumed after promotion.
        assert cand_mod.list_candidates() == []

        # Dataset now has the case.
        from agent.eval.dataset import load_dataset

        loaded = load_dataset(dataset_path)
        assert any(c.reference_answer.startswith("需查看") for c in loaded)

    def test_promote_skips_empty_query(self, tmp_path, monkeypatch):
        from agent.eval import candidates as cand_mod
        from agent.eval.inference_store import InferenceRecord

        monkeypatch.setattr(cand_mod, "CANDIDATES_DIR", tmp_path / "cands")
        inference = InferenceRecord(trace_id="t1", query="", answer="x")
        assert cand_mod.promote_to_candidate(inference, "flag") is None


# ---------------------------------------------------------------------------
# Flywheel trigger (judge stubbed)
# ---------------------------------------------------------------------------


class TestFlywheel:
    def test_on_negative_feedback_promotes_and_records_miss(self, tmp_path, monkeypatch):
        from agent.eval import candidates as cand_mod
        from agent.eval import flywheel as fw_mod
        from agent.eval.inference_store import InferenceRecord, InferenceStore
        from agent.eval.judge import TrustworthyMetrics

        # Isolated stores.
        monkeypatch.setattr(cand_mod, "CANDIDATES_DIR", tmp_path / "cands")
        monkeypatch.setattr(fw_mod, "RETRIEVAL_MISSES_DB", str(tmp_path / "misses.db"))

        store = InferenceStore(str(tmp_path / "inf.db"))
        store.record(
            InferenceRecord(
                trace_id="t1",
                message_id="m1",
                session_id="s1",
                query="git 分支冲突如何处理？",
                answer="必须立即回滚提交。",
                retrieved_docs=[{"source": "doc", "content": "建议进一步检查"}],
                route="rag",
            )
        )
        monkeypatch.setattr(fw_mod, "get_inference_store", lambda: store)

        # Stub the judge: faithfulness low => triggers retrieval-miss recording.
        metrics = TrustworthyMetrics(
            faithfulness=0.2,
            answer_relevancy=0.5,
            hallucination_score=0.8,
            context_precision=0.3,
            judge_used=True,
        )

        class _StubJudge:
            available = True

            def evaluate(self, **kw):
                return metrics

        import agent.eval.flywheel as fly

        monkeypatch.setattr(fly, "get_judge", lambda: _StubJudge())

        try:
            result = fly.on_negative_feedback(
                trace_id="t1",
                message_id="m1",
                feedback_type="thumbs_down",
            )
            assert result["promoted"] is True
            assert result["judge_run"] is True
            assert result["miss_recorded"] is True

            # A retrieval miss row was written.
            misses = fly.get_retrieval_misses()
            assert len(misses) == 1
            assert misses[0]["faithfulness"] == 0.2
        finally:
            store.close()

    def test_missing_inference_returns_error(self, tmp_path, monkeypatch):
        from agent.eval import flywheel as fly
        from agent.eval.inference_store import InferenceStore

        store = InferenceStore(str(tmp_path / "inf.db"))
        monkeypatch.setattr(fly, "get_inference_store", lambda: store)

        try:
            result = fly.on_negative_feedback(
                trace_id="nonexistent", message_id="", feedback_type="flag"
            )
            assert result["promoted"] is False
            assert "no matching inference" in (result["error"] or "")
        finally:
            store.close()


# ---------------------------------------------------------------------------
# Capture helper (sampler + store integration)
# ---------------------------------------------------------------------------


class TestCapture:
    def test_maybe_capture_writes_ids_into_metadata(self, tmp_path, monkeypatch):
        from agent.eval import capture as cap_mod
        from agent.eval.inference_store import InferenceStore

        store = InferenceStore(str(tmp_path / "inf.db"))
        monkeypatch.setattr(cap_mod, "get_inference_store", lambda: store)
        # Force sampling on.
        monkeypatch.setattr(cap_mod, "should_sample", lambda *a, **k: True)
        monkeypatch.setattr(cap_mod, "_cached_commit", lambda: "deadbeef")

        meta: dict = {}
        try:
            tid = cap_mod.maybe_capture_inference(
                request_message="q",
                answer="a",
                sources=[],
                reasoning="",
                route="rag",
                prompt_profile="p",
                intent="rag_query",
                metadata=meta,
                latency_ms=10.0,
                trace_id="trace1",
                session_id="s1",
            )
            assert tid == "trace1"
            assert meta["trace_id"] == "trace1"
            assert bool(meta["message_id"])
        finally:
            store.close()

    def test_maybe_capture_skips_when_not_sampled(self, tmp_path, monkeypatch):
        from agent.eval import capture as cap_mod
        from agent.eval.inference_store import InferenceStore

        store = InferenceStore(str(tmp_path / "inf.db"))
        monkeypatch.setattr(cap_mod, "get_inference_store", lambda: store)
        monkeypatch.setattr(cap_mod, "should_sample", lambda *a, **k: False)

        meta: dict = {}
        try:
            tid = cap_mod.maybe_capture_inference(
                request_message="q",
                answer="a",
                sources=[],
                reasoning="",
                route="rag",
                prompt_profile="p",
                intent="rag_query",
                metadata=meta,
                latency_ms=1.0,
                trace_id="t",
                session_id="s",
            )
            assert tid is None
        finally:
            store.close()
        # metadata untouched when not sampled.
        assert "trace_id" not in meta


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
