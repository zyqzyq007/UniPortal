#!/usr/bin/env python3
"""
Unit tests for the evaluation flywheel (judge parsing, scorer blending,
runner extraction, history/regression). These do NOT invoke the real LLM —
the judge is stubbed.

Run: pytest tests/unit/test_eval.py -v
"""

from __future__ import annotations

import json
import os
import sys

import pytest

# Add project root to path
sys.path.insert(0, ".")


# ---------------------------------------------------------------------------
# Judge: JSON / boolean parsing (no LLM involved)
# ---------------------------------------------------------------------------


class TestJudgeParsing:
    def test_extract_json_strict(self):
        from agent.eval.judge import _extract_json

        assert _extract_json('{"supported": true, "rationale": "ok"}') == {
            "supported": True,
            "rationale": "ok",
        }

    def test_extract_json_from_prose(self):
        from agent.eval.judge import _extract_json

        # Judge wraps JSON in prose.
        text = '根据分析：\n{"supported": false, "rationale": "未提及"}\n以上。'
        out = _extract_json(text)
        assert out is not None
        assert out["supported"] is False

    def test_extract_json_code_fence(self):
        from agent.eval.judge import _extract_json

        text = '```json\n{"supported": true}\n```'
        out = _extract_json(text)
        assert out is not None
        assert out["supported"] is True

    def test_extract_json_trailing_comma(self):
        from agent.eval.judge import _extract_json

        text = '{"supported": true, "rationale": "x",}'
        out = _extract_json(text)
        assert out is not None
        assert out["supported"] is True

    def test_extract_json_garbage_returns_none(self):
        from agent.eval.judge import _extract_json

        assert _extract_json("not json at all") is None
        assert _extract_json("") is None

    def test_parse_bool_yes(self):
        from agent.eval.judge import _parse_bool_answer

        assert _parse_bool_answer("Yes, supported.") is True
        assert _parse_bool_answer("支持该声明") is True
        assert _parse_bool_answer('{"supported": true}') is True

    def test_parse_bool_no(self):
        from agent.eval.judge import _parse_bool_answer

        assert _parse_bool_answer("No, not supported.") is False
        assert _parse_bool_answer("未支持") is False
        assert _parse_bool_answer('{"supported": false}') is False

    def test_parse_bool_default(self):
        from agent.eval.judge import _parse_bool_answer

        assert _parse_bool_answer("ambiguous text", default=True) is True
        assert _parse_bool_answer("", default=False) is False


# ---------------------------------------------------------------------------
# Judge: claim splitting + hard-claim detection
# ---------------------------------------------------------------------------


class TestClaimExtraction:
    def test_split_claims_basic(self):
        from agent.eval.judge import split_claims

        text = "结论：合并冲突。步骤1：查看状态；步骤2：编辑标记。"
        claims = split_claims(text)
        assert len(claims) >= 2
        # Section markers stripped.
        assert all("【" not in c for c in claims)

    def test_split_claims_numbering(self):
        from agent.eval.judge import split_claims

        text = "1) 检查容器日志 2) 测量响应时间 3) 重启服务进程"
        claims = split_claims(text)
        assert len(claims) == 3
        # Numbering should be stripped, content retained.
        assert all("检查" in c or "测量" in c or "重启" in c for c in claims)

    def test_split_claims_empty(self):
        from agent.eval.judge import split_claims

        assert split_claims("") == []
        assert split_claims("。；。") == []

    def test_is_hard_claim_value(self):
        from agent.eval.judge import is_hard_claim

        assert is_hard_claim("超时阈值应为 30 秒")
        assert is_hard_claim("并发不超过 1000")
        assert is_hard_claim("【结论】必须重启服务")

    def test_is_not_hard_claim(self):
        from agent.eval.judge import is_hard_claim

        assert not is_hard_claim("请进一步检查")
        assert not is_hard_claim("这是一个普通描述")


# ---------------------------------------------------------------------------
# Scorer: rule-based path (no judge)
# ---------------------------------------------------------------------------


class TestScorer:
    def test_rule_based_scoring(self):
        from agent.eval.scorer import EvalScorer
        from agent.eval.types import EvalCase

        case = EvalCase(
            id="t1",
            query="git 合并冲突如何解决？",
            expected_sections=["结论", "步骤"],
            expected_keywords=["合并", "冲突"],
            expected_intent="rag_query",
            expected_min_sources=1,
        )
        scorer = EvalScorer(use_judge=False)
        answer = "【结论】合并冲突。需编辑冲突标记。"
        score = scorer.score(case, answer, "rag_query", 2, [])

        assert score.judge_used is False
        assert score.faithfulness is None
        # section: 1/2 covered (结论 present, 步骤 absent) = 0.5
        assert 0.0 < score.section_coverage <= 1.0
        assert score.overall_score > 0.0

    def test_rule_based_perfect(self):
        from agent.eval.scorer import EvalScorer
        from agent.eval.types import EvalCase

        case = EvalCase(
            id="t2",
            query="q",
            expected_sections=["结论"],
            expected_keywords=["合并"],
            expected_intent="rag_query",
            expected_min_sources=1,
        )
        scorer = EvalScorer(use_judge=False)
        score = scorer.score(case, "【结论】合并问题", "rag_query", 1, [])
        assert score.overall_score == pytest.approx(1.0)

    def test_composite_with_judge_metrics(self):
        """When judge metrics are present, they dominate the composite."""
        from agent.eval.scorer import EvalScorer
        from agent.eval.types import EvalCase, EvalScore

        scorer = EvalScorer(use_judge=False)
        # Manually exercise _composite with judge-style scores.
        s = EvalScore(
            section_coverage=0.5,
            keyword_coverage=0.5,
            intent_accuracy=True,
            source_count_ok=True,
            faithfulness=0.9,
            answer_relevancy=0.9,
            hallucination_score=0.0,
            context_precision=0.9,
            context_recall=0.9,
            judge_used=True,
        )
        # rule_component = 0.5*0.3 + 0.5*0.3 + 1*0.2 + 1*0.2 = 0.7
        blended = scorer._composite(0.7, s)
        # High judge metrics should pull the score up above pure rule.
        assert blended > 0.7
        assert blended <= 1.0

    def test_hallucination_penalizes(self):
        from agent.eval.scorer import EvalScorer
        from agent.eval.types import EvalScore

        scorer = EvalScorer(use_judge=False)
        s_good = EvalScore(
            faithfulness=0.9,
            answer_relevancy=0.9,
            context_precision=0.9,
            judge_used=True,
        )
        s_bad = EvalScore(
            faithfulness=0.9,
            answer_relevancy=0.9,
            context_precision=0.9,
            hallucination_score=1.0,  # fully unsupported
            judge_used=True,
        )
        good = scorer._composite(0.7, s_good)
        bad = scorer._composite(0.7, s_bad)
        assert bad < good


# ---------------------------------------------------------------------------
# Runner: result extraction (no LLM)
# ---------------------------------------------------------------------------


class TestRunnerExtraction:
    def test_extract_result_full_graph(self):
        from langchain_core.messages import AIMessage, ToolMessage

        from agent.eval.runner import EvalRunner

        result = {
            "messages": [
                ToolMessage(
                    content="Source: git_doc\nTitle: 合并\n合并冲突排查要点...",
                    tool_call_id="call_1",
                ),
                ToolMessage(
                    content="Source: docker_doc\n容器启动排查步骤...",
                    tool_call_id="call_2",
                ),
                AIMessage(content="【结论】合并冲突，建议编辑标记。"),
            ]
        }
        answer, intent, sources, contexts, context_ids = EvalRunner._extract_result(result)
        assert "合并冲突" in answer
        assert sources == 2
        assert len(contexts) == 2
        assert len(context_ids) == 2  # Stage D: ids extracted from contexts

    def test_extract_result_fast_mode(self):
        from agent.eval.runner import EvalRunner

        result = {
            "messages": [],
            "_fast_mode": True,
            "_sources": [
                {"source": "doc1", "content": "片段1"},
                {"source": "doc2", "content": "片段2"},
                {"source": "doc3", "content": "片段3"},
            ],
        }
        answer, intent, sources, contexts, context_ids = EvalRunner._extract_result(result)
        assert sources == 3
        assert intent == "rag_query"
        assert len(contexts) == 3

    def test_extract_result_empty(self):
        from agent.eval.runner import EvalRunner

        answer, intent, sources, contexts, context_ids = EvalRunner._extract_result(None)
        assert answer == ""
        assert sources == 0
        assert contexts == []
        assert context_ids == []


# ---------------------------------------------------------------------------
# Judge: faithfulness / hallucination with a stubbed LLM
# ---------------------------------------------------------------------------


class TestStubbedJudge:
    """Stub the judge's _ask to return canned verdicts."""

    def _make_judge(self, monkeypatch, responses, tmp_path):
        from agent.eval.judge import LLMJudge

        judge = LLMJudge(cache_path=str(tmp_path / "test_judge_cache.db"))
        judge._failures._tripped = False  # ensure available
        calls = list(responses)

        def fake_ask(prompt):
            return calls.pop(0) if calls else '{"supported": true}'

        monkeypatch.setattr(judge, "_ask", fake_ask)
        return judge

    def test_faithfulness_all_supported(self, monkeypatch, tmp_path):
        judge = self._make_judge(monkeypatch, ['{"supported": true}'], tmp_path)
        try:
            score, note = judge.faithfulness(
                "合并冲突需编辑标记。",
                ["文档说明合并冲突时需编辑标记。"],
            )
            assert score == 1.0
        finally:
            judge.close()

    def test_faithfulness_none_supported(self, monkeypatch, tmp_path):
        # Two claims -> two "not supported" responses.
        judge = self._make_judge(
            monkeypatch,
            ['{"supported": false}', '{"supported": false}'],
            tmp_path,
        )
        try:
            score, note = judge.faithfulness(
                "合并冲突。需回滚提交。",
                ["文档仅提到分支管理。"],
            )
            assert score == 0.0
        finally:
            judge.close()

    def test_hallucination_no_hard_claims(self, monkeypatch, tmp_path):
        judge = self._make_judge(monkeypatch, [], tmp_path)
        try:
            # Soft claim only -> 0 hallucination without calling the LLM.
            score, note = judge.hallucination_score(
                "请进一步检查。",
                ["context"],
            )
            assert score == 0.0
        finally:
            judge.close()

    def test_circuit_breaker_trips(self, monkeypatch, tmp_path):
        from agent.eval.judge import LLMJudge

        judge = LLMJudge(cache_path=str(tmp_path / "test_judge_cache.db"), failure_threshold=2)

        def always_fail(prompt):
            raise RuntimeError("LLM down")

        # Force the lazy llm to raise via patching _get_llm.
        monkeypatch.setattr(judge, "_get_llm", always_fail)
        try:
            # First failure
            assert judge._ask("p1") is None
            assert judge.available
            # Second failure -> trips
            assert judge._ask("p2") is None
            assert not judge.available
            # Once tripped, evaluate returns judge_used=False
            m = judge.evaluate("q", "a", ["c"])
            assert m.judge_used is False
        finally:
            judge.close()


# ---------------------------------------------------------------------------
# History: regression comparison
# ---------------------------------------------------------------------------


class TestRegression:
    def test_no_regression_when_improving(self):
        from agent.eval.history import compare_runs
        from agent.eval.types import EvalRunSummary

        baseline = EvalRunSummary(
            run_id="b1",
            average_score=0.7,
            avg_faithfulness=0.7,
            avg_answer_relevancy=0.7,
            avg_context_precision=0.7,
            avg_context_recall=0.7,
            avg_hallucination=0.1,
        )
        current = EvalRunSummary(
            run_id="c1",
            average_score=0.8,
            avg_faithfulness=0.8,
            avg_answer_relevancy=0.8,
            avg_context_precision=0.8,
            avg_context_recall=0.8,
            avg_hallucination=0.05,
        )
        reg = compare_runs(baseline, current)
        assert reg.passed is True
        assert len(reg.regressions) == 0

    def test_regression_on_faithfulness_drop(self):
        from agent.eval.history import compare_runs
        from agent.eval.types import EvalRunSummary

        baseline = EvalRunSummary(
            run_id="b1",
            average_score=0.8,
            avg_faithfulness=0.85,
            avg_answer_relevancy=0.8,
            avg_context_precision=0.8,
            avg_context_recall=0.8,
            avg_hallucination=0.05,
        )
        current = EvalRunSummary(
            run_id="c1",
            average_score=0.8,
            avg_faithfulness=0.70,  # dropped 0.15 -> beyond 0.05 threshold
            avg_answer_relevancy=0.8,
            avg_context_precision=0.8,
            avg_context_recall=0.8,
            avg_hallucination=0.05,
        )
        reg = compare_runs(baseline, current)
        assert reg.passed is False
        assert any(d.metric == "avg_faithfulness" for d in reg.regressions)

    def test_regression_on_hallucination_increase(self):
        from agent.eval.history import compare_runs
        from agent.eval.types import EvalRunSummary

        baseline = EvalRunSummary(
            run_id="b1",
            average_score=0.8,
            avg_hallucination=0.05,
        )
        current = EvalRunSummary(
            run_id="c1",
            average_score=0.8,
            avg_hallucination=0.20,  # increased 0.15 -> regression
        )
        reg = compare_runs(baseline, current)
        assert reg.passed is False


# ---------------------------------------------------------------------------
# Dataset: load + append
# ---------------------------------------------------------------------------


class TestDataset:
    def test_load_default_dataset(self):
        from agent.eval.dataset import load_dataset

        cases = load_dataset()
        assert len(cases) >= 15
        # All seed cases have ids.
        assert all(c.id for c in cases)
        # Reference answers present on non-edge cases.
        ref = [c for c in cases if c.reference_answer.strip()]
        assert len(ref) >= 10

    def test_load_missing_returns_empty(self, tmp_path):
        from agent.eval.dataset import load_dataset

        assert load_dataset(str(tmp_path / "nope.yaml")) == []

    def test_append_then_load(self, tmp_path):
        from agent.eval.dataset import append_cases, load_dataset
        from agent.eval.types import EvalCase

        path = str(tmp_path / "ds.yaml")
        # Seed with an empty dataset.
        with open(path, "w", encoding="utf-8") as f:
            f.write("cases: []\n")

        new = [
            EvalCase(id="x1", query="q1", reference_answer="r1", source="feedback"),
            EvalCase(id="x2", query="q2", reference_answer="r2", source="correction"),
        ]
        n = append_cases(path, new)
        assert n == 2
        # Duplicate id is skipped.
        n2 = append_cases(path, [EvalCase(id="x1", query="dup")])
        assert n2 == 0

        loaded = load_dataset(path)
        ids = {c.id for c in loaded}
        assert {"x1", "x2"} <= ids


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
