#!/usr/bin/env python3
"""
Stage 2 audit bugfix test — B6 (time-decay defeated when reranker enabled).

The hybrid pipeline runs RRF → rerank → time_decay → MMR, contradicting the
time_decay.py docstring ("AFTER RRF fusion but BEFORE reranking/MMR"). Because
MMR keys its relevance blend off `rerank_score`, the decayed `score` is ignored
for final ordering whenever the reranker is on — so time-decay has no ranking
effect in the "premium" config. The fix reorders to RRF → time_decay → rerank →
MMR.

This test builds a minimal scenario where the reranker returns a FIXED order
(old before fresh), and asserts that after the fix the fresh doc still ranks
no worse than the old one (decay applied before rerank influences the blend).

Run: uv run --frozen python -m pytest tests/unit/test_audit_stage2_pipeline.py -v
"""

from __future__ import annotations

import sys
import time

import pytest

sys.path.insert(0, ".")


def test_b6_time_decay_influences_ranking_with_reranker(monkeypatch):
    """When the reranker is enabled, time-decay MUST still apply before rerank.

    Setup: two docs with distinct text (so both survive RRF), one fresh and one
    2-year-old. We capture the docs handed to _rerank and assert they already
    carry a `time_decay_factor` with fresh > old — proof decay ran before rerank
    (before the fix, decay ran after rerank so the reranker saw un-decayed scores
    and the factor never reached the ranking signal).
    """
    from langchain_core.documents import Document

    from core.retrieval.hybrid_retriever import HybridRetriever, RetrievalResult

    now = time.time()
    fresh = Document(
        page_content="解决 git 合并冲突需要手动编辑冲突标记后提交",
        metadata={"source": "fresh", "score": 1.0, "created_at": now},
    )
    old = Document(
        page_content="git 分支管理常用命令与合并冲突排查流程",
        metadata={"source": "old", "score": 1.0, "created_at": now - 365 * 86400 * 2},
    )

    retriever = HybridRetriever()

    # Force dense to return both docs (RRF keeps them both).
    def _both(_q, _f=None):
        return [
            RetrievalResult(document=fresh, score=1.0, source="dense", rank=1),
            RetrievalResult(document=old, score=1.0, source="dense", rank=2),
        ]

    monkeypatch.setattr(retriever, "_dense_retrieve", _both)
    monkeypatch.setattr(retriever, "_sparse_retrieve", lambda _q: [])
    monkeypatch.setattr(retriever, "_graph_retrieve", lambda _q, _f=None: [])
    monkeypatch.setattr(retriever, "_parallel_retrieve", lambda _q, _f: (_both(_q), [], []))
    monkeypatch.setattr(retriever, "_mmr", lambda _q, d, _k: d)

    captured = {"docs": None}

    def _rerank(_q, docs, _top_k=None):
        captured["docs"] = docs
        return docs

    monkeypatch.setattr(retriever, "_rerank", _rerank)

    monkeypatch.setenv("RETRIEVAL_HALF_LIFE_DAYS", "30")

    retriever.retrieve("git 合并冲突", top_k=2)

    docs_in = captured["docs"]
    assert docs_in and len(docs_in) == 2, (
        f"expected 2 docs at rerank, got {len(docs_in) if docs_in else 0}"
    )
    factors = {d.metadata["source"]: d.metadata.get("time_decay_factor") for d in docs_in}
    assert factors.get("fresh") is not None and factors.get("old") is not None, (
        f"docs fed to rerank lack time_decay_factor — decay did not run before rerank; {factors}"
    )
    assert factors["fresh"] > factors["old"], (
        f"fresh factor {factors['fresh']} should exceed old factor {factors['old']}"
    )


def test_b6_pipeline_calls_decay_before_rerank(monkeypatch):
    """Pin the order-of-operations: _time_decay MUST be called before _rerank.

    This is the direct contract assertion. We record call order on the three
    pipeline stages and assert decay precedes rerank.
    """
    from langchain_core.documents import Document

    from core.retrieval.hybrid_retriever import HybridRetriever, RetrievalResult

    doc = Document(page_content="git 合并冲突", metadata={"source": "s", "score": 1.0})
    retriever = HybridRetriever()

    monkeypatch.setattr(
        retriever,
        "_dense_retrieve",
        lambda _q, _f=None: [RetrievalResult(document=doc, score=1.0, source="dense", rank=1)],
    )
    monkeypatch.setattr(retriever, "_sparse_retrieve", lambda _q: [])
    monkeypatch.setattr(retriever, "_graph_retrieve", lambda _q, _f=None: [])
    monkeypatch.setattr(
        retriever,
        "_parallel_retrieve",
        lambda _q, _f: (
            [RetrievalResult(document=doc, score=1.0, source="dense", rank=1)],
            [],
            [],
        ),
    )

    order: list[str] = []

    def _wrap(name, fn):
        def _w(*a, **k):
            order.append(name)
            return fn(*a, **k)

        return _w

    # Use real decay + identity rerank/mmr, recording call order.
    monkeypatch.setattr(retriever, "_time_decay", _wrap("decay", retriever._time_decay))
    monkeypatch.setattr(retriever, "_rerank", _wrap("rerank", lambda _q, d, _k: d))
    monkeypatch.setattr(retriever, "_mmr", _wrap("mmr", lambda _q, d, _k: d))

    retriever.retrieve("git 合并冲突", top_k=1)

    assert order == ["decay", "rerank", "mmr"], (
        f"pipeline order is {order}, expected ['decay','rerank','mmr'] "
        f"(time_decay must run BEFORE rerank per time_decay.py docstring)"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
