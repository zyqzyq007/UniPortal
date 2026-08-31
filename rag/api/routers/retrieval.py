"""
Retrieval Router — 知识库向量/关键词检索

提供三种检索策略，全部不调用 LLM，仅做知识库匹配：
- 混合检索 (dense + active sparse backend + RRF/optional rerank)
- 纯向量检索 (dense only)
- 纯关键词检索 (BM25 sparse only)

These are low-level retrieval endpoints. Chat Fast/Thinking and MCP
rag_retrieve use the higher-level RetrievalWorkflow instead.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from utils.log_utils import log

router = APIRouter()


# =============================================================================
# Request / Response Models
# =============================================================================


class RetrievalRequest(BaseModel):
    query: str = Field(..., min_length=1, description="检索查询文本")
    top_k: int = Field(5, ge=1, le=50, description="返回结果数量")


class RetrievedDocument(BaseModel):
    content: str
    source: str = ""
    title: str = ""
    score: float = 0.0
    retrieval_score: float | None = None
    rerank_score: float | None = None
    rerank_applied: bool = False


class RetrievalResponse(BaseModel):
    query: str
    results: list[RetrievedDocument]
    total: int
    retrieval_time_ms: float


# =============================================================================
# Helpers
# =============================================================================


def _build_response(query: str, results, elapsed_ms: float) -> RetrievalResponse:
    docs = []
    for r in results:
        if hasattr(r, "page_content"):
            content = r.page_content
            meta = getattr(r, "metadata", {})
            score = meta.get("score", 0.0)
            source = meta.get("source", "")
            title = meta.get("title", "")
        elif hasattr(r, "text"):
            content = r.text
            score = getattr(r, "score", 0.0)
            meta = getattr(r, "metadata", {})
            source = meta.get("source", "")
            title = meta.get("title", "")
        elif hasattr(r, "document"):
            doc = r.document
            content = doc.page_content
            score = r.score
            meta = doc.metadata
            source = meta.get("source", "")
            title = meta.get("title", "")
        else:
            continue
        docs.append(
            RetrievedDocument(
                content=content,
                source=source,
                title=title,
                score=score,
                retrieval_score=meta.get("retrieval_score"),
                rerank_score=meta.get("rerank_score"),
                rerank_applied=bool(meta.get("rerank_applied", False)),
            )
        )
    return RetrievalResponse(
        query=query,
        results=docs,
        total=len(docs),
        retrieval_time_ms=elapsed_ms,
    )


# =============================================================================
# Endpoints
# =============================================================================


@router.post("", response_model=RetrievalResponse)
async def hybrid_retrieve(req: RetrievalRequest):
    """
    混合检索 — dense + 当前 sparse backend，RRF 融合并可选重排。

    适用场景：通用检索，兼顾语义匹配和关键词精确匹配。
    """
    from core.retrieval.hybrid_retriever import get_hybrid_retriever

    retriever = get_hybrid_retriever()
    start = time.perf_counter()
    try:
        results = await retriever.aretrieve(req.query, top_k=req.top_k)
    except Exception:
        log.exception("Hybrid retrieval failed")
        raise HTTPException(500, "检索失败，请稍后重试")
    elapsed = (time.perf_counter() - start) * 1000
    return _build_response(req.query, results, elapsed)


@router.post("/dense", response_model=RetrievalResponse)
async def dense_retrieve(req: RetrievalRequest):
    """
    纯向量检索 — 仅 dense embedding 相似度搜索，不经过 BM25。

    适用场景：语义匹配优先，如「意思相近但关键词不同」的查询。
    """
    from documents.milvus_db import get_milvus_manager

    manager = get_milvus_manager()
    start = time.perf_counter()
    try:
        results = await asyncio.to_thread(manager.search, query=req.query, top_k=req.top_k)
    except Exception:
        log.exception("Dense retrieval failed")
        raise HTTPException(500, "向量检索失败，请稍后重试")
    elapsed = (time.perf_counter() - start) * 1000
    return _build_response(req.query, results, elapsed)


@router.post("/sparse", response_model=RetrievalResponse)
async def sparse_retrieve(req: RetrievalRequest):
    """
    纯 BM25 关键词检索 — 仅词频匹配，不使用向量。

    适用场景：精确关键词匹配，如标识符、型号、错误代码。
    """
    from core.retrieval.hybrid_retriever import get_hybrid_retriever

    retriever = get_hybrid_retriever()
    start = time.perf_counter()
    try:
        # 确保通过 worker 线程访问 sparse_retriever 属性，
        # 避免首次调用时在事件循环上同步触发 Milvus->BM25 索引同步阻塞请求
        bm25 = await asyncio.to_thread(lambda: retriever.sparse_retriever)
        results = await asyncio.to_thread(bm25.retrieve, req.query, top_k=req.top_k)
    except Exception:
        log.exception("Sparse retrieval failed")
        raise HTTPException(500, "BM25 检索失败，请稍后重试")
    elapsed = (time.perf_counter() - start) * 1000
    return _build_response(req.query, results, elapsed)
