"""Deterministic contextual index text separated from display evidence."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from langchain_core.documents import Document

__all__ = [
    "CONTEXTUAL_INDEX_VERSION",
    "ContextualText",
    "build_contextual_text",
    "contextualize_document",
    "contextualize_documents_if_enabled",
]

CONTEXTUAL_INDEX_VERSION = 1

_FIELDS: tuple[tuple[str, str], ...] = (
    ("source", "source"),
    ("title", "title"),
    ("title_path", "section"),
    ("page", "page"),
    ("content_type", "type"),
    ("revision", "revision"),
    ("effective_date", "effective_date"),
    ("status", "status"),
)


@dataclass(frozen=True)
class ContextualText:
    display_text: str
    index_text: str
    degraded: bool = False


def build_contextual_text(
    document: Document,
    *,
    max_field_chars: int = 160,
    max_prefix_chars: int = 800,
    max_index_chars: int = 4000,
) -> ContextualText:
    display = document.page_content or ""
    metadata = document.metadata if isinstance(document.metadata, dict) else {}
    fields: list[str] = []
    degraded = False
    for key, label in _FIELDS:
        value = metadata.get(key)
        if value in (None, ""):
            continue
        sanitized = _sanitize_value(value, source=(key == "source"))
        if not sanitized:
            degraded = True
            continue
        if len(sanitized) > max_field_chars:
            sanitized = sanitized[:max_field_chars]
            degraded = True
        fields.append(f"【{label}】{sanitized}")

    prefix = " | ".join(fields)
    if len(prefix) > max_prefix_chars:
        prefix = prefix[:max_prefix_chars]
        degraded = True
    if not prefix:
        return ContextualText(display, display[:max_index_chars], degraded)

    prefix = prefix[:max_index_chars]
    remaining = max(0, max_index_chars - len(prefix) - 2)
    body = display[:remaining]
    if len(body) < len(display):
        degraded = True
    return ContextualText(display, f"{prefix}\n\n{body}", degraded)


def contextualize_document(document: Document, **kwargs: Any) -> Document:
    contextual = build_contextual_text(document, **kwargs)
    metadata = dict(document.metadata)
    metadata.update(
        {
            "display_text": contextual.display_text,
            "index_text": contextual.index_text,
            "contextual_index_version": CONTEXTUAL_INDEX_VERSION,
        }
    )
    if contextual.degraded:
        metadata["contextual_index_degraded"] = True
    return Document(page_content=contextual.display_text, metadata=metadata)


def contextualize_documents_if_enabled(documents: list[Document]) -> list[Document]:
    """Prepare both Milvus and BM25 inputs when the isolated contextual index is enabled."""
    import os

    if os.getenv("CONTEXTUAL_INDEX_ENABLED", "false").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return documents
    return [contextualize_document(document) for document in documents]


def _sanitize_value(value: Any, *, source: bool = False) -> str:
    text = unicodedata.normalize("NFKC", str(value))
    if source:
        text = PurePosixPath(text.replace("\\", "/")).name
    cleaned = []
    for character in text:
        category = unicodedata.category(character)
        cleaned.append(" " if category in {"Cc", "Cf", "Cs"} else character)
    text = "".join(cleaned).replace("<", "‹").replace(">", "›")
    return re.sub(r"\s+", " ", text).strip()
