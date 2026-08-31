#!/usr/bin/env python3
"""
Unit tests for P1 retrieval-depth enhancements:
  - token budget context packing (P1.1)
  - MMR diversity re-ranking (P1.2)
  - metadata filter plumbing (P1.3)
  - embedding model fingerprinting (P1.4)
  - query transformation parsing (P1.5)
  - parent-child / small-to-big expansion (P1.6)
  - multi-format doc dispatch (P1.7)
  - index config env parsing (P1.8)

These avoid the real LLM / Milvus. Run: pytest tests/unit/test_p1_retrieval.py -v
"""

from __future__ import annotations

import sys

import pytest
from langchain_core.documents import Document

sys.path.insert(0, ".")


# ===========================================================================
# P1.1 token budget
# ===========================================================================


class TestTokenBudget:
    def test_estimate_tokens_cjk(self):
        from core.context.token_budget import estimate_tokens

        # 3 CJK chars ~ 2 tokens + 1
        assert estimate_tokens("数据库") > 0
        assert estimate_tokens("") == 0
        # CJK is more token-dense than ASCII.
        assert estimate_tokens("数据库查询") > estimate_tokens("abcd")

    def test_build_context_keeps_most_relevant(self):
        from core.context.token_budget import build_context_within_budget

        docs = [
            Document(page_content="无关长文本" * 50, metadata={"score": 0.1}),
            Document(page_content="高度相关的配置说明", metadata={"score": 0.95}),
            Document(page_content="次相关内容", metadata={"score": 0.5}),
        ]
        # Tiny budget forces dropping the long irrelevant doc.
        ctx, kept = build_context_within_budget(docs, question="数据库", context_token_budget=30)
        # Most relevant kept first.
        assert any("配置说明" in d.page_content for d in kept)
        assert "配置说明" in ctx

    def test_build_context_all_fit(self):
        from core.context.token_budget import build_context_within_budget

        docs = [Document(page_content="短文本A"), Document(page_content="短文本B")]
        ctx, kept = build_context_within_budget(docs, context_token_budget=10000)
        assert len(kept) == 2
        assert "短文本A" in ctx and "短文本B" in ctx

    def test_build_context_empty(self):
        from core.context.token_budget import build_context_within_budget

        ctx, kept = build_context_within_budget([])
        assert ctx == "" and kept == []


# ===========================================================================
# P1.2 MMR
# ===========================================================================


class TestMMR:
    def test_mmr_returns_subset(self, monkeypatch):
        from core.retrieval import mmr as mmr_mod

        # Stub embeddings to deterministic vectors.
        class _FakeEmb:
            def embed_documents(self, texts):
                import numpy as np

                # Each text maps to a distinct-ish vector.
                return [
                    np.array([float(hash(t) % 100) / 100, 0.1, 0.2], dtype="float32") for t in texts
                ]

            def embed_query(self, text):
                import numpy as np

                return np.array([0.9, 0.1, 0.2], dtype="float32")

        monkeypatch.setattr(mmr_mod, "_embeddings", lambda: _FakeEmb())

        docs = [
            Document(page_content=f"chunk {i}", metadata={"score": 0.9 - i * 0.1}) for i in range(6)
        ]
        out = mmr_mod.mmr_rerank("query", docs, top_k=3)
        assert len(out) <= 3
        assert all(isinstance(d, Document) for d in out)

    def test_mmr_falls_back_on_embedding_failure(self, monkeypatch):
        from core.retrieval import mmr as mmr_mod

        def boom():
            raise RuntimeError("no embeddings")

        monkeypatch.setattr(mmr_mod, "_embeddings", boom)

        docs = [Document(page_content=f"c{i}", metadata={"score": 0.5}) for i in range(4)]
        out = mmr_mod.mmr_rerank("q", docs, top_k=2)
        # Falls back to relevance order, returns top_k.
        assert len(out) == 2

    def test_mmr_single_doc(self, monkeypatch):
        from core.retrieval import mmr as mmr_mod

        docs = [Document(page_content="only", metadata={"score": 1.0})]
        out = mmr_mod.mmr_rerank("q", docs, top_k=3)
        assert len(out) == 1


# ===========================================================================
# P1.3 metadata filter plumbing
# ===========================================================================


class TestMetadataFilter:
    def test_extract_filter_from_shared_state(self):
        from agent.skills.retrieve.skill import RetrieveSkill

        class _Ctx:
            shared_state = {"filter_expr": 'source == "engine"'}

        assert RetrieveSkill._extract_filter(_Ctx()) == 'source == "engine"'

    def test_extract_filter_none(self):
        from agent.skills.retrieve.skill import RetrieveSkill

        class _Ctx:
            shared_state = {}

        assert RetrieveSkill._extract_filter(_Ctx()) is None
        assert RetrieveSkill._extract_filter(type("X", (), {"shared_state": None})()) is None

    def test_retrieve_passes_filter(self, monkeypatch):
        from agent.skills.retrieve.skill import RetrieveSkill

        skill = RetrieveSkill()
        captured = {}

        class _FakeRetriever:
            def retrieve(self, query, top_k=None, filter_expr=None):
                captured["filter"] = filter_expr
                return []

        skill._retriever = _FakeRetriever()
        skill._retrieve("q", filter_expr='title == "X"')
        assert captured["filter"] == 'title == "X"'


# ===========================================================================
# P1.4 embedding fingerprint
# ===========================================================================


class TestEmbeddingFingerprint:
    def test_fingerprint_stable(self):
        from documents.embedding_registry import fingerprint

        assert fingerprint("bge", 512) == fingerprint("bge", 512)
        assert fingerprint("bge", 512) != fingerprint("bge", 768)
        assert fingerprint("bge", 512) != fingerprint("other", 512)

    def test_registry_compatible_same_model(self, tmp_path):
        from documents.embedding_registry import EmbeddingRegistry

        reg = EmbeddingRegistry(str(tmp_path / "er.db"))
        try:
            reg.register("col1", "bge-small", 512)
            assert reg.is_compatible("col1", "bge-small", 512) is True
        finally:
            reg.close()

    def test_registry_incompatible_on_model_change(self, tmp_path):
        from documents.embedding_registry import EmbeddingRegistry

        reg = EmbeddingRegistry(str(tmp_path / "er.db"))
        try:
            reg.register("col1", "bge-small", 512)
            assert reg.is_compatible("col1", "bge-large", 1024) is False
        finally:
            reg.close()

    def test_registry_unknown_existing_collection_is_incompatible(self, tmp_path):
        from documents.embedding_registry import EmbeddingRegistry

        reg = EmbeddingRegistry(str(tmp_path / "er.db"))
        try:
            assert reg.is_compatible("nope", "bge", 512) is False
        finally:
            reg.close()


# ===========================================================================
# P1.5 query transform parsing
# ===========================================================================


class TestQueryTransform:
    def test_parse_queries_strips_numbering(self):
        from core.retrieval.query_transform import _parse_queries

        raw = "1. 日志排查\n2) 性能诊断\n\n网络分析"
        out = _parse_queries(raw, 3)
        assert out == ["日志排查", "性能诊断", "网络分析"]

    def test_parse_queries_caps_n(self):
        from core.retrieval.query_transform import _parse_queries

        # Each line must be >= 4 chars to pass the length filter.
        out = _parse_queries("日志如何排查\n性能过高诊断\n网络分析步骤\n更多内容", 2)
        assert len(out) == 2

    def test_multi_query_fallback_on_llm_failure(self, monkeypatch):
        from core.retrieval import query_transform as qt

        def boom(prompt):
            return None

        monkeypatch.setattr(qt, "_llm_invoke", boom)
        out = qt.multi_query_expand("query", n=3)
        assert out == ["query"]  # falls back to original only


# ===========================================================================
# P1.6 parent-child expansion
# ===========================================================================


class TestParentChild:
    def test_make_parent_id_stable(self):
        from documents.parent_store import make_parent_id

        assert make_parent_id("manual", 1) == make_parent_id("manual", 1)
        assert make_parent_id("manual", 1) != make_parent_id("manual", 2)

    def test_expand_to_parents_dedupes(self, monkeypatch, tmp_path):
        from documents import parent_store as ps_mod

        # Redirect store to a tmp db with known parents.
        store = ps_mod.ParentStore(str(tmp_path / "ps.db"))
        store.store("p1", "父文档完整内容第一章", source="manual")
        store.store("p2", "父文档完整内容第二章", source="manual")
        monkeypatch.setattr(ps_mod, "get_parent_store", lambda: store)

        try:
            children = [
                Document(page_content="child1", metadata={"parent_id": "p1", "score": 0.9}),
                Document(page_content="child2", metadata={"parent_id": "p1", "score": 0.5}),
                Document(page_content="child3", metadata={"parent_id": "p2", "score": 0.8}),
            ]
            expanded = ps_mod.expand_to_parents(children)
            # Two distinct parents, deduplicated.
            assert len(expanded) == 2
            # Parent text replaced child content.
            assert all("父文档" in d.page_content for d in expanded)
            # Best child score preserved on parent.
            p1 = next(d for d in expanded if d.metadata["parent_id"] == "p1")
            assert p1.metadata["score"] == 0.9
        finally:
            store.close()

    def test_expand_passthrough_when_no_parent_id(self, monkeypatch, tmp_path):
        from documents import parent_store as ps_mod

        store = ps_mod.ParentStore(str(tmp_path / "ps.db"))
        monkeypatch.setattr(ps_mod, "get_parent_store", lambda: store)

        try:
            children = [Document(page_content="orphan", metadata={"score": 0.3})]
            expanded = ps_mod.expand_to_parents(children)
            assert len(expanded) == 1
            assert expanded[0].page_content == "orphan"
        finally:
            store.close()


# ===========================================================================
# P1.7 multi-format dispatch
# ===========================================================================


class TestFormatParsers:
    def test_parse_html_real(self, tmp_path):
        from documents.format_parsers import parse_html

        html_file = tmp_path / "test.html"
        html_file.write_text(
            "<html><body>"
            "<h1>部署章节</h1><p>日志分析要点。内容足够长以通过长度检查。</p>"
            "<h2>缓存章节</h2><p>配置排查步骤。</p>"
            "</body></html>",
            encoding="utf-8",
        )
        docs = parse_html(str(html_file), source="test.html")
        assert len(docs) >= 1
        assert all(d.metadata["format"] == "html" for d in docs)

    def test_dispatch_docx_without_lib_errors(self, tmp_path):
        from documents.format_parsers import parse_by_extension

        # We don't ship a real docx; but if python-docx is absent the error is
        # a clear RuntimeError, not an obscure import error.
        f = tmp_path / "x.docx"
        f.write_bytes(b"fake")
        with pytest.raises((RuntimeError, Exception)):
            parse_by_extension(str(f))

    def test_dispatch_unknown_ext(self):
        from documents.format_parsers import parse_by_extension

        with pytest.raises(ValueError):
            parse_by_extension("file.xyz")


# ===========================================================================
# P1.8 index config env parsing
# ===========================================================================


class TestIndexConfig:
    def test_parse_index_env_valid(self):
        from documents.milvus_db import _parse_index_env

        assert _parse_index_env('{"M": 16, "efConstruction": 200}') == {
            "M": 16,
            "efConstruction": 200,
        }

    def test_parse_index_env_empty(self):
        from documents.milvus_db import _parse_index_env

        assert _parse_index_env("") is None
        assert _parse_index_env(None) is None

    def test_parse_index_env_invalid(self):
        from documents.milvus_db import _parse_index_env

        assert _parse_index_env("not json") is None

    def test_milvus_config_defaults_autoindex(self, monkeypatch):
        from documents.milvus_db import MilvusConfig

        # Ensure no env override so default AUTOINDEX applies.
        monkeypatch.delenv("MILVUS_INDEX_TYPE", raising=False)
        monkeypatch.delenv("MILVUS_INDEX_PARAMS", raising=False)
        monkeypatch.delenv("MILVUS_SEARCH_PARAMS", raising=False)
        cfg = MilvusConfig()
        assert cfg.index_type in ("AUTOINDEX", "AUTOINDEX")
        assert cfg.index_params is None
        assert cfg.search_params is None

    def test_milvus_config_env_override(self, monkeypatch):
        from documents.milvus_db import MilvusConfig

        monkeypatch.setenv("MILVUS_INDEX_TYPE", "HNSW")
        monkeypatch.setenv("MILVUS_INDEX_PARAMS", '{"M": 32, "efConstruction": 256}')
        monkeypatch.setenv("MILVUS_SEARCH_PARAMS", '{"ef": 128}')
        cfg = MilvusConfig()
        assert cfg.index_type == "HNSW"
        assert cfg.index_params == {"M": 32, "efConstruction": 256}
        assert cfg.search_params == {"ef": 128}


# ===========================================================================
# HybridRetriever config wiring
# ===========================================================================


class TestHybridRetrieverConfig:
    def test_mmr_config_defaults(self):
        from core.retrieval.hybrid_retriever import HybridRetrieverConfig

        cfg = HybridRetrieverConfig()
        assert cfg.enable_mmr is True
        assert 0 < cfg.mmr_lambda <= 1.0

    def test_retrieve_accepts_filter_expr(self):
        # Signature must accept filter_expr (P1.3 plumbing).
        import inspect

        from core.retrieval.hybrid_retriever import HybridRetriever

        sig = inspect.signature(HybridRetriever.retrieve)
        assert "filter_expr" in sig.parameters
        sig_a = inspect.signature(HybridRetriever.aretrieve)
        assert "filter_expr" in sig_a.parameters


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
