#!/usr/bin/env python3
"""
F1 Stage D — late chunking integration regression guards.

Covers docs/specs/retrieval-backend-modernization §3.5:
- F-05: late chunking attaches _late_chunk_dense to chunk metadata; sparse stays
  per-chunk (not tested here — covered by add_documents using encode_hybrid_batch
  for sparse regardless of late dense).
- F-06: degradation (disabled / non-M3 model / encode failure) → no metadata key,
  add_documents falls back to per-chunk embed.
- F-08: span reconstruction via sequential cursor search; splitter normalisation
  failure → graceful skip.

Run: pytest tests/unit/test_late_chunking.py -v
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document

sys.path.insert(0, ".")


@pytest.fixture
def fake_m3_embedding():
    """Fake embedding that mimics BGEM3Embeddings (has encode_late_chunked)."""

    class FakeM3:
        def encode_late_chunked(self, section_text, chunk_spans):
            # Return a distinct vector per span (length 4 for test simplicity).
            return [[float(i)] * 4 for i in range(len(chunk_spans))]

        def embed_query(self, text):
            return [0.0] * 4

        def embed_documents(self, texts):
            return [[0.0] * 4 for _ in texts]

    return FakeM3()


class TestMaybeApplyLateChunking:
    """markdown_parser._maybe_apply_late_chunking attaches dense vecs."""

    def test_attaches_late_dense_to_pieces(self, fake_m3_embedding):
        from documents.markdown_parser import MarkdownParser

        parent = Document(page_content="alpha content beta content gamma content")
        pieces = [
            Document(page_content="alpha content"),
            Document(page_content="beta content"),
            Document(page_content="gamma content"),
        ]
        parser = MarkdownParser.__new__(MarkdownParser)
        parser.log = MagicMock()

        with (
            patch("documents.markdown_parser._late_chunking_enabled", return_value=True),
            patch(
                "documents.markdown_parser._get_local_embeddings", return_value=fake_m3_embedding
            ),
        ):
            parser._maybe_apply_late_chunking(parent, pieces)

        assert "_late_chunk_dense" in pieces[0].metadata
        assert "_late_chunk_dense" in pieces[1].metadata
        assert pieces[0].metadata["_late_chunk_dense"] == [0.0, 0.0, 0.0, 0.0]
        assert pieces[1].metadata["_late_chunk_dense"] == [1.0, 1.0, 1.0, 1.0]

    def test_disabled_skips_late_chunking(self, fake_m3_embedding):
        """LATE_CHUNKING_ENABLED=false → no _late_chunk_dense."""
        from documents.markdown_parser import MarkdownParser

        parent = Document(page_content="alpha content beta content")
        pieces = [Document(page_content="alpha content")]
        parser = MarkdownParser.__new__(MarkdownParser)
        parser.log = MagicMock()

        with (
            patch("documents.markdown_parser._late_chunking_enabled", return_value=False),
            patch(
                "documents.markdown_parser._get_local_embeddings", return_value=fake_m3_embedding
            ),
        ):
            parser._maybe_apply_late_chunking(parent, pieces)

        assert "_late_chunk_dense" not in pieces[0].metadata

    def test_non_m3_model_skips(self):
        """Non-BGEM3 embedding (no encode_late_chunked) → skip."""
        from documents.markdown_parser import MarkdownParser

        class PlainEmbedding:
            def embed_query(self, text):
                return [0.0]

            def embed_documents(self, texts):
                return [[0.0] for _ in texts]

        parent = Document(page_content="alpha content")
        pieces = [Document(page_content="alpha content")]
        parser = MarkdownParser.__new__(MarkdownParser)
        parser.log = MagicMock()

        with (
            patch("documents.markdown_parser._late_chunking_enabled", return_value=True),
            patch("documents.markdown_parser._get_local_embeddings", return_value=PlainEmbedding()),
        ):
            parser._maybe_apply_late_chunking(parent, pieces)

        assert "_late_chunk_dense" not in pieces[0].metadata

    def test_span_reconstruction_failure_skips(self, fake_m3_embedding):
        """F-08: when splitter normalisation makes chunk text unfindable in
        parent, late chunking is skipped for the whole section (no crash)."""
        from documents.markdown_parser import MarkdownParser

        # Parent has different whitespace than pieces (splitter normalised).
        parent = Document(page_content="alpha   content")  # 3 spaces
        pieces = [Document(page_content="alpha content")]  # 1 space — not a substring
        parser = MarkdownParser.__new__(MarkdownParser)
        parser.log = MagicMock()

        with (
            patch("documents.markdown_parser._late_chunking_enabled", return_value=True),
            patch(
                "documents.markdown_parser._get_local_embeddings", return_value=fake_m3_embedding
            ),
        ):
            parser._maybe_apply_late_chunking(parent, pieces)

        assert "_late_chunk_dense" not in pieces[0].metadata

    def test_encode_failure_degrades_silently(self):
        """F-06: encode_late_chunked raises → no metadata key, no crash."""
        from documents.markdown_parser import MarkdownParser

        class FailingM3:
            def encode_late_chunked(self, section_text, chunk_spans):
                raise RuntimeError("OOM")

        parent = Document(page_content="alpha content beta content")
        pieces = [
            Document(page_content="alpha content"),
            Document(page_content="beta content"),
        ]
        parser = MarkdownParser.__new__(MarkdownParser)
        parser.log = MagicMock()

        with (
            patch("documents.markdown_parser._late_chunking_enabled", return_value=True),
            patch("documents.markdown_parser._get_local_embeddings", return_value=FailingM3()),
        ):
            parser._maybe_apply_late_chunking(parent, pieces)

        assert "_late_chunk_dense" not in pieces[0].metadata

    def test_empty_pieces_noop(self, fake_m3_embedding):
        """No pieces → no-op."""
        from documents.markdown_parser import MarkdownParser

        parser = MarkdownParser.__new__(MarkdownParser)
        parser.log = MagicMock()
        with (
            patch("documents.markdown_parser._late_chunking_enabled", return_value=True),
            patch(
                "documents.markdown_parser._get_local_embeddings", return_value=fake_m3_embedding
            ),
        ):
            parser._maybe_apply_late_chunking(Document(page_content="x"), [])


class TestAddDocumentsUsesLateChunkDense:
    """MilvusManager.add_documents uses _late_chunk_dense when present (F-05)."""

    def test_late_dense_used_instead_of_embed(self):
        """When a chunk has _late_chunk_dense, add_documents writes that vector
        and does NOT call embed_documents for it."""
        import tempfile

        from documents.milvus_db import MilvusConfig, MilvusManager

        db_path = tempfile.mktemp(suffix=".db")
        manager = MilvusManager(config=MilvusConfig(uri=db_path, dense_dim=4, enable_sparse=False))
        manager.create_collection(drop_if_exists=True)

        late_vec = [0.9, 0.8, 0.7, 0.6]
        doc = Document(
            page_content="test doc",
            metadata={"source": "s", "title": "t", "_late_chunk_dense": late_vec},
        )

        mock_emb = MagicMock()
        mock_emb.embed_documents.return_value = [[0.1, 0.1, 0.1, 0.1]]
        mock_emb.embed_query.return_value = [0.1, 0.1, 0.1, 0.1]
        manager._embedding_fn = mock_emb

        manager.add_documents([doc], show_progress=False)

        # embed_documents should NOT have been called (late vec used instead).
        mock_emb.embed_documents.assert_not_called()

        # Verify the late vec was actually written — query it back.
        manager.client.load_collection(manager.config.collection_name)
        rows = manager.client.query(
            collection_name=manager.config.collection_name,
            filter="id > 0",
            output_fields=["dense"],
            limit=1,
        )
        written = list(rows[0]["dense"])
        assert abs(written[0] - 0.9) < 1e-5, f"late vec not written, got {written}"
        manager.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
