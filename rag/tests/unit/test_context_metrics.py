#!/usr/bin/env python3
"""
Context-metric + benchmark-loader unit tests (C-phase).

Verifies:
- Deterministic context precision/recall (set-overlap, no LLM) — REQ-C-003.
- The builtin general benchmark dataset loads and every case carries
  expected_context_ids — REQ-C-002/C-005.

Run: uv run --frozen python -m pytest tests/unit/test_context_metrics.py -v
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")


# ===========================================================================
# Deterministic context precision / recall (REQ-C-003)
# ===========================================================================


class TestContextMetrics:
    def test_perfect_overlap(self):
        from agent.eval.scorer import EvalScorer

        p, r = EvalScorer.score_context_ids(["a", "b"], ["a", "b"])
        assert p == 1.0
        assert r == 1.0

    def test_partial_overlap(self):
        from agent.eval.scorer import EvalScorer

        # expected {a,b}, retrieved {a,c,d} -> overlap {a}
        p, r = EvalScorer.score_context_ids(["a", "b"], ["a", "c", "d"])
        assert p == pytest.approx(1 / 3)  # 1 of 3 retrieved relevant
        assert r == 0.5  # 1 of 2 expected retrieved

    def test_no_overlap(self):
        from agent.eval.scorer import EvalScorer

        p, r = EvalScorer.score_context_ids(["a", "b"], ["c", "d"])
        assert p == 0.0
        assert r == 0.0

    def test_no_expected_returns_none(self):
        """Cases without ground-truth ids must not pollute the metric."""
        from agent.eval.scorer import EvalScorer

        p, r = EvalScorer.score_context_ids([], ["a", "b"])
        assert p is None
        assert r is None

    def test_nothing_retrieved(self):
        """Retrieved empty: precision undefined, recall 0 (missed all)."""
        from agent.eval.scorer import EvalScorer

        p, r = EvalScorer.score_context_ids(["a", "b"], [])
        assert p is None
        assert r == 0.0

    def test_retrieved_superset(self):
        from agent.eval.scorer import EvalScorer

        # expected {a}, retrieved {a,b,c} -> recall 1.0, precision 1/3
        p, r = EvalScorer.score_context_ids(["a"], ["a", "b", "c"])
        assert p == pytest.approx(1 / 3)
        assert r == 1.0

    def test_scorer_score_populates_context_dims(self):
        """End-to-end: EvalScorer.score fills context_precision/recall from ids."""
        from agent.eval.scorer import EvalScorer
        from agent.eval.types import EvalCase

        case = EvalCase(
            id="t1",
            query="q",
            expected_context_ids=["a", "b"],
        )
        scorer = EvalScorer(use_judge=False)
        score = scorer.score(
            case,
            actual_answer="ans",
            actual_intent="rag_query",
            actual_sources=1,
            retrieved_context_ids=["a", "c"],
        )
        assert score.context_precision == pytest.approx(0.5)  # 1 of 2 retrieved
        assert score.context_recall == 0.5  # 1 of 2 expected

    def test_scorer_score_without_expected_ids_stays_none(self):
        from agent.eval.scorer import EvalScorer
        from agent.eval.types import EvalCase

        case = EvalCase(id="t2", query="q")  # no expected_context_ids
        scorer = EvalScorer(use_judge=False)
        score = scorer.score(case, "ans", "rag_query", 1, retrieved_context_ids=["a"])
        assert score.context_precision is None
        assert score.context_recall is None


# ===========================================================================
# Builtin general benchmark dataset (REQ-C-002)
# ===========================================================================


class TestBuiltinGeneralBenchmark:
    def test_dataset_loads(self):
        from agent.eval.dataset import load_dataset

        cases = load_dataset("data/benchmark/builtin_general.yaml")
        assert len(cases) >= 8
        # Every case must carry expected_context_ids (the whole point: makes
        # context metrics deterministic).
        for c in cases:
            assert c.expected_context_ids, f"case {c.id} missing expected_context_ids"
            assert c.query
            assert c.reference_answer

    def test_corpus_loads_and_ids_match(self):
        """Every expected_context_id in the dataset exists in the corpus."""
        import yaml

        from agent.eval.dataset import load_dataset

        with open("data/benchmark/builtin_general_corpus.yaml", encoding="utf-8") as f:
            corpus = yaml.safe_load(f)
        corpus_ids = {c["id"] for c in corpus["chunks"]}
        assert len(corpus_ids) >= 8

        cases = load_dataset("data/benchmark/builtin_general.yaml")
        for c in cases:
            for cid in c.expected_context_ids:
                assert cid in corpus_ids, f"case {c.id} references unknown chunk id {cid}"

    def test_cases_are_domain_agnostic(self):
        """No aviation-specific terms in the general benchmark queries."""
        from agent.eval.dataset import load_dataset

        cases = load_dataset("data/benchmark/builtin_general.yaml")
        for c in cases:
            assert "飞机" not in c.query
            assert "PHM" not in c.query
            assert "ATA" not in c.query


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
