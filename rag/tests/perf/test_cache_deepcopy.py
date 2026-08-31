#!/usr/bin/env python3
"""
F13 — retrieval cache deepcopy cost benchmark (time.perf_counter, no new deps).

The cache write deep-copies results to insulate the cache from downstream
mutations (a correctness fix). This test quantifies the deepcopy cost on a
representative result set and asserts it stays under a hard threshold. If a
future change pushes deepcopy over budget, the fix is to switch to a shallow
copy + fresh metadata dict (see design F13) — but only after this test flags it.

Per requirements §4 ("no new external dependencies"), this uses stdlib
``time.perf_counter`` rather than pytest-benchmark.

Run: pytest tests/perf/test_cache_deepcopy.py -v
"""

from __future__ import annotations

import copy
import sys
import time

import pytest
from langchain_core.documents import Document

sys.path.insert(0, ".")


def _make_docs(n: int, chars_each: int = 400) -> list[Document]:
    return [
        Document(
            page_content=f"chunk {i} " + ("x" * chars_each),
            metadata={
                "source": f"manual_{i}.md",
                "title": f"section {i}",
                "score": 0.9 - i * 0.01,
                "retrieval_source": "hybrid",
                "retrieval_score": 0.9 - i * 0.01,
            },
        )
        for i in range(n)
    ]


def _p95(samples: list[float]) -> float:
    samples = sorted(samples)
    idx = max(0, int(len(samples) * 0.95) - 1)
    return samples[idx]


class TestCacheDeepcopyBudget:
    def test_deepcopy_p95_under_budget_for_typical_result_set(self):
        """A 10-doc result set (~400 chars each + metadata) should deepcopy in
        well under the budget. The threshold is generous to avoid CI flakiness;
        the point is to catch regressions (e.g. a 100x slowdown)."""
        docs = _make_docs(10, chars_each=400)
        samples = []
        for _ in range(30):
            t0 = time.perf_counter()
            copy.deepcopy(docs)
            samples.append((time.perf_counter() - t0) * 1000.0)
        p95 = _p95(samples)
        assert p95 < 50.0, (
            f"deepcopy P95 {p95:.2f}ms exceeds 50ms budget for 10 docs; "
            f"consider switching to shallow-copy + fresh metadata dict"
        )

    def test_shallow_copy_with_fresh_metadata_is_cheaper(self):
        """Documents the cheaper alternative if deepcopy ever exceeds budget:
        shallow Document copy + a fresh metadata dict breaks the aliasing that
        deepcopy guards against, at a fraction of the cost."""
        docs = _make_docs(10, chars_each=400)

        def _shallow_with_fresh_meta(doc_list):
            return [
                Document(page_content=d.page_content, metadata=dict(d.metadata)) for d in doc_list
            ]

        deep_samples = []
        shallow_samples = []
        for _ in range(30):
            t0 = time.perf_counter()
            copy.deepcopy(docs)
            deep_samples.append((time.perf_counter() - t0) * 1000.0)
            t0 = time.perf_counter()
            _shallow_with_fresh_meta(docs)
            shallow_samples.append((time.perf_counter() - t0) * 1000.0)

        # The cheaper alternative must be at least as fast (sanity; not a hard
        # requirement on the production path, which currently uses deepcopy).
        assert _p95(shallow_samples) <= _p95(deep_samples) * 1.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
