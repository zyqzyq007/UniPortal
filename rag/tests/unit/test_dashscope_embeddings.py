"""Unit tests for the DashScope embedding adapter.

Covers REQ-AO-003 ~ REQ-AO-007 and the critic/defender findings F-01 (dimension
echo check), F-03 (model-family branching + output_type), F-07 (base_url scheme
validation). All HTTP is mocked — no real DashScope calls (REQ-AO-012).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from models.dashscope_embeddings import (
    _V3_V4_DIMENSIONS,
    DashScopeEmbeddings,
    _validate_base_url,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULTS = {
    "api_key": "sk-test-key",
    "base_url": "https://dashscope.aliyuncs.com",
    "model": "text-embedding-v3",
    "dimension": 512,
}


def _make_response(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        content=json.dumps(payload),
        headers={"content-type": "application/json"},
        request=httpx.Request("POST", "https://x/"),
    )


def _ds_response(dim: int, count: int, usage_tokens: int = 25) -> dict:
    """Build a DashScope-shaped response with ``count`` vectors of length ``dim``."""
    return {
        "output": {
            "embeddings": [{"text_index": i, "embedding": [0.1] * dim} for i in range(count)]
        },
        "usage": {"total_tokens": usage_tokens},
        "request_id": "test-req",
    }


# ---------------------------------------------------------------------------
# Construction / validation
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_v3_dimension_must_be_valid(self):
        """REQ-AO-005 / F-03: v3 model rejects unsupported dimensions."""
        with pytest.raises(ValueError, match="not supported by text-embedding-v3"):
            DashScopeEmbeddings(**{**DEFAULTS, "dimension": 999})

    @pytest.mark.parametrize("dim", sorted(_V3_V4_DIMENSIONS))
    def test_v3_all_valid_dimensions_accepted(self, dim):
        emb = DashScopeEmbeddings(**{**DEFAULTS, "dimension": dim})
        assert emb._send_dimension is True
        assert emb._dimension == dim

    def test_v4_also_dimension_aware(self):
        emb = DashScopeEmbeddings(**{**DEFAULTS, "model": "text-embedding-v4"})
        assert emb._send_dimension is True

    def test_non_v3_model_skips_dimension_validation(self):
        """F-03: v1 (fixed 1536) accepts any dimension env value — it only
        governs the Milvus schema, not a sent parameter."""
        emb = DashScopeEmbeddings(**{**DEFAULTS, "model": "text-embedding-v1"})
        assert emb._send_dimension is False

    def test_batch_size_bounds_enforced(self):
        with pytest.raises(ValueError, match="batch_size"):
            DashScopeEmbeddings(**{**DEFAULTS, "batch_size": 0})
        with pytest.raises(ValueError, match="batch_size"):
            DashScopeEmbeddings(**{**DEFAULTS, "batch_size": 11})


class TestBaseUrlValidation:
    """F-07: reject non-http(s) schemes to prevent key exfiltration."""

    @pytest.mark.parametrize(
        "url",
        ["file:///etc/passwd", "ftp://host/", "gopher://x", "data:text/plain,x"],
    )
    def test_non_http_schemes_rejected(self, url):
        with pytest.raises(ValueError, match="must use http or https"):
            _validate_base_url(url)
        with pytest.raises(ValueError, match="must use http or https"):
            DashScopeEmbeddings(**{**DEFAULTS, "base_url": url})

    def test_missing_host_rejected(self):
        with pytest.raises(ValueError, match="no host"):
            _validate_base_url("https://")

    def test_http_https_accepted(self):
        _validate_base_url("http://internal-gateway:8080")
        _validate_base_url("https://dashscope.aliyuncs.com")


# ---------------------------------------------------------------------------
# Payload shape (golden)
# ---------------------------------------------------------------------------


class TestPayload:
    def _capture_payload(self, emb, text_type, texts):
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            captured["timeout"] = timeout
            return _make_response(_ds_response(emb._dimension, len(texts)))

        return captured, fake_post

    def test_endpoint_url_and_headers(self):
        emb = DashScopeEmbeddings(**DEFAULTS)
        captured, fake = self._capture_payload(emb, "query", ["x"])
        with patch("models.dashscope_embeddings.httpx.post", side_effect=fake):
            emb.embed_query("x")
        assert (
            captured["url"]
            == "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
        )
        assert captured["headers"]["Authorization"] == "Bearer sk-test-key"
        assert captured["headers"]["Content-Type"] == "application/json"

    def test_query_payload_golden(self):
        """REQ-AO-003/004: query request body golden snapshot."""
        emb = DashScopeEmbeddings(**DEFAULTS)
        captured, fake = self._capture_payload(emb, "query", ["hello"])
        with patch("models.dashscope_embeddings.httpx.post", side_effect=fake):
            emb.embed_query("hello")
        assert captured["json"] == {
            "model": "text-embedding-v3",
            "input": {"texts": ["hello"]},
            "parameters": {
                "text_type": "query",
                "output_type": "dense",
                "dimension": 512,
            },
        }

    def test_document_payload_golden(self):
        """REQ-AO-004: documents use text_type=document."""
        emb = DashScopeEmbeddings(**DEFAULTS)
        captured, fake = self._capture_payload(emb, "document", ["a", "b"])
        with patch("models.dashscope_embeddings.httpx.post", side_effect=fake):
            emb.embed_documents(["a", "b"])
        assert captured["json"]["parameters"]["text_type"] == "document"
        assert captured["json"]["parameters"]["dimension"] == 512
        assert captured["json"]["input"]["texts"] == ["a", "b"]

    def test_v1_model_payload_omits_dimension(self):
        """F-03: non-v3 models must not send the dimension parameter."""
        emb = DashScopeEmbeddings(**{**DEFAULTS, "model": "text-embedding-v1"})
        captured, fake = self._capture_payload(emb, "query", ["x"])
        with patch("models.dashscope_embeddings.httpx.post", side_effect=fake):
            # echo check compares against EMBEDDING_DIMENSION (512) by default;
            # _ds_response returns 512-wide vectors so it passes.
            emb.embed_query("x")
        assert "dimension" not in captured["json"]["parameters"]
        assert captured["json"]["parameters"] == {
            "text_type": "query",
            "output_type": "dense",
        }


# ---------------------------------------------------------------------------
# Chunking + order preservation (REQ-AO-006)
# ---------------------------------------------------------------------------


class TestChunking:
    def test_more_than_10_texts_are_chunked_and_reordered(self):
        emb = DashScopeEmbeddings(**DEFAULTS)  # batch_size default = 10
        texts = [f"doc-{i}" for i in range(25)]

        sent_batches: list[list[str]] = []

        def fake_post(url, json=None, headers=None, timeout=None):
            texts_in = json["input"]["texts"]
            sent_batches.append(texts_in)
            # Return shuffled order to prove reassembly by text_index.
            resp = {
                "output": {
                    "embeddings": [
                        {"text_index": i, "embedding": [float(hash(t) % 100)] * 512}
                        for i, t in enumerate(texts_in)
                    ][::-1]
                },
                "usage": {"total_tokens": 1},
            }
            return _make_response(resp)

        with patch("models.dashscope_embeddings.httpx.post", side_effect=fake_post):
            result = emb.embed_documents(texts)

        assert len(result) == 25
        # Three chunks of 10/10/5.
        assert [len(b) for b in sent_batches] == [10, 10, 5]
        # Order preserved despite shuffled responses.
        for i, vec in enumerate(result):
            assert vec == [float(hash(f"doc-{i}") % 100)] * 512

    def test_empty_documents_returns_empty(self):
        emb = DashScopeEmbeddings(**DEFAULTS)
        assert emb.embed_documents([]) == []


# ---------------------------------------------------------------------------
# Dimension echo check (F-01)
# ---------------------------------------------------------------------------


class TestDimensionEcho:
    def test_query_echo_check_raises_on_dimension_mismatch(self):
        """F-01: a wrong-dimension response is caught at the adapter, not later."""
        emb = DashScopeEmbeddings(**{**DEFAULTS, "dimension": 512})

        def fake_post(url, json=None, headers=None, timeout=None):
            # Server returns 1024-wide vectors despite dimension=512 requested.
            return _make_response(_ds_response(1024, 1))

        with patch("models.dashscope_embeddings.httpx.post", side_effect=fake_post):
            with pytest.raises(RuntimeError, match="1024-dim vector but EMBEDDING_DIMENSION=512"):
                emb.embed_query("x")

    def test_documents_echo_check_raises_on_dimension_mismatch(self):
        emb = DashScopeEmbeddings(**{**DEFAULTS, "dimension": 512})

        def fake_post(url, json=None, headers=None, timeout=None):
            return _make_response(_ds_response(1024, 2))

        with patch("models.dashscope_embeddings.httpx.post", side_effect=fake_post):
            with pytest.raises(RuntimeError, match="1024-dim vector"):
                emb.embed_documents(["a", "b"])

    def test_search_cold_path_dim_mismatch_raises(self):
        """F-01 regression: even when the Milvus collection was created first
        (search cold path), the first embed_query must still raise via the echo
        check rather than silently returning a mismatched vector."""
        emb = DashScopeEmbeddings(**{**DEFAULTS, "dimension": 512})

        def fake_post(url, json=None, headers=None, timeout=None):
            return _make_response(_ds_response(1024, 1))

        with patch("models.dashscope_embeddings.httpx.post", side_effect=fake_post):
            with pytest.raises(RuntimeError):
                emb.embed_query("late-query")


# ---------------------------------------------------------------------------
# Retry + error propagation (REQ-AO-007)
# ---------------------------------------------------------------------------


class TestRetryAndErrors:
    def test_transient_500_retried_then_succeeds(self):
        emb = DashScopeEmbeddings(**DEFAULTS)
        calls = {"n": 0}

        def fake_post(url, json=None, headers=None, timeout=None):
            calls["n"] += 1
            if calls["n"] < 2:
                return _make_response({"message": "boom"}, status=500)
            return _make_response(_ds_response(512, 1))

        with (
            patch("models.dashscope_embeddings.httpx.post", side_effect=fake_post),
            patch("models.dashscope_embeddings.time.sleep"),
        ):
            vec = emb.embed_query("x")
        assert calls["n"] == 2
        assert len(vec) == 512

    def test_4xx_not_retried_propagates_immediately(self):
        emb = DashScopeEmbeddings(**DEFAULTS)
        calls = {"n": 0}

        def fake_post(url, json=None, headers=None, timeout=None):
            calls["n"] += 1
            return _make_response({"message": "bad model"}, status=400)

        with (
            patch("models.dashscope_embeddings.httpx.post", side_effect=fake_post),
            patch("models.dashscope_embeddings.time.sleep"),
        ):
            with pytest.raises(RuntimeError, match="HTTP 400"):
                emb.embed_query("x")
        assert calls["n"] == 1

    def test_network_error_retried_then_raises(self):
        emb = DashScopeEmbeddings(**DEFAULTS)
        calls = {"n": 0}

        def fake_post(url, json=None, headers=None, timeout=None):
            calls["n"] += 1
            raise httpx.ConnectError("refused")

        with (
            patch("models.dashscope_embeddings.httpx.post", side_effect=fake_post),
            patch("models.dashscope_embeddings.time.sleep"),
        ):
            with pytest.raises(RuntimeError, match="failed after retries"):
                emb.embed_query("x")
        assert calls["n"] == emb._max_retries + 1

    def test_missing_embedding_in_response_raises(self):
        emb = DashScopeEmbeddings(**DEFAULTS)

        def fake_post(url, json=None, headers=None, timeout=None):
            return _make_response({"output": {"embeddings": []}, "usage": {}})

        with patch("models.dashscope_embeddings.httpx.post", side_effect=fake_post):
            with pytest.raises(RuntimeError, match="missing embeddings"):
                emb.embed_query("x")
