"""Facet- and parent-aware final evidence selection."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from langchain_core.documents import Document

__all__ = ["select_evidence"]


def select_evidence(
    documents: Sequence[Document],
    *,
    final_k: int,
    selection_k: int | None = None,
    facets: Sequence[str] = (),
) -> list[Document]:
    """Select distinct parents/orphans while retaining the full backfill reservoir."""
    if not documents or final_k <= 0:
        return []
    ranked = list(documents)
    primary_k = max(final_k, selection_k or final_k)
    selected: list[Document] = []
    selected_keys: set[str] = set()

    def add(document: Document) -> bool:
        key = _evidence_key(document)
        if key in selected_keys:
            return False
        selected.append(document)
        selected_keys.add(key)
        return True

    # Facet coverage may inspect the full ranked reservoir so a lower-ranked
    # missing facet is not hidden by the primary selection target.
    for facet in _unique_nonempty(facets):
        for document in ranked:
            matched = document.metadata.get("matched_facets", ())
            if isinstance(matched, str):
                matched = (matched,)
            if facet in matched and add(document):
                break
        if len(selected) >= final_k:
            return selected[:final_k]

    # Prefer the primary window, then continue through the full rerank reservoir
    # to backfill after duplicate child chunks collapse to one parent.
    for document in [*ranked[:primary_k], *ranked[primary_k:]]:
        add(document)
        if len(selected) >= final_k:
            break
    return selected[:final_k]


def _evidence_key(document: Document) -> str:
    metadata = document.metadata if isinstance(document.metadata, dict) else {}
    parent_id = metadata.get("parent_id")
    if parent_id:
        return f"parent:{parent_id}"
    explicit = metadata.get("chunk_id") or metadata.get("id")
    if explicit:
        return f"chunk:{explicit}"
    raw = "|".join(
        (
            str(metadata.get("source", "")),
            str(metadata.get("page", "")),
            document.page_content,
        )
    )
    return "orphan:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _unique_nonempty(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in values if value and value.strip()))
