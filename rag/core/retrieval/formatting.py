"""
Shared document-context formatting for the RAG pipeline.

Three call sites previously duplicated the same ``[证据N] 来源=... | 标题=... |
相关度=...`` evidence-line formatting:

  - ``RetrieveSkill._format_documents`` (retrieve/skill.py)
  - ``GenerateSkill._extract_context`` + ``_extract_relevance_scores``
    (generate/skill.py)
  - ``core/fast_mode._format_context``

The duplication created a fragile cross-module string contract: GenerateSkill
regex-parsed the ``相关度=X`` markers that the other two emitted, so any
change in one place silently broke score extraction elsewhere.

This module centralises:
  - :func:`format_documents` — build the evidence context string + a parallel
    list of structured :class:`FormattedDoc` records (one per chunk), so
    consumers no longer have to re-parse the string.
  - :func:`parse_relevance_scores` — the single source of truth for reading
    scores back out of a formatted context (kept for backward compat with
    callers that receive a plain string).

The output string is byte-for-byte compatible with the previous hand-rolled
versions, so existing prompts and tests are unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "FormattedDoc",
    "format_documents",
    "parse_relevance_scores",
    "format_score",
]


@dataclass
class FormattedDoc:
    """Structured view of one formatted evidence chunk."""

    index: int  # 1-based
    source: str
    title: str
    score: float | None
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def score_text(self) -> str:
        return format_score(self.score)

    def to_evidence_line(self) -> str:
        """Render the ``[证据N] 来源=... | 标题=... | 相关度=...`` header line."""
        return (
            f"[证据{self.index}] 来源={self.source} | 标题={self.title} | 相关度={self.score_text}"
        )


def format_score(score: Any) -> str:
    """Render a retrieval score the way the evidence line expects."""
    if isinstance(score, (int, float)):
        return f"{float(score):.4f}"
    return "N/A"


def _doc_fields(doc: Any, idx: int, defaults: dict[str, str]) -> FormattedDoc:
    """Extract the common fields from a Document-like object."""
    text = doc.page_content.strip() if hasattr(doc, "page_content") else str(doc).strip()
    meta = getattr(doc, "metadata", None) or {}
    return FormattedDoc(
        index=idx,
        source=meta.get("source", defaults.get("source", "unknown")),
        title=meta.get("title", defaults.get("title", "unknown")),
        score=meta.get("score") if isinstance(meta.get("score"), (int, float)) else None,
        content=text,
        metadata=dict(meta) if isinstance(meta, dict) else {},
    )


def format_documents(
    documents: list[Any],
    defaults: dict[str, str] | None = None,
) -> tuple[str, list[FormattedDoc]]:
    """
    Format a list of documents into the shared evidence-context string.

    Args:
        documents: Document-like objects with ``page_content`` + ``metadata``.
        defaults: optional override for the source/title fallback strings
            (e.g. fast-mode uses ``未知来源``/``未知标题``). Defaults to
            ``unknown``/``unknown`` to match the retrieve/generate paths.

    Returns:
        (context_string, formatted_docs) where ``formatted_docs`` parallels
        the chunks that actually made it into the string (empty-content docs
        are skipped, preserving previous behaviour).

    The context string is identical to what the previous per-module
    implementations produced, so prompts/tests are unaffected.
    """
    dv = defaults or {}
    parts: list[str] = []
    formatted: list[FormattedDoc] = []
    out_idx = 0
    for doc in documents:
        fields = _doc_fields(doc, out_idx + 1, dv)
        if not fields.content:
            continue
        out_idx += 1
        parts.append(f"{fields.to_evidence_line()}\n{fields.content}")
        formatted.append(fields)
    return "\n\n".join(parts), formatted


def parse_relevance_scores(context: str) -> list[float]:
    """
    Extract the ``相关度=X`` scores from a formatted evidence-context string.

    This is the single authoritative parser; GenerateSkill previously had its
    own copy. Scores are returned in document order. Non-numeric markers are
    skipped.
    """
    import re

    scores: list[float] = []
    for m in re.finditer(r"相关度=([\d.]+)", context):
        try:
            scores.append(float(m.group(1)))
        except ValueError:
            continue
    return scores
