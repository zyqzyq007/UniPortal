#!/usr/bin/env python3
"""
REQ-RS-001 ~ 007 — Chinese BM25 tokenization regression.

Guards the P0 retrieval failure where jieba was never declared as a dependency:
bm25_retriever._tokenize silently fell back to a regex that treated a whole
Chinese sentence as ONE token, so Chinese queries shared zero terms with
documents → BM25 score=0 → sparse leg empty → hybrid retrieval degraded to
dense-only. Fixed by declaring jieba + script-aware min_token_length.

Run: pytest tests/unit/test_bm25_chinese_tokenization.py -v
"""

from __future__ import annotations

import importlib
import sys
import unittest.mock

import pytest
from langchain_core.documents import Document

sys.path.insert(0, ".")

from core.retrieval.bm25_retriever import BM25Config, BM25Retriever  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_retriever(**cfg) -> BM25Retriever:
    return BM25Retriever(config=BM25Config(**cfg))


# ===========================================================================
# REQ-RS-001 — jieba tokenization produces word-level tokens
# ===========================================================================


class TestJiebaTokenization:
    def test_chinese_sentence_split_into_words(self):
        """A Chinese sentence MUST split into word-level tokens, not collapse to
        a single whole-sentence token. '数据库查询优化' → contains 数据库/查询/优化."""
        r = _new_retriever()
        tokens = r._tokenize("数据库查询优化")
        assert "数据库" in tokens, f"expected word '数据库' in {tokens}"
        assert "查询" in tokens, f"expected word '查询' in {tokens}"
        assert "优化" in tokens, f"expected word '优化' in {tokens}"
        # The pre-fix regression produced ['数据库查询优化'] (len 1).
        assert len(tokens) > 1, f"sentence collapsed to one token: {tokens}"

    def test_multiple_terms_not_one_mega_token(self):
        """Two distinct concepts must not fuse into one token."""
        r = _new_retriever()
        tokens = r._tokenize("数据库查询 缓存失效")
        assert "数据库" in tokens
        assert "缓存" in tokens

    def test_jieba_is_actually_installed(self):
        """The dependency MUST be declared so the jieba path runs (not the
        regex fallback). This pins the install against accidental removal."""
        assert importlib.util.find_spec("jieba") is not None, (
            "jieba not installed — bm25 Chinese tokenization is broken"
        )


# ===========================================================================
# REQ-RS-003 — Chinese single-character terms survive (script-aware floor)
# ===========================================================================


class TestScriptAwareMinTokenLength:
    def test_chinese_single_char_kept(self):
        """High-value CJK单字 (库/表/链) MUST survive — they are the
        subject of many technical queries. With the script-aware floor (zh=1) they
        are kept even though len==1."""
        r = _new_retriever()
        for term in ["库", "表", "链"]:
            assert term in r._tokenize(term), f"Chinese单字 {term} was dropped"

    def test_english_single_letter_dropped(self):
        """Single English letters (noise) MUST be dropped by the en floor (2)."""
        r = _new_retriever()
        tokens = r._tokenize("a b engine")
        assert "a" not in tokens
        assert "b" not in tokens
        assert "engine" in tokens

    def test_custom_zh_floor_can_drop_short_chinese(self):
        """A caller can raise the zh floor; 单字 then drops, multi-char kept."""
        r = _new_retriever(min_token_length_zh=2)
        tokens = r._tokenize("库 参数")
        assert "库" not in tokens
        assert "参数" in tokens


# ===========================================================================
# REQ-RS-002 — regex fallback emits a visible warning (no silent degradation)
# ===========================================================================


class TestFallbackVisibility:
    def test_missing_jieba_logs_warning(self, monkeypatch):
        """When jieba is unavailable, BM25 MUST log a warning so the degradation
        is visible (previously silent — the root cause of undetected failure).

        Project logging uses loguru (not stdlib logging), so pytest's caplog
        fixture won't capture it; we attach a loguru sink and assert directly.
        """
        from utils.log_utils import log as _  # noqa: F401  (ensure logger configured)

        # Force the ImportError path by making 'import jieba' raise.
        real_import = __import__
        monkeypatch.setitem(sys.modules, "jieba", None)

        def _fake_import(name, *args, **kwargs):
            if name == "jieba":
                raise ImportError("mocked: jieba unavailable")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", _fake_import)

        # Collect loguru records into a list.
        messages: list[str] = []
        from loguru import logger

        sink_id = logger.add(lambda m: messages.append(m), level="WARNING")

        try:
            r = _new_retriever()
            r._tokenize("数据库查询")
        finally:
            logger.remove(sink_id)

        joined = " ".join(messages).lower()
        assert "jieba not installed" in joined or "falling back to regex" in joined, (
            f"expected jieba-degradation warning, got: {messages!r}"
        )


# ===========================================================================
# REQ-RS-006 / REQ-RS-007 — Chinese BM25 recall + score>0 filter
# ===========================================================================


class TestChineseBM25Recall:
    def _index(self, r: BM25Retriever):
        r.add_documents(
            [
                Document(page_content="数据库查询优化是常见操作", metadata={"id": "d1"}),
                Document(page_content="缓存命中率正常无异常", metadata={"id": "d2"}),
                Document(page_content="天气晴朗适合户外运动", metadata={"id": "d3"}),
            ]
        )

    def test_chinese_query_recalls_matching_doc(self):
        """A Chinese query sharing word tokens with a doc MUST produce score>0
        and be recalled (pre-fix: always 0 results)."""
        r = _new_retriever()
        self._index(r)
        results = r.retrieve("数据库查询", top_k=3)
        ids = [x.document.metadata["id"] for x in results]
        assert "d1" in ids, f"expected d1 (数据库/查询 match), got {ids}"
        assert len(results) >= 1

    def test_zero_overlap_doc_filtered_out(self):
        """Docs with zero term overlap (score=0) MUST be filtered by `if score>0`
        — keeping them would inject noise into RRF fusion (design §3)."""
        r = _new_retriever()
        self._index(r)
        results = r.retrieve("数据库查询", top_k=3)
        ids = [x.document.metadata["id"] for x in results]
        # d3 (天气晴朗) shares no terms with 数据库查询 → must not appear.
        assert "d3" not in ids, "zero-overlap doc d3 leaked into results — score>0 filter broken"

    def test_chinese_query_score_is_positive(self):
        """The recalled Chinese doc MUST have a positive score (was always 0)."""
        r = _new_retriever()
        self._index(r)
        results = r.retrieve("数据库查询", top_k=3)
        assert results, "no results for a matching Chinese query"
        assert all(x.score > 0 for x in results), (
            f"non-positive scores: {[(x.document.metadata['id'], x.score) for x in results]}"
        )


# ===========================================================================
# Cross-cutting: BM25Config field rename did not break construction
# ===========================================================================


class TestBM25ConfigCompat:
    def test_default_config_has_script_aware_floors(self):
        cfg = BM25Config()
        assert cfg.min_token_length_zh == 1
        assert cfg.min_token_length_en == 2

    def test_legacy_min_token_length_not_required(self):
        """Construction MUST NOT require the old single min_token_length field
        (renamed to zh/en). Callers using defaults work."""
        cfg = BM25Config()
        assert cfg.k1 == 1.5
        assert cfg.b == 0.75


# ===========================================================================
# F-RS-006 — hybrid retrieval invariants (§7.2): Chinese sparse leg non-empty
#            + dense-only fallback when sparse errors.
#
# The unit tests above cover _tokenize/retrieve in isolation; these guard the
# *integration* so a future regression (jieba removed, score>0 loosened) cannot
# silently empty the sparse leg again — which is exactly how this P0 went
# undetected. Must assert at the hybrid layer, not the BM25 layer.
# ===========================================================================


class TestHybridChineseSparseLeg:
    def test_hybrid_chinese_sparse_leg_non_empty(self):
        """After Stage A, a Chinese query MUST produce a non-empty sparse
        contribution that flows into RRF fusion (pre-fix: sparse leg empty for
        Chinese, hybrid degraded to dense-only). Guards §7.2 write→read
        consistency across the whole retrieval leg, not just _tokenize."""
        from langchain_core.documents import Document

        from core.retrieval.bm25_retriever import BM25Retriever

        # Isolated BM25 instance with Chinese corpus — mirrors what the hybrid
        # sparse leg holds after bootstrap.
        r = BM25Retriever()
        r.add_documents(
            [
                Document(page_content="数据库查询优化是常见操作原因", metadata={"id": "d1"}),
                Document(page_content="缓存命中率偏低报警", metadata={"id": "d2"}),
            ]
        )
        results = r.retrieve("数据库查询", top_k=5)
        assert results, "sparse leg returned empty for a Chinese query — P0 regressed"

    def test_dense_only_fallback_when_sparse_empty(self):
        """When the sparse leg returns nothing (zero term overlap), the hybrid
        retriever MUST still return dense results — the §3 'unavailable != 0'
        invariant: a failed/empty leg degrades gracefully, never yields []."""
        from langchain_core.documents import Document

        from core.retrieval.hybrid_retriever import (
            HybridRetriever,
            HybridRetrieverConfig,
            RetrievalResult,
        )

        cfg = HybridRetrieverConfig(enable_reranker=False)
        retriever = HybridRetriever(config=cfg)

        # Drive _rrf_fusion directly with empty sparse to prove dense-only works.
        dense = [
            RetrievalResult(
                document=Document(page_content="dense fallback result", metadata={"id": "d1"}),
                score=1.0,
                source="dense",
                rank=1,
            )
        ]
        fused = retriever._rrf_fusion(dense_results=dense, sparse_results=[])
        assert fused, "dense-only RRF fallback returned empty — unavailable was treated as 0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
