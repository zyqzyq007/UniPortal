"""Request-local query representations shared by retrieval channels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from utils.log_utils import log

__all__ = ["QueryRepresentation", "QueryRepresentationProvider"]


@dataclass(frozen=True)
class QueryRepresentation:
    dense: list[float] | None = None
    sparse: dict[int, float] | None = None
    colbert: Any | None = None
    degraded: bool = False
    errors: tuple[str, ...] = ()
    forward_count: int = 0
    model_fingerprint: str = "unknown"


class QueryRepresentationProvider:
    """Encode one query once and publish an immutable request-local object."""

    def __init__(self, embedding: Any):
        self._embedding = embedding

    def encode(self, query: str, include_colbert: bool = False) -> QueryRepresentation:
        from core.retrieval.cache import embedding_fingerprint

        fingerprint = embedding_fingerprint(self._embedding)
        try:
            if hasattr(self._embedding, "encode_query_representation"):
                raw = self._embedding.encode_query_representation(
                    query,
                    return_colbert=include_colbert,
                )
                dense = _field(raw, "dense")
                sparse = _field(raw, "sparse")
                colbert = _field(raw, "colbert") if include_colbert else None
            elif hasattr(self._embedding, "encode_hybrid"):
                dense, sparse = self._embedding.encode_hybrid(query)
                colbert = None
            else:
                dense = self._embedding.embed_query(query)
                sparse = None
                colbert = None
            return QueryRepresentation(
                dense=list(dense) if dense is not None else None,
                sparse={int(key): float(value) for key, value in sparse.items()}
                if sparse is not None
                else None,
                colbert=colbert,
                degraded=False,
                forward_count=1,
                model_fingerprint=fingerprint,
            )
        except Exception as exc:  # hot path: atomic failure, never escape
            log.warning(
                f"Query representation unavailable; safe fallback required: {type(exc).__name__}"
            )
            return QueryRepresentation(
                dense=None,
                sparse=None,
                colbert=None,
                degraded=True,
                errors=("query_representation_unavailable",),
                forward_count=1,
                model_fingerprint=fingerprint,
            )


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
