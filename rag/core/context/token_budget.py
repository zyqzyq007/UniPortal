"""
Token-budget-aware context management for RAG.

Replaces the legacy character-slice truncation (``ctx[:2500]``) which could
cut mid-token/multibyte and drop high-relevance chunks appended last.

Two responsibilities:
  1. estimate_tokens — cheap token estimate without loading a tokenizer
     (Chinese ~ 1.5 chars/token, English ~ 4 chars/token heuristic; falls back
     to a fraction of LLM_MAX_TOKENS budget).
  2. build_context_within_budget — greedily pack retrieved chunks into the
     context window by descending relevance, so the most relevant evidence is
     always kept and only the least-relevant tail is dropped.

The packing respects a reserved budget for the question + answer + prompt
overhead (default: 25% of the model window).
"""

from __future__ import annotations

from langchain_core.documents import Document

from utils.log_utils import log

__all__ = [
    "estimate_tokens",
    "build_context_within_budget",
    "DEFAULT_CONTEXT_RESERVE_FRACTION",
]


def estimate_tokens(text: str) -> int:
    """
    Cheap token estimate without a tokenizer dependency.

    Heuristic: CJK characters count ~1.5 chars/token, ASCII ~4 chars/token.
    This is deliberately conservative (over-estimates slightly) so we err on
    the side of NOT overflowing the model window.
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return int(cjk / 1.5 + other / 4) + 1


# Fraction of the model window reserved for system prompt + question + answer.
DEFAULT_CONTEXT_RESERVE_FRACTION = 0.25


def _model_window() -> int:
    """The LLM context window size (tokens). Defaults to 32k for Qwen3."""
    try:
        from utils.env_utils import LLM_MAX_TOKENS

        # LLM_MAX_TOKENS is the generation budget; the *context window* is
        # typically larger (32k for qwen3:14b). Use the larger of the two so
        # we don't under-pack on default configs.
        return max(LLM_MAX_TOKENS, 32768)
    except Exception:  # noqa: BLE001
        return 32768


def build_context_within_budget(
    documents: list[Document],
    question: str = "",
    context_token_budget: int | None = None,
    reserve_fraction: float = DEFAULT_CONTEXT_RESERVE_FRACTION,
) -> tuple[str, list[Document]]:
    """
    Pack retrieved documents into a context string that fits the token budget.

    Documents are sorted by descending ``metadata["score"]`` (relevance) so the
    most relevant evidence is always kept; lower-relevance chunks are dropped
    first when the budget is exceeded.

    Args:
        documents: retrieved chunks (any order).
        question: the user question (its token cost is reserved).
        context_token_budget: explicit budget for the context block. When None,
            it is derived as ``(1 - reserve_fraction) * model_window -
            tokens(question)``.
        reserve_fraction: fraction of the window reserved for prompt+answer
            when budget is auto-derived.

    Returns:
        (context_string, kept_documents) where kept_documents is the subset
        that actually fit (in packing order).
    """
    if not documents:
        return "", []

    window = _model_window()
    if context_token_budget is None:
        reserve = max(int(window * reserve_fraction), estimate_tokens(question))
        context_token_budget = max(512, window - reserve)

    # Sort by descending relevance score; missing scores rank last but keep
    # their relative order (stable sort).
    def _score(d: Document) -> float:
        s = d.metadata.get("score") if isinstance(d.metadata, dict) else None
        try:
            return float(s) if s is not None else -1.0
        except (TypeError, ValueError):
            return -1.0

    ordered = sorted(documents, key=_score, reverse=True)

    kept: list[Document] = []
    used = 0
    for doc in ordered:
        chunk = doc.page_content
        cost = estimate_tokens(chunk) + 2  # +2 for the separator/newlines
        if used + cost > context_token_budget and kept:
            # Budget exhausted; skip the rest.
            break
        kept.append(doc)
        used += cost

    if len(kept) < len(ordered):
        log.info(
            f"Token budget packing: kept {len(kept)}/{len(documents)} chunks "
            f"({used}/{context_token_budget} tokens)"
        )

    # Re-assemble in relevance order with a light marker.
    parts = []
    for i, doc in enumerate(kept, 1):
        source = doc.metadata.get("source", "")
        marker = f"[证据{i}]" + (f" 来源={source}" if source else "")
        parts.append(f"{marker}\n{doc.page_content}")

    context = "\n\n".join(parts)
    return context, kept
