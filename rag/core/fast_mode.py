"""
Fast Mode Pipeline for Enterprise RAG Platform

Skips the full LangGraph pipeline and directly retrieves + generates.
Uses one shared workflow invocation (which may perform one bounded changed
retry) and at most one LLM call. Weak/conflict/empty states skip generation.

Thinking mode (current graph): Intent → Agent → Retrieve → Grade → Generate  (4+ LLM calls)
Fast mode (this module):       Retrieve → Generate                               (1 LLM call)
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from core.prompts.profile_prompts import GENERATE_HUMAN_PROMPT, GENERATE_SYSTEM_PROMPT
from utils.log_utils import log
from utils.think_tag_utils import strip_think_tags

__all__ = [
    "FastModeResult",
    "fast_generate",
    "fast_generate_async",
    "fast_generate_stream",
]

# Module-level chain cache
_chain = None


@dataclass
class FastModeResult:
    answer: str
    sources: list[dict[str, Any]]
    retrieval_count: int
    retrieval_time_ms: float
    generation_time_ms: float
    retrieval_diagnostics: dict[str, Any] | None = None


def _terminal_message(state: str) -> str:
    if state == "conflict":
        return "检索到的资料存在无法自动消解的版本冲突，请指定适用版本或权威来源后重试。"
    if state == "weak":
        return "现有资料不足以可靠回答该问题，请补充更具体的范围、标识符或相关文档。"
    from core.prompts.domain_profile import get_active_profile

    return get_active_profile().empty_context_message


def _retrieve_sync(query: str, top_k: int, filter_expr: str | None = None):
    from core.retrieval.workflow import get_retrieval_workflow, retrieval_workflow_enabled

    if retrieval_workflow_enabled():
        result = get_retrieval_workflow().retrieve(
            query,
            final_k=top_k,
            filter_expr=filter_expr,
        )
        return result.documents, result
    from core.retrieval.hybrid_retriever import get_hybrid_retriever

    return get_hybrid_retriever().retrieve(
        query,
        top_k=top_k,
        filter_expr=filter_expr,
    ), None


async def _retrieve_async(query: str, top_k: int, filter_expr: str | None = None):
    from core.retrieval.workflow import get_retrieval_workflow, retrieval_workflow_enabled

    if retrieval_workflow_enabled():
        result = await get_retrieval_workflow().aretrieve(
            query,
            final_k=top_k,
            filter_expr=filter_expr,
        )
        return result.documents, result
    from core.retrieval.hybrid_retriever import get_hybrid_retriever

    return await get_hybrid_retriever().aretrieve(
        query,
        top_k=top_k,
        filter_expr=filter_expr,
    ), None


def _format_context(documents) -> str:
    """Format retrieved documents into context string.

    Delegates to the shared :mod:`core.retrieval.formatting` layer (the single
    source of truth for the evidence-line format). The Chinese fallback labels
    (未知来源/未知标题) are preserved via ``defaults`` so existing prompts are
    unaffected.
    """
    from core.retrieval.formatting import format_documents

    context, _ = format_documents(documents, defaults={"source": "未知来源", "title": "未知标题"})
    return context


def _prepare_documents(documents):
    from core.retrieval.evidence import (
        documents_to_evidence,
        evidence_to_document,
        prepare_evidence,
    )

    prepared = prepare_evidence(documents_to_evidence(documents), token_budget=2048)
    kept_documents = [evidence_to_document(item) for item in prepared["evidence"]]
    return prepared["context"], kept_documents


def _docs_to_sources(documents) -> list[dict[str, Any]]:
    """Convert retrieved Documents to source dicts for API response."""
    sources = []
    for doc in documents:
        meta = getattr(doc, "metadata", None) or {}
        content = doc.page_content if hasattr(doc, "page_content") else str(doc)
        sources.append(
            {
                "content": content[:500],
                "source": meta.get("source"),
                "title": meta.get("title"),
                "score": meta.get("score"),
                "retrieval_score": meta.get("retrieval_score"),
                "rerank_score": meta.get("rerank_score"),
                "rerank_applied": bool(meta.get("rerank_applied", False)),
            }
        )
    return sources


# Fast mode prompt — appends /no_think to suppress Qwen3 reasoning
_FAST_HUMAN_PROMPT = GENERATE_HUMAN_PROMPT.rstrip() + "\n\n/no_think"


def _get_chain(llm: BaseChatModel):
    """Build the generate chain (cached across calls)."""
    global _chain
    if _chain is None:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", GENERATE_SYSTEM_PROMPT),
                ("human", _FAST_HUMAN_PROMPT),
            ]
        )
        _chain = prompt | llm | StrOutputParser()
    return _chain


# Cache for the streaming prompt chain (no StrOutputParser — we iterate chunks directly)
_stream_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", GENERATE_SYSTEM_PROMPT),
        ("human", _FAST_HUMAN_PROMPT),
    ]
)


def fast_generate(
    query: str,
    top_k: int = 3,
    *,
    filter_expr: str | None = None,
) -> FastModeResult:
    """
    Fast mode: direct retrieve + generate (synchronous).
    Uses /no_think to suppress Qwen3 reasoning for lower latency.

    Args:
        query: User question
        top_k: Number of documents to retrieve

    Returns:
        FastModeResult with answer, sources, and timing info
    """
    # --- Retrieve ---
    t0 = time.perf_counter()
    documents, workflow_result = _retrieve_sync(query, top_k, filter_expr)
    retrieval_ms = (time.perf_counter() - t0) * 1000

    log.info(f"Fast mode retrieval: {len(documents)} docs, {retrieval_ms:.0f}ms")

    if workflow_result is not None and not workflow_result.should_generate:
        return FastModeResult(
            answer=_terminal_message(workflow_result.state.value),
            sources=_docs_to_sources(documents),
            retrieval_count=len(documents),
            retrieval_time_ms=retrieval_ms,
            generation_time_ms=0,
            retrieval_diagnostics=workflow_result.diagnostics,
        )

    if not documents:
        from core.prompts.domain_profile import get_active_profile

        return FastModeResult(
            answer=get_active_profile().empty_context_message,
            sources=[],
            retrieval_count=0,
            retrieval_time_ms=retrieval_ms,
            generation_time_ms=0,
        )

    # --- Generate ---
    context, kept_documents = _prepare_documents(documents)
    if not kept_documents or not context.strip():
        from core.prompts.domain_profile import get_active_profile

        return FastModeResult(
            answer=get_active_profile().empty_context_message,
            sources=[],
            retrieval_count=0,
            retrieval_time_ms=retrieval_ms,
            generation_time_ms=0,
        )

    from models.llm_models import get_llm

    llm = get_llm()
    chain = _get_chain(llm)

    t1 = time.perf_counter()
    answer = chain.invoke({"question": query, "context": context})
    answer = strip_think_tags(answer)
    gen_ms = (time.perf_counter() - t1) * 1000

    log.info(f"Fast mode generation: {len(answer)} chars, {gen_ms:.0f}ms")

    return FastModeResult(
        answer=answer,
        sources=_docs_to_sources(kept_documents),
        retrieval_count=len(kept_documents),
        retrieval_time_ms=retrieval_ms,
        generation_time_ms=gen_ms,
        retrieval_diagnostics=(
            workflow_result.diagnostics if workflow_result is not None else None
        ),
    )


async def fast_generate_stream(
    query: str,
    top_k: int = 3,
    *,
    filter_expr: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """
    Fast mode: direct retrieve + streaming generate.

    Yields SSE-style event dicts:
        {"type": "status", ...}
        {"type": "token", "content": ...}
        {"type": "sources", "data": [...]}
        {"type": "done", ...}

    Args:
        query: User question
        top_k: Number of documents to retrieve
    """
    # --- Retrieve ---
    t0 = time.perf_counter()
    documents, workflow_result = await _retrieve_async(query, top_k, filter_expr)
    retrieval_ms = (time.perf_counter() - t0) * 1000

    log.info(f"Fast mode retrieval: {len(documents)} docs, {retrieval_ms:.0f}ms")

    if workflow_result is not None and not workflow_result.should_generate:
        terminal = _terminal_message(workflow_result.state.value)
        yield {"type": "token", "content": terminal}
        yield {
            "type": "done",
            "full_response": terminal,
            "sources": _docs_to_sources(documents),
            "processing_time_ms": retrieval_ms,
            "retrieval_diagnostics": workflow_result.diagnostics,
        }
        return

    if not documents:
        from core.prompts.domain_profile import get_active_profile

        empty_msg = get_active_profile().empty_context_message
        yield {"type": "token", "content": empty_msg}
        # full_response must carry the same message as the non-streaming
        # path's `answer` (fast_generate), not an empty string (B5).
        yield {
            "type": "done",
            "full_response": empty_msg,
            "sources": [],
            "processing_time_ms": retrieval_ms,
        }
        return

    context, kept_documents = _prepare_documents(documents)
    if not kept_documents or not context.strip():
        from core.prompts.domain_profile import get_active_profile

        empty_msg = get_active_profile().empty_context_message
        yield {"type": "token", "content": empty_msg}
        yield {
            "type": "done",
            "full_response": empty_msg,
            "sources": [],
            "processing_time_ms": retrieval_ms,
        }
        return

    # --- Stream generate ---
    from models.llm_models import get_llm

    llm = get_llm()
    chain = _stream_prompt | llm

    t1 = time.perf_counter()
    full_response = ""
    async for chunk in chain.astream({"question": query, "context": context}):
        if hasattr(chunk, "content") and chunk.content:
            full_response += chunk.content
            yield {"type": "token", "content": chunk.content}
    gen_ms = (time.perf_counter() - t1) * 1000

    full_response = strip_think_tags(full_response)

    log.info(f"Fast mode stream done: {len(full_response)} chars, {gen_ms:.0f}ms")

    yield {
        "type": "done",
        "full_response": full_response,
        "sources": _docs_to_sources(kept_documents),
        "processing_time_ms": retrieval_ms + gen_ms,
        **(
            {"retrieval_diagnostics": workflow_result.diagnostics}
            if workflow_result is not None
            else {}
        ),
    }


async def fast_generate_async(
    query: str,
    top_k: int = 3,
    *,
    filter_expr: str | None = None,
) -> FastModeResult:
    """Native async fast mode for non-streaming API calls."""
    t0 = time.perf_counter()
    documents, workflow_result = await _retrieve_async(query, top_k, filter_expr)
    retrieval_ms = (time.perf_counter() - t0) * 1000
    if workflow_result is not None and not workflow_result.should_generate:
        return FastModeResult(
            answer=_terminal_message(workflow_result.state.value),
            sources=_docs_to_sources(documents),
            retrieval_count=len(documents),
            retrieval_time_ms=retrieval_ms,
            generation_time_ms=0,
            retrieval_diagnostics=workflow_result.diagnostics,
        )
    if not documents:
        from core.prompts.domain_profile import get_active_profile

        return FastModeResult(
            answer=get_active_profile().empty_context_message,
            sources=[],
            retrieval_count=0,
            retrieval_time_ms=retrieval_ms,
            generation_time_ms=0,
        )

    context, kept_documents = _prepare_documents(documents)
    if not kept_documents or not context.strip():
        from core.prompts.domain_profile import get_active_profile

        return FastModeResult(
            answer=get_active_profile().empty_context_message,
            sources=[],
            retrieval_count=0,
            retrieval_time_ms=retrieval_ms,
            generation_time_ms=0,
        )

    from models.llm_models import get_llm

    t1 = time.perf_counter()
    answer = await _get_chain(get_llm()).ainvoke({"question": query, "context": context})
    answer = strip_think_tags(answer)
    generation_ms = (time.perf_counter() - t1) * 1000
    return FastModeResult(
        answer=answer,
        sources=_docs_to_sources(kept_documents),
        retrieval_count=len(kept_documents),
        retrieval_time_ms=retrieval_ms,
        generation_time_ms=generation_ms,
        retrieval_diagnostics=(
            workflow_result.diagnostics if workflow_result is not None else None
        ),
    )
