"""Per-document relevance scoring with multi-signal fusion (F3).

The original GradeSkill grades the whole context blob as a binary yes/no — coarse
and can't rank individual documents. This module adds per-document continuous
scoring that fuses:

- **LLM relevance grade** (per-document binary → 1.0/0.0, via structured output).
- **Reranker score** (continuous, from the cross-encoder's metadata when present).
- **Embedding similarity** (cosine, fallback when reranker is unavailable).

The fused score ∈ [0, 1] drives filtering (drop below threshold) + re-ranking
(more relevant docs first). The binary routing gate (generate vs rewrite) stays
in GradeSkill — this is a complementary precision layer.

Degrades gracefully: if LLM grading fails, falls back to rerank-score-only; if
that's absent, returns docs unchanged (never blocks the pipeline).
"""

from __future__ import annotations

import asyncio

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate

from utils.log_utils import log

__all__ = ["score_documents", "ascore_documents"]

# Weight allocation for multi-signal fusion (sum = 1.0).
# Reranker is the strongest signal (cross-encoder); LLM grade catches semantic
# relevance the reranker misses; embedding sim is a weak fallback.
W_RERANK = 0.5
W_LLM_GRADE = 0.4
W_EMBED_SIM = 0.1

# Default filter threshold: documents below this fused score are dropped.
DEFAULT_MIN_SCORE = 0.3


def _per_doc_prompt() -> ChatPromptTemplate:
    """Build from the active profile so prompt content has one source of truth."""
    from core.prompts.domain_profile import get_active_profile

    prompts = get_active_profile().prompts
    return ChatPromptTemplate.from_messages(
        [
            ("system", prompts["per_doc_grade_system"]),
            ("human", prompts["per_doc_grade_human"]),
        ]
    )


def _parse_llm_grade(result) -> float | None:
    """Accept only an explicit JSON boolean; malformed output is unavailable."""
    if not isinstance(result, dict) or "relevant" not in result:
        return None
    value = result["relevant"]
    if type(value) is bool:
        return 1.0 if value else 0.0
    return None


def _llm_grade_document(llm, question: str, doc_text: str) -> float | None:
    """Grade a single document via LLM → 1.0 (relevant) or 0.0 (not). Best-effort."""
    try:
        structured = llm.with_structured_output(dict, method="json_mode")
        chain = _per_doc_prompt() | structured
        from core.retrieval.evidence import render_untrusted_text

        result = chain.invoke(
            {"question": question[:300], "doc_text": render_untrusted_text(doc_text[:500])}
        )
        return _parse_llm_grade(result)
    except Exception:  # noqa: BLE001 — best-effort
        return None


async def _allm_grade_document(llm, question: str, doc_text: str) -> float | None:
    """Async single-document LLM grade."""
    try:
        structured = llm.with_structured_output(dict, method="json_mode")
        chain = _per_doc_prompt() | structured
        from core.retrieval.evidence import render_untrusted_text

        result = await chain.ainvoke(
            {"question": question[:300], "doc_text": render_untrusted_text(doc_text[:500])}
        )
        return _parse_llm_grade(result)
    except Exception:  # noqa: BLE001
        return None


def _get_rerank_score(doc: Document) -> float | None:
    """Return a valid reranker signal on a common [0, 1] scale."""
    from core.retrieval.scoring import probability, raw_logit_probability

    value = probability(doc.metadata.get("rerank_prob"))
    if value is not None:
        return value
    return raw_logit_probability(doc.metadata.get("rerank_score"))


def _fused_score(
    llm_grade: float | None,
    rerank_score: float | None,
    embed_sim: float | None,
) -> float | None:
    """Fuse signals into a single [0, 1] score. Missing signals redistribute weight."""
    signals: list[tuple[float, float]] = []
    if llm_grade is not None:
        signals.append((llm_grade, W_LLM_GRADE))
    if rerank_score is not None:
        signals.append((rerank_score, W_RERANK))
    if embed_sim is not None:
        signals.append((embed_sim, W_EMBED_SIM))
    total_w = sum(w for _, w in signals)
    return sum(s * w for s, w in signals) / total_w if total_w > 0 else None


def _select_scored_documents(
    scored: list[tuple[float | None, Document]], min_score: float
) -> list[Document]:
    passing: list[tuple[float, Document]] = []
    evaluated: list[tuple[float, Document]] = []
    degraded: list[Document] = []
    for score, document in scored:
        metadata = dict(document.metadata)
        if score is None:
            metadata["score_degraded"] = True
            degraded.append(Document(page_content=document.page_content, metadata=metadata))
            continue
        metadata["grade_score"] = round(score, 4)
        scored_document = Document(page_content=document.page_content, metadata=metadata)
        evaluated.append((score, scored_document))
        if score >= min_score:
            passing.append((score, scored_document))

    if passing:
        passing.sort(key=lambda item: item[0], reverse=True)
        return [document for _, document in passing] + degraded
    if evaluated:
        return [max(evaluated, key=lambda item: item[0])[1]] + degraded
    return degraded


def score_documents(
    question: str,
    documents: list[Document],
    llm,
    min_score: float = DEFAULT_MIN_SCORE,
) -> list[Document]:
    """Score + filter documents by fused relevance (sync).

    Each document gets a continuous fused score (LLM grade + rerank + embed sim).
    Documents below ``min_score`` are dropped; survivors are re-ranked by score.
    Degrades to rerank-only (if LLM fails) or unchanged (if all signals absent).
    """
    if not documents:
        return documents
    scored: list[tuple[float | None, Document]] = []
    for doc in documents:
        rerank = _get_rerank_score(doc)
        embed_sim = None
        try:
            llm_grade = _llm_grade_document(llm, question, doc.page_content)
        except Exception:  # noqa: BLE001
            llm_grade = None
        fused = _fused_score(llm_grade, rerank, embed_sim)
        scored.append((fused, doc))
    selected = _select_scored_documents(scored, min_score)
    log.debug(f"per-doc scoring: {len(selected)}/{len(documents)} docs retained")
    return selected


async def ascore_documents(
    question: str,
    documents: list[Document],
    llm,
    min_score: float = DEFAULT_MIN_SCORE,
) -> list[Document]:
    """Score + filter documents by fused relevance (async, concurrent grading)."""
    if not documents:
        return documents

    async def _score_one(doc: Document) -> tuple[float | None, Document]:
        rerank = _get_rerank_score(doc)
        embed_sim = None
        llm_grade = await _allm_grade_document(llm, question, doc.page_content)
        fused = _fused_score(llm_grade, rerank, embed_sim)
        return fused, doc

    results = await asyncio.gather(*[_score_one(d) for d in documents], return_exceptions=True)
    scored: list[tuple[float | None, Document]] = []
    for document, result in zip(documents, results):
        if isinstance(result, Exception):
            scored.append((None, document))
            continue
        scored.append(result)
    selected = _select_scored_documents(scored, min_score)
    log.debug(f"per-doc scoring (async): {len(selected)}/{len(documents)} docs retained")
    return selected
