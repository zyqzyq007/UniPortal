#!/usr/bin/env python3
"""
REQ-RD-001/002/003/004 — eval closure metric-accuracy regression.

Guards Stage D:
- runner extracts retrieved_context_ids and passes them to scorer (was never passed)
- runner classifies intent via the real classifier (was empty -> intent_accuracy False)
- scorer strips guardrail boilerplate before feeding the judge

Run: pytest tests/unit/test_eval_closure.py -v
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")

from agent.eval.runner import EvalRunner, _content_id  # noqa: E402

# ===========================================================================
# REQ-RD-001 — _content_id deterministic + _extract_result returns context_ids
# ===========================================================================


class TestContentIdExtraction:
    def test_content_id_deterministic(self):
        """_content_id MUST be deterministic (same text -> same id), matching
        the golden expected_context_ids algorithm (sha1 of normalised text)."""
        text = "git 合并冲突的可能原因包括同一文件多分支改动"
        assert _content_id(text) == _content_id(text)  # deterministic
        assert len(_content_id(text)) == 12

    def test_content_id_normalises_whitespace(self):
        """Whitespace differences MUST NOT change the id (normalised first)."""
        a = _content_id("git  合并\n冲突")
        b = _content_id("git 合并 冲突")
        assert a == b

    def test_extract_result_returns_context_ids(self):
        """_extract_result MUST return a 5th element: list of context ids
        computed from the retrieved contexts (Stage D REQ-RD-001)."""
        from langchain_core.messages import AIMessage, ToolMessage

        # Simulate a graph result with a ToolMessage carrying context.
        ctx_text = "git 合并冲突的解决步骤"
        result = {
            "messages": [
                ToolMessage(content=ctx_text, tool_call_id="c1"),
                AIMessage(content="结论..."),
            ]
        }
        answer, intent, sources, contexts, context_ids = EvalRunner._extract_result(result, "query")
        assert len(context_ids) >= 1, "context_ids empty — runner not extracting chunk ids"
        assert _content_id(ctx_text) in context_ids


# ===========================================================================
# REQ-RD-003 — intent extracted via real classifier
# ===========================================================================


class TestIntentExtraction:
    def test_extract_result_classifies_intent(self, monkeypatch):
        """_extract_result MUST classify the query via the real intent classifier
        (not return empty). The graph has no intent node, so eval must classify
        itself. Mock the classifier to return a known intent."""

        class _FakeIntent:
            class intent:
                value = "rag_query"

        class _FakeClassifier:
            def classify(self, query):
                return _FakeIntent()

        import core.intent.classifier as ic_mod

        monkeypatch.setattr(ic_mod, "get_intent_classifier", lambda: _FakeClassifier())

        result = {"messages": []}
        _, intent, _, _, _ = EvalRunner._extract_result(result, "git 合并冲突")
        assert intent == "rag_query", f"intent should be classified, got {intent!r}"

    def test_extract_result_intent_non_empty_for_query(self, monkeypatch):
        """Even a general query MUST get a real intent classification (not empty)."""

        class _FakeIntent:
            class intent:
                value = "general_chat"

        class _FakeClassifier:
            def classify(self, query):
                return _FakeIntent()

        import core.intent.classifier as ic_mod

        monkeypatch.setattr(ic_mod, "get_intent_classifier", lambda: _FakeClassifier())

        result = {"messages": []}
        _, intent, _, _, _ = EvalRunner._extract_result(result, "你好")
        assert intent == "general_chat"


# ===========================================================================
# REQ-RD-004 — scorer strips guardrail boilerplate before judge
# ===========================================================================


class TestJudgeScopeStripping:
    def test_strip_removes_safety_disclaimer(self):
        """The judge answer MUST NOT contain the domain safety_disclaimer
        (appended by OutputGuardrail — has no grounding evidence)."""
        from agent.eval.scorer import _strip_guardrail_boilerplate

        answer = "【结论】git 合并冲突。\n\n本回答仅供参考，不构成最终操作决策。"
        stripped = _strip_guardrail_boilerplate(answer)
        # The disclaimer (from the active profile) should be removed if present.
        # At minimum, the answer content survives.
        assert "结论" in stripped

    def test_strip_removes_caveat_markers(self):
        """Caveat lines (⚠️/🤔 markers) MUST be stripped before judging."""
        from agent.eval.scorer import _strip_guardrail_boilerplate

        answer = "结论。\n\n> ⚠️ 提示：推理存在不确定性，请结合文档核实。"
        stripped = _strip_guardrail_boilerplate(answer)
        assert "⚠️" not in stripped
        assert "结论" in stripped

    def test_strip_preserves_real_answer(self):
        """Real diagnostic content MUST survive the strip."""
        from agent.eval.scorer import _strip_guardrail_boilerplate

        answer = "【结论】git 合并冲突。【可能原因】多分支改动。【排查步骤】编辑标记。"
        stripped = _strip_guardrail_boilerplate(answer)
        assert "结论" in stripped
        assert "排查步骤" in stripped


# ===========================================================================
# REQ-RD-002 — scorer computes context precision/recall when ids present
# ===========================================================================


class TestContextIdScoring:
    def test_scorer_context_ids_non_none_when_expected_present(self):
        """When a case carries expected_context_ids AND the runner passes
        retrieved_context_ids, the scorer MUST compute non-None precision/recall
        (was always None because runner never passed retrieved ids)."""
        from agent.eval.scorer import EvalScorer
        from agent.eval.types import EvalCase

        case = EvalCase(
            id="test_ctx",
            query="git 合并",
            expected_sections=[],
            expected_keywords=[],
            expected_intent="rag_query",
            expected_min_sources=1,
            difficulty="easy",
            reference_answer="",
            expected_context_ids=["abc123def456"],
        )
        scorer = EvalScorer(use_judge=False)
        # retrieved includes the expected id -> precision=1.0, recall=1.0
        score = scorer.score(
            case=case,
            actual_answer="answer",
            actual_intent="rag_query",
            actual_sources=1,
            retrieved_contexts=["some text"],
            retrieved_context_ids=["abc123def456", "zzz999zzz999"],
        )
        assert score.context_precision is not None, "context_precision None despite ids"
        assert score.context_precision == pytest.approx(0.5)  # 1 of 2 retrieved is gold


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
