#!/usr/bin/env python3
"""
Layer ④ — rerank score threshold (v2: sigmoid absolute + min-max relative).

Bug2 Layer ④: the main hybrid retrieval path had NO score threshold — top_k
docs returned regardless of relevance, so 3%-relevance docs sailed through.

v1 used pure min-max normalization, which critic F-03 proved has zero filtering
power on 'weak batches' (the batch-top is always normalized to 1.0 >= 0.3).
v2 adds a sigmoid absolute floor: sigmoid(rerank_score) < min_rerank_prob is
dropped outright, so an all-weak batch (e.g. logits [-6,-5,-4,-3]) is correctly
emptied and pushed to Layer ⑤.

Run: uv run --frozen python -m pytest tests/unit/test_retrieve_rerank_threshold.py -v
"""

from __future__ import annotations

import math
import sys

import pytest

sys.path.insert(0, ".")


def _doc(rerank_score=None, rerank_applied=None, score=0.5):
    """Build a Document with reranker metadata."""
    from langchain_core.documents import Document

    meta = {"score": score}
    if rerank_applied is not None:
        meta["rerank_applied"] = rerank_applied
    if rerank_score is not None:
        meta["rerank_score"] = rerank_score
    return Document(page_content=f"doc-{rerank_score}", metadata=meta)


# ===========================================================================
# Sigmoid helper
# ===========================================================================


class TestSigmoid:
    def test_stable_for_large_negative(self):
        """Numerically stable sigmoid must not overflow on extreme logits."""
        from agent.skills.retrieve.skill import _sigmoid

        # Raw math.exp(710) would overflow; stable impl must return ~0.0.
        assert _sigmoid(-1000.0) == pytest.approx(0.0, abs=1e-9)
        assert _sigmoid(1000.0) == pytest.approx(1.0, abs=1e-9)

    def test_known_values(self):
        from agent.skills.retrieve.skill import _sigmoid

        assert _sigmoid(0.0) == pytest.approx(0.5)
        assert _sigmoid(2.0) == pytest.approx(1.0 / (1.0 + math.exp(-2.0)))


# ===========================================================================
# _filter_by_rerank_score — dual sieve
# ===========================================================================


class TestFilterByRerankScore:
    """[REQ-RG-007/008/009/010] Dual sieve: sigmoid absolute + min-max relative."""

    def _skill(self, min_rerank_score=0.3, min_rerank_prob=0.35):
        from agent.skills.retrieve.skill import RetrieveSkill, RetrieveSkillConfig

        return RetrieveSkill(
            RetrieveSkillConfig(
                min_rerank_score=min_rerank_score,
                min_rerank_prob=min_rerank_prob,
            )
        )

    def test_weak_batch_emptied(self):
        """[F-03] All-weak batch (logits [-6,-5,-4,-3]) MUST be emptied — the
        target-bug distribution. Pure min-max would keep the top doc."""
        skill = self._skill()
        docs = [
            _doc(rerank_score=-6.0, rerank_applied=True),
            _doc(rerank_score=-5.0, rerank_applied=True),
            _doc(rerank_score=-4.0, rerank_applied=True),
            _doc(rerank_score=-3.0, rerank_applied=True),
        ]
        result = skill._filter_by_rerank_score(docs)
        # sigmoid([-6,-5,-4,-3]) ≈ [0.0025,0.0067,0.018,0.047], all < 0.35 -> empty.
        assert result == [], "weak batch must be emptied by the sigmoid floor"

    def test_strong_batch_kept(self):
        """Strong docs (logits [2,1]) pass the sigmoid floor. min-max may drop
        the lower one, but at least the strongest is kept."""
        skill = self._skill()
        docs = [
            _doc(rerank_score=2.0, rerank_applied=True),
            _doc(rerank_score=1.0, rerank_applied=True),
        ]
        result = skill._filter_by_rerank_score(docs)
        # sigmoid(2)≈0.88, sigmoid(1)≈0.73, both > 0.35 sigmoid floor.
        # min-max: (1-1)/1=0 < 0.3 drops the lower; (2-1)/1=1.0 keeps the top.
        assert len(result) >= 1
        assert result[0].metadata["rerank_score"] == 2.0

    def test_reranker_degraded_no_filtering(self):
        """[REQ-RG-009] rerank_applied=False (degraded/no reranker) docs MUST
        NOT be filtered — empty-set handling is delegated to Layer ⑤."""
        skill = self._skill()
        docs = [
            _doc(rerank_applied=False),
            _doc(rerank_applied=False),
        ]
        result = skill._filter_by_rerank_score(docs)
        assert len(result) == 2, "degraded docs must pass through unchanged"

    def test_mixed_keeps_others(self):
        """A mixed batch keeps the real top reranked candidate plus unavailable docs."""
        skill = self._skill()
        docs = [
            _doc(rerank_score=-6.0, rerank_applied=True),
            _doc(score=1.0),  # memory, no rerank_applied -> kept
        ]
        result = skill._filter_by_rerank_score(docs)
        assert len(result) == 2
        assert result[0].metadata.get("rerank_score") == -6.0
        assert result[1].metadata.get("score") == 1.0

    def test_missing_rerank_score_treated_as_unavailable(self):
        """[critic-v2 Low #3] rerank_applied=True but rerank_score missing =
        data inconsistency -> bypass filtering without inventing a probability."""
        skill = self._skill()
        docs = [_doc(rerank_applied=True)]  # no rerank_score key
        result = skill._filter_by_rerank_score(docs)
        assert result == docs
        assert skill._compute_max_rerank_prob(docs) is None

    def test_empty_input_returns_empty(self):
        skill = self._skill()
        assert skill._filter_by_rerank_score([]) == []

    def test_uniform_batch_kept_by_min_max_guard(self):
        """A uniform batch (all same score) has span≈0; min-max is meaningless.
        The sigmoid floor still applies, but if scores pass sigmoid, all kept."""
        skill = self._skill(min_rerank_score=0.3, min_rerank_prob=0.0)
        docs = [
            _doc(rerank_score=2.0, rerank_applied=True),
            _doc(rerank_score=2.0, rerank_applied=True),
        ]
        result = skill._filter_by_rerank_score(docs)
        # span=0 -> min-max skipped; sigmoid floor disabled (prob=0) -> all kept.
        assert len(result) == 2


# ===========================================================================
# max_rerank_prob signal (Layer④ -> Layer⑤ via shared_state)
# ===========================================================================


class TestMaxRerankProbSignal:
    """[REQ-RG-008a] After filtering, the batch's max sigmoid probability MUST
    be published to shared_state['max_rerank_prob'] so Layer ⑤ uses the same
    absolute ruler. None when reranker degraded."""

    def test_compute_max_rerank_prob(self):
        from agent.skills.retrieve.skill import RetrieveSkill

        skill = RetrieveSkill()
        docs = [
            _doc(rerank_score=-6.0, rerank_applied=True),
            _doc(rerank_score=-3.0, rerank_applied=True),
        ]
        prob = skill._compute_max_rerank_prob(docs)
        # max sigmoid of [-6,-3] = sigmoid(-3) ≈ 0.047
        assert prob == pytest.approx(1.0 / (1.0 + math.exp(3.0)), abs=1e-6)

    def test_none_when_no_reranked_docs(self):
        from agent.skills.retrieve.skill import RetrieveSkill

        skill = RetrieveSkill()
        docs = [_doc(rerank_applied=False), _doc(score=1.0)]
        assert skill._compute_max_rerank_prob(docs) is None

    def test_none_for_empty(self):
        from agent.skills.retrieve.skill import RetrieveSkill

        skill = RetrieveSkill()
        assert skill._compute_max_rerank_prob([]) is None
