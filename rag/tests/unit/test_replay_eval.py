#!/usr/bin/env python3
"""
Unit tests for the offline replay evaluator and judge graceful-degradation
semantics (LLM-down => None, not 0).

Run: pytest tests/unit/test_replay_eval.py -v
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, ".")


# ---------------------------------------------------------------------------
# JSONL loading + record-to-case conversion
# ---------------------------------------------------------------------------


class TestReplayLoading:
    def test_load_jsonl_skips_comments_and_blanks(self, tmp_path):
        from scripts.replay_eval import load_replay_records

        path = tmp_path / "ds.jsonl"
        path.write_text(
            "# header comment\n"
            "\n"
            '{"id":"r1","query":"q1","answer":"a1"}\n'
            "   \n"
            '{"id":"r2","query":"q2","answer":"a2"}\n',
            encoding="utf-8",
        )
        recs = load_replay_records(str(path))
        assert len(recs) == 2
        assert recs[0]["id"] == "r1"

    def test_load_skips_malformed_lines(self, tmp_path):
        from scripts.replay_eval import load_replay_records

        path = tmp_path / "ds.jsonl"
        path.write_text(
            '{"id":"r1","query":"q1"}\nthis is not json\n{"id":"r2","query":"q2"}\n',
            encoding="utf-8",
        )
        recs = load_replay_records(str(path))
        assert len(recs) == 2  # malformed line skipped

    def test_load_missing_file_raises(self, tmp_path):
        from scripts.replay_eval import load_replay_records

        with pytest.raises(FileNotFoundError):
            load_replay_records(str(tmp_path / "nope.jsonl"))

    def test_record_to_case_string_and_dict_contexts(self):
        from scripts.replay_eval import record_to_case

        # contexts as plain strings
        case, ctxs = record_to_case(
            {
                "id": "x",
                "query": "q",
                "answer": "a",
                "contexts": ["c1", "c2"],
                "reference_answer": "ref",
            }
        )
        assert case.id == "x"
        assert case.reference_answer == "ref"
        assert ctxs == ["c1", "c2"]
        # No rule-based expectations => they default empty.
        assert case.expected_sections == []

    def test_record_to_case_dict_contexts_normalized(self):
        from scripts.replay_eval import record_to_case

        case, ctxs = record_to_case(
            {
                "id": "x",
                "query": "q",
                "answer": "a",
                "contexts": [
                    {"content": "dict-ctx", "source": "doc"},
                    {"text": "alt-key"},
                    "plain string",
                    {"content": "   "},  # whitespace-only -> dropped
                ],
            }
        )
        assert ctxs == ["dict-ctx", "alt-key", "plain string"]


# ---------------------------------------------------------------------------
# Offline evaluation (rule-based, no LLM) — proves pure-data path works
# ---------------------------------------------------------------------------


class TestReplayOffline:
    def test_score_record_no_judge(self):
        from agent.eval.scorer import EvalScorer
        from scripts.replay_eval import ReplayEvaluator

        ev = ReplayEvaluator(scorer=EvalScorer(use_judge=False))
        rec = {
            "id": "r1",
            "query": "git 合并冲突如何解决？",
            "answer": "需编辑冲突标记后提交。",
            "contexts": ["文档说合并冲突需编辑标记。"],
            "reference_answer": "需编辑冲突标记。",
            "intent": "rag_query",
        }
        result = ev.score_record(rec)
        assert result.case_id == "r1"
        assert result.error is None
        assert result.score.judge_used is False
        # Rule-based overall is computable without the judge.
        assert 0.0 <= result.score.overall_score <= 1.0
        # Trustworthy metrics absent when judge off.
        assert result.score.faithfulness is None

    def test_score_all_no_judge(self):
        import asyncio

        from agent.eval.scorer import EvalScorer
        from scripts.replay_eval import ReplayEvaluator

        ev = ReplayEvaluator(scorer=EvalScorer(use_judge=False))
        records = [
            {"id": f"r{i}", "query": f"q{i}", "answer": f"a{i}", "contexts": []} for i in range(5)
        ]
        report = asyncio.run(ev.score_all_async(records, concurrency=2))
        assert report.total_cases == 5
        assert all(r.error is None for r in report.results)


# ---------------------------------------------------------------------------
# Judge graceful degradation: LLM-down => None (not 0), no crash
# ---------------------------------------------------------------------------


class TestJudgeDegradation:
    def _make_judge_with_dead_llm(self, monkeypatch, tmp_path):
        from agent.eval.judge import LLMJudge

        judge = LLMJudge(cache_path=str(tmp_path / "test_degrade_cache.db"))
        judge._failures._tripped = False

        def dead_llm():
            raise RuntimeError("LLM unreachable")

        monkeypatch.setattr(judge, "_get_llm", dead_llm)
        return judge

    def test_faithfulness_none_when_llm_down(self, monkeypatch, tmp_path):
        judge = self._make_judge_with_dead_llm(monkeypatch, tmp_path)
        try:
            score, note = judge.faithfulness(
                "合并冲突需编辑标记。需查看状态。",
                ["文档说明合并冲突时需编辑标记。"],
            )
            assert score is None
            assert "unavailable" in note or "无法判定" in note
        finally:
            judge.close()

    def test_hallucination_none_when_llm_down(self, monkeypatch, tmp_path):
        judge = self._make_judge_with_dead_llm(monkeypatch, tmp_path)
        try:
            # Hard claim (contains a value) but LLM down => None.
            score, note = judge.hallucination_score(
                "超时应为 30 秒。",
                ["context"],
            )
            assert score is None
        finally:
            judge.close()

    def test_context_recall_none_when_llm_down(self, monkeypatch, tmp_path):
        judge = self._make_judge_with_dead_llm(monkeypatch, tmp_path)
        try:
            score, note = judge.context_recall(
                "参考答案声明一。声明二。",
                ["context"],
            )
            assert score is None
        finally:
            judge.close()

    def test_context_precision_none_when_llm_down(self, monkeypatch, tmp_path):
        judge = self._make_judge_with_dead_llm(monkeypatch, tmp_path)
        try:
            score, note = judge.context_precision("q", ["c1", "c2"])
            assert score is None
        finally:
            judge.close()

    def test_evaluate_returns_judge_used_false_after_circuit(self, monkeypatch, tmp_path):
        judge = self._make_judge_with_dead_llm(monkeypatch, tmp_path)
        try:
            # Force trips by repeated failures.
            for _ in range(6):
                judge._ask("p")
            m = judge.evaluate("q", "答案为超时 30 秒。", ["context"], reference_answer="ref")
            assert m.judge_used is False
            # answer_relevancy uses local embeddings, not the LLM — it can still
            # produce a value even with the circuit open. The NLI metrics must be None.
            assert m.faithfulness is None
            assert m.hallucination_score is None
            assert m.context_recall is None
        finally:
            judge.close()


# ---------------------------------------------------------------------------
# End-to-end: CLI with --no-judge runs fully offline
# ---------------------------------------------------------------------------


class TestReplayCLI:
    def test_no_judge_runs_offline(self, tmp_path, capsys):
        import asyncio

        from agent.eval.scorer import EvalScorer
        from scripts.replay_eval import ReplayEvaluator

        # Write a tiny dataset.
        ds = tmp_path / "ds.jsonl"
        ds.write_text(
            '{"id":"r1","query":"q1","answer":"a1","contexts":["c1"]}\n',
            encoding="utf-8",
        )
        ev = ReplayEvaluator(scorer=EvalScorer(use_judge=False))
        records = [{"id": "r1", "query": "q1", "answer": "a1", "contexts": ["c1"]}]
        report = asyncio.run(ev.score_all_async(records, concurrency=1))
        assert report.total_cases == 1
        assert report.results[0].error is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
