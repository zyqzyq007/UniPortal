"""
Time-decay retrieval scoring (P3.7).

Boosts recently-indexed documents over stale ones — useful when manuals get
updated and the latest revision should rank higher for the same query.

Applied as a multiplicative factor on the retrieval score AFTER RRF fusion but
BEFORE reranking/MMR. The decay is gentle (half-life configurable, default
180 days) so historical docs are not excluded — just slightly demoted vs fresh
revisions of the same content.

Requires documents to carry a ``created_at`` (unix timestamp) or ``timestamp``
metadata field; docs without timestamps pass through unaffected.
"""

from __future__ import annotations

import math
import os
import time

from langchain_core.documents import Document

__all__ = ["apply_time_decay", "DEFAULT_HALF_LIFE_DAYS"]


def _half_life_days() -> float:
    try:
        return max(1.0, float(os.getenv("RETRIEVAL_HALF_LIFE_DAYS", "180")))
    except (TypeError, ValueError):
        return 180.0


DEFAULT_HALF_LIFE_DAYS = 180.0


def _decay_factor(doc_age_days: float, half_life: float) -> float:
    """
    Multiplicative decay factor in (0, 1].

    factor = 0.5 ^ (age / half_life) — a doc half its relevance at `half_life`
    days old, quarter at 2x half_life, etc. Capped at 1.0 (fresh) and floored
    at 0.1 (very old docs keep 10% to stay retrievable).
    """
    if doc_age_days <= 0:
        return 1.0
    factor = math.pow(0.5, doc_age_days / half_life)
    return max(0.1, min(1.0, factor))


def apply_time_decay(
    documents: list[Document],
    half_life_days: float | None = None,
    now: float | None = None,
) -> list[Document]:
    """
    Apply gentle time-decay to retrieval scores.

    Docs without a ``created_at`` / ``timestamp`` metadata field are returned
    unchanged (backward compatible). The decay is multiplicative on the
    existing ``metadata["score"]``.
    """
    if not documents:
        return documents

    half_life = half_life_days if half_life_days is not None else _half_life_days()
    now_ts = now if now is not None else time.time()

    decayed: list[Document] = []
    for doc in documents:
        meta = doc.metadata if isinstance(doc.metadata, dict) else {}
        ts = meta.get("created_at") or meta.get("timestamp")
        if not ts:
            decayed.append(doc)
            continue
        try:
            ts = float(ts)
        except (TypeError, ValueError):
            decayed.append(doc)
            continue

        age_days = (now_ts - ts) / 86400.0
        factor = _decay_factor(age_days, half_life)
        old_score = meta.get("score", 1.0)
        try:
            old_score = float(old_score)
        except (TypeError, ValueError):
            old_score = 1.0
        new_meta = dict(meta)
        new_meta["score"] = old_score * factor
        new_meta["time_decay_factor"] = round(factor, 3)
        decayed.append(Document(page_content=doc.page_content, metadata=new_meta))

    return decayed
