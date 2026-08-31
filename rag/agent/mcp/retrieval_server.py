"""
MCP Retrieval Server

Exposes retrieval tools via the MCP protocol:
- rag_retrieve: shared adaptive/corrective workflow (legacy hybrid when disabled)
- rag_search_dense: dense-only vector search
- rag_search_sparse: BM25-only keyword search

The current server is in-process. The default rag_retrieve result contains
documents plus redacted workflow diagnostics; see docs/MCP.md.
"""

from __future__ import annotations

import time
from typing import Any

from langchain_core.documents import Document

from agent.mcp.server import InProcessMCPServer, MCPServerConfig
from utils.log_utils import log

__all__ = ["MCPRetrievalServer"]


class MCPRetrievalServer(InProcessMCPServer):
    """
    MCP server that exposes RAG retrieval as MCP tools.

    Delegates to the shared RetrievalWorkflow for rag_retrieve and keeps
    explicit dense/BM25 low-level tools for diagnostics and baselines.
    """

    def __init__(
        self,
        default_top_k: int = 4,
        config: MCPServerConfig | None = None,
    ):
        server_config = config or MCPServerConfig(
            name="rag-retrieval-server",
            description="MCP server for RAG retrieval tools",
        )
        super().__init__(server_config)
        self._default_top_k = default_top_k
        self._register_tools()

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_tools(self) -> None:
        """Register all retrieval tools on this server."""

        # --- rag_retrieve: hybrid retrieval ---
        from core.prompts.domain_profile import get_active_profile

        self.register_tool(
            name="rag_retrieve",
            description=get_active_profile().retriever_tool_description,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return",
                        "default": self._default_top_k,
                    },
                    "filter_expr": {
                        "type": "string",
                        "description": (
                            "Optional Milvus boolean expression to pre-filter "
                            'dense candidates, e.g. source == "engine_manual"'
                        ),
                    },
                    "transform": {
                        "type": "string",
                        "description": ("Optional query transform: 'hyde' or 'multi_query'"),
                    },
                },
                "required": ["query"],
            },
            handler=self._hybrid_retrieve,
        )

        # --- rag_search_dense: dense-only vector search ---
        self.register_tool(
            name="rag_search_dense",
            description=(
                "Dense vector search in the knowledge base. "
                "Returns documents ranked by semantic similarity."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return",
                        "default": self._default_top_k,
                    },
                },
                "required": ["query"],
            },
            handler=self._dense_search,
        )

        # --- rag_search_sparse: BM25 keyword search ---
        self.register_tool(
            name="rag_search_sparse",
            description=(
                "Sparse (BM25) keyword search in the knowledge base. "
                "Returns documents ranked by keyword matching."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return",
                        "default": self._default_top_k,
                    },
                },
                "required": ["query"],
            },
            handler=self._sparse_search,
        )

        log.info("MCPRetrievalServer: 3 retrieval tools registered")

    # ------------------------------------------------------------------
    # Handler implementations (delegate to existing code)
    # ------------------------------------------------------------------

    def _hybrid_retrieve(
        self,
        query: str,
        top_k: int | None = None,
        filter_expr: str | None = None,
        transform: str | None = None,
    ) -> Any:
        """
        Shared adaptive/corrective retrieval, with a legacy hybrid fallback.

        ``filter_expr`` is enforced by the workflow's typed capability routing.
        ``transform`` is a legacy-path compatibility input; the default planner
        selects its own bounded transform. See docs/MCP.md for both result shapes.
        """
        top_k = top_k or self._default_top_k

        start = time.perf_counter()
        try:
            from core.retrieval.workflow import (
                get_retrieval_workflow,
                retrieval_workflow_enabled,
            )

            if retrieval_workflow_enabled():
                workflow_result = get_retrieval_workflow().retrieve(
                    query,
                    filter_expr=filter_expr,
                    final_k=top_k,
                )
                elapsed_ms = (time.perf_counter() - start) * 1000
                log.info(
                    f"MCP workflow retrieval: {len(workflow_result.documents)} docs, "
                    f"{elapsed_ms:.0f}ms, state={workflow_result.state.value}"
                )
                return {
                    "documents": self._format_documents(workflow_result.documents),
                    "diagnostics": workflow_result.diagnostics,
                }

            from core.retrieval.hybrid_retriever import get_hybrid_retriever

            retriever = get_hybrid_retriever()
            if transform == "multi_query":
                from core.retrieval.query_transform import multi_query_retrieve

                documents = multi_query_retrieve(
                    query, retriever, top_k=top_k, filter_expr=filter_expr
                )
            elif transform == "hyde":
                from core.retrieval.query_transform import hyde

                hyde_query = hyde(query)
                documents = retriever.retrieve(hyde_query, top_k=top_k, filter_expr=filter_expr)
            else:
                documents = retriever.retrieve(query, top_k=top_k, filter_expr=filter_expr)
            elapsed_ms = (time.perf_counter() - start) * 1000

            log.info(
                f"MCP rag_retrieve: {len(documents)} docs, "
                f"{elapsed_ms:.0f}ms"
                f"{', filtered=true' if filter_expr else ''}"
                f"{f', transform={transform}' if transform else ''}"
            )
            return self._format_documents(documents)

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            log.error(
                f"MCP rag_retrieve failed ({elapsed_ms:.0f}ms), " f"error_type={type(exc).__name__}"
            )
            raise

    def _dense_search(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        """Dense-only retrieval via MilvusManager."""
        top_k = top_k or self._default_top_k

        start = time.perf_counter()
        try:
            from agent.mcp.retriever_tools import RetrieverConfig, RetrieverManager

            config = RetrieverConfig(top_k=top_k, use_hybrid=False)
            with RetrieverManager(config) as manager:
                documents = manager.search(query, top_k=top_k)
            elapsed_ms = (time.perf_counter() - start) * 1000

            log.info(f"MCP rag_search_dense: {len(documents)} docs, " f"{elapsed_ms:.0f}ms")
            return self._format_documents(documents)

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            log.error(
                f"MCP rag_search_dense failed ({elapsed_ms:.0f}ms), "
                f"error_type={type(exc).__name__}"
            )
            raise

    def _sparse_search(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        """Sparse-only BM25 retrieval.

        Uses the hybrid retriever's shared BM25 index (which is auto-synced
        from Milvus on first access). Previously this constructed a brand-new
        empty ``BM25Retriever()`` per call, which always returned zero results
        because the index was never populated.
        """
        top_k = top_k or self._default_top_k

        start = time.perf_counter()
        try:
            from core.retrieval.hybrid_retriever import get_hybrid_retriever

            retriever = get_hybrid_retriever()
            results = retriever.sparse_retriever.retrieve(query, top_k=top_k)
            documents = [r.document for r in results]
            elapsed_ms = (time.perf_counter() - start) * 1000

            log.info(f"MCP rag_search_sparse: {len(documents)} docs, " f"{elapsed_ms:.0f}ms")
            return self._format_documents(documents)

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            log.error(
                f"MCP rag_search_sparse failed ({elapsed_ms:.0f}ms), "
                f"error_type={type(exc).__name__}"
            )
            raise

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_documents(documents: list[Document]) -> list[dict[str, Any]]:
        """Convert LangChain Documents to MCP-friendly dicts."""
        results = []
        for idx, doc in enumerate(documents, 1):
            meta = getattr(doc, "metadata", None) or {}
            content = doc.page_content if hasattr(doc, "page_content") else str(doc)
            results.append(
                {
                    "index": idx,
                    "content": content,
                    "source": meta.get("source", "unknown"),
                    "title": meta.get("title", "unknown"),
                    "score": meta.get("score"),
                    # parent_id MUST be carried through so the retrieve skill can
                    # expand small chunks to parent sections (small-to-big). Without
                    # this, MCP deployments silently no-op the expand (critic F-RB-01).
                    "parent_id": meta.get("parent_id"),
                }
            )
        return results

    @staticmethod
    def documents_to_tool_content(documents: list[Document]) -> str:
        """
        Format documents into the content string that the ToolMessage
        node expects (mirrors the format used by LangChain's ToolNode).
        """
        parts: list[str] = []
        for idx, doc in enumerate(documents, 1):
            text = doc.page_content.strip() if hasattr(doc, "page_content") else str(doc).strip()
            if not text:
                continue
            meta = getattr(doc, "metadata", None) or {}
            source = meta.get("source", "unknown")
            title = meta.get("title", "unknown")
            score = meta.get("score")
            score_text = f"{float(score):.4f}" if isinstance(score, int | float) else "N/A"
            parts.append(f"[证据{idx}] 来源={source} | 标题={title} | 相关度={score_text}\n{text}")
        return "\n\n".join(parts)
