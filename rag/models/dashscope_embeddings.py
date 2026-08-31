"""DashScope text-embedding adapter (api-only deploy).

Thin LangChain ``Embeddings``-compatible client for Aliyun DashScope's native
text-embedding API. Uses ``httpx`` (already a dependency) — **no torch, no
sentence-transformers, no SDK**. The native API is chosen over DashScope's
OpenAI-compatible mode because it exposes ``text_type`` (query vs document),
a Chinese-embedding quality feature the compatible mode drops.

Contract: REQ-AO-003 ~ REQ-AO-007 (see docs/specs/api-only-deploy/). Embeddings
are write/search-critical (NOT a hot-path grading component), so on failure this
adapter RAISES to the caller — it never silently degrades to a zero vector
(AGENTS.md §0.3). The retriever layer's existing try/except turns query-path
failures into an empty candidate list (§0.5), which is the expected behaviour.

Security: ``DASHSCOPE_BASE_URL`` is operator-trusted (same posture as the
existing ``OPENAI_BASE_URL``), but ``_validate_base_url`` rejects non-http(s)
schemes to prevent local-protocol key leakage (design §9 / F-07).
"""

from __future__ import annotations

import time
from urllib.parse import urlparse

import httpx
from langchain_core.embeddings import Embeddings

from utils.log_utils import log

# DashScope v3/v4 supported dimensions for the ``dimension`` parameter.
# v1/v2 are fixed at 1536 and do NOT accept ``dimension`` — see ``_send_dimension``.
_V3_V4_DIMENSIONS = frozenset({1024, 768, 512, 256, 128, 64})
# Models that accept the ``dimension`` parameter. Other models (v1/v2 fixed-dim)
# omit it and rely on the model default; dimension mismatches then surface as
# Milvus insert errors (never silent — REQ-AO-005).
_DIMENSION_AWARE_MODELS = frozenset({"text-embedding-v3", "text-embedding-v4"})

# DashScope hard limit per request (also applies to the compatible mode).
_MAX_TEXTS_PER_REQUEST = 10

# Transient HTTP statuses worth retrying. 4xx (except 429) are business errors
# (bad request / bad key / invalid model) and are surfaced immediately.
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def _validate_base_url(base_url: str) -> None:
    """Reject non-http(s) schemes so a misconfigured DASHSCOPE_BASE_URL cannot
    exfiltrate the bearer key via a local protocol (file://, ftp://, ...).

    Operator-trust is otherwise preserved (host allow-listing is optional via
    DASHSCOPE_ALLOWED_HOSTS, mirroring HTTP_TOOL_ALLOWED_HOSTS); see design §9.
    """
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"DASHSCOPE_BASE_URL must use http or https, got scheme={parsed.scheme!r}")
    if not parsed.netloc:
        raise ValueError(f"DASHSCOPE_BASE_URL has no host: {base_url!r}")


class DashScopeEmbeddings(Embeddings):
    """LangChain ``Embeddings`` backed by the DashScope native text-embedding API.

    Stateless: holds only connection config; no on-disk persistence, so no
    module-level path attribute is required (AGENTS.md §6/§10).
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        dimension: int,
        timeout: float = 30.0,
        batch_size: int = _MAX_TEXTS_PER_REQUEST,
        max_retries: int = 2,
        retry_delay: float = 0.5,
        retry_backoff: float = 2.0,
    ) -> None:
        _validate_base_url(base_url)

        if batch_size < 1 or batch_size > _MAX_TEXTS_PER_REQUEST:
            raise ValueError(
                f"batch_size must be in [1, {_MAX_TEXTS_PER_REQUEST}], got {batch_size}"
            )

        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._dimension = dimension
        self._timeout = timeout
        self._batch_size = batch_size
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._retry_backoff = retry_backoff

        # F-03: only v3/v4 accept ``dimension``; other models use a fixed size.
        self._send_dimension = model in _DIMENSION_AWARE_MODELS
        if self._send_dimension and dimension not in _V3_V4_DIMENSIONS:
            raise ValueError(
                f"EMBEDDING_DIMENSION={dimension} is not supported by {model}; "
                f"valid values: {sorted(_V3_V4_DIMENSIONS)}. Either set "
                f"EMBEDDING_DIMENSION to one of those, or pick a non-v3/v4 model "
                f"(which ignores the dimension parameter)."
            )
        if not self._send_dimension:
            log.warning(
                f"DashScope model {model!r} does not accept the dimension parameter; "
                f"omitting it (EMBEDDING_DIMENSION={dimension} is used only for the "
                f"Milvus collection schema — a mismatch will surface on insert)."
            )

        log.info(
            f"DashScopeEmbeddings ready: model={model}, dimension={dimension}, "
            f"send_dimension={self._send_dimension}, base_url={self._base_url}"
        )

    # -- LangChain Embeddings interface -------------------------------------

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string (text_type=query)."""
        vectors = self._embed_batch([text], text_type="query")
        self._echo_check(vectors[0])
        return vectors[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple documents (text_type=document).

        DashScope caps each request at 10 texts; inputs are chunked and results
        reassembled in input order via ``text_index`` (REQ-AO-006).
        """
        if not texts:
            return []
        # Dict-keyed accumulation avoids a None-initialized typed list.
        placed: dict[int, list[float]] = {}
        for start in range(0, len(texts), self._batch_size):
            chunk = texts[start : start + self._batch_size]
            vectors = self._embed_batch(chunk, text_type="document")
            for offset, vector in enumerate(vectors):
                self._echo_check(vector)
                placed[start + offset] = vector
        return [placed[i] for i in range(len(texts))]

    # -- internals ----------------------------------------------------------

    def _build_payload(self, texts: list[str], text_type: str) -> dict[str, object]:
        parameters: dict[str, object] = {
            "text_type": text_type,
            "output_type": "dense",  # F-03: pin dense so parsing is unambiguous.
        }
        if self._send_dimension:
            parameters["dimension"] = self._dimension
        return {
            "model": self._model,
            "input": {"texts": texts},
            "parameters": parameters,
        }

    def _embed_batch(self, texts: list[str], text_type: str) -> list[list[float]]:
        payload = self._build_payload(texts, text_type)
        data = self._post(payload)
        embeddings = data.get("output", {}).get("embeddings", [])
        # Reassemble by text_index (defensive — API returns in input order).
        # A dict avoids the None-initialized typed-list workaround.
        placed: dict[int, list[float]] = {}
        for item in embeddings:
            idx = item.get("text_index")
            if not isinstance(idx, int) or not 0 <= idx < len(texts):
                raise RuntimeError(
                    f"DashScope returned out-of-range text_index={idx!r} "
                    f"for batch size {len(texts)}"
                )
            placed[idx] = list(item["embedding"])
        missing = [i for i in range(len(texts)) if i not in placed]
        if missing:
            raise RuntimeError(f"DashScope response missing embeddings for indices {missing}")
        ordered = [placed[i] for i in range(len(texts))]
        usage = data.get("usage", {})
        log.debug(
            f"DashScope embedded {len(texts)} texts ({text_type}); "
            f"tokens={usage.get('total_tokens')}"
        )
        return ordered

    def _echo_check(self, vector: list[float]) -> None:
        """F-01: assert the returned vector matches the expected dimension.
        Fires on every call so a wrong-dimension model is caught on first use
        rather than after a collection has been created at the wrong dim."""
        if len(vector) != self._dimension:
            raise RuntimeError(
                f"DashScope returned a {len(vector)}-dim vector but "
                f"EMBEDDING_DIMENSION={self._dimension}. The model and the "
                f"Milvus collection schema disagree — fix EMBEDDING_DIMENSION "
                f"or EMBEDDING_MODEL."
            )

    def _post(self, payload: dict[str, object]) -> dict[str, object]:
        """POST to the DashScope native embedding endpoint with retry.

        REQ-AO-007: transient HTTP errors are retried with backoff; on exhaustion
        or a business error, the exception propagates to the caller (never a
        zero vector / silent degradation).
        """
        url = f"{self._base_url}/api/v1/services/embeddings/text-embedding/text-embedding"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        last_exc: Exception | None = None
        delay = self._retry_delay
        for attempt in range(self._max_retries + 1):
            is_last = attempt == self._max_retries
            try:
                response = httpx.post(url, json=payload, headers=headers, timeout=self._timeout)
            except httpx.HTTPError as exc:
                last_exc = exc
                if not is_last:
                    log.warning(
                        f"DashScope request failed (attempt {attempt + 1}): {exc}; "
                        f"retry in {delay:.1f}s"
                    )
                    time.sleep(delay)
                    delay *= self._retry_backoff
                    continue
                break  # exhausted -> fall through to terminal raise

            status = response.status_code
            if status == 200:
                return response.json()

            body = response.text
            if status in _RETRYABLE_STATUS and not is_last:
                log.warning(
                    f"DashScope returned HTTP {status} (attempt {attempt + 1}); "
                    f"retry in {delay:.1f}s. body={body[:200]}"
                )
                time.sleep(delay)
                delay *= self._retry_backoff
                continue
            # Non-retryable (4xx business error) or retries exhausted.
            raise RuntimeError(
                f"DashScope embedding request failed: HTTP {status}, body={body[:500]}"
            )

        # Reached only when retries are exhausted on a network error.
        raise RuntimeError(f"DashScope request failed after retries: {last_exc}") from last_exc
