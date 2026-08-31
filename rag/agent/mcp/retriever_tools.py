"""
RAG Retriever Tools - Optimized for Low-Resource Servers

Features:
    - Lazy initialization (resources loaded only when needed)
    - Memory-efficient design for 4GB RAM servers
    - Configurable search parameters
    - Connection pooling and reuse
    - Proper error handling and retry logic
    - Context manager support for resource cleanup
    - Simple caching to reduce repeated queries
"""

from __future__ import annotations

import gc
import time
from dataclasses import dataclass, field

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.tools import create_retriever_tool
from pydantic import ConfigDict

from core.prompts.profile_prompts import RETRIEVER_TOOL_DESCRIPTION, RETRIEVER_TOOL_NAME
from documents.milvus_db import MilvusConfig, MilvusManager
from utils.env_utils import COLLECTION_NAME, MILVUS_URI
from utils.log_utils import log

__all__ = [
    "RetrieverConfig",
    "RetrieverManager",
    "get_retriever_tool",
    "get_retriever",
]


@dataclass
class RetrieverConfig:
    """
    Configuration for retriever optimized for low-resource servers.

    Default values are conservative for 4GB RAM, 4-core CPU servers.
    """

    # Milvus connection
    milvus_uri: str = MILVUS_URI
    collection_name: str = COLLECTION_NAME

    # Search parameters
    top_k: int = 4
    score_threshold: float = 0.1

    # Performance tuning for low memory
    enable_cache: bool = True
    cache_maxsize: int = 128  # Small cache to reduce memory usage

    # Retry settings
    max_retries: int = 2
    retry_delay: float = 1.0

    # Hybrid retrieval
    use_hybrid: bool = True  # Enable hybrid (dense + BM25) retrieval

    # Tool metadata
    tool_name: str = RETRIEVER_TOOL_NAME
    tool_description: str = RETRIEVER_TOOL_DESCRIPTION


class RetrieverManager:
    """
    Retriever manager with lazy initialization and resource management.

    Designed for low-resource servers:
    - Lazy loads embedding model and Milvus connection
    - Supports context manager for proper cleanup
    - Optional caching to reduce repeated queries
    - Memory-efficient operations
    """

    def __init__(self, config: RetrieverConfig | None = None) -> None:
        self.config = config or RetrieverConfig()
        self._manager: MilvusManager | None = None
        self._initialized = False

        log.debug(f"RetrieverManager created: collection={self.config.collection_name}")

    @property
    def manager(self) -> MilvusManager:
        """Get MilvusManager instance (lazy initialization)."""
        if self._manager is None:
            milvus_config = MilvusConfig(
                uri=self.config.milvus_uri,
                collection_name=self.config.collection_name,
            )
            self._manager = MilvusManager(milvus_config)
        return self._manager

    def _ensure_initialized(self) -> None:
        """Ensure connection is initialized."""
        if not self._initialized:
            self.manager._ensure_collection_loaded()
            self._initialized = True

    def search(
        self,
        query: str,
        top_k: int | None = None,
    ) -> list[Document]:
        """
        Search for similar documents.

        Args:
            query: Search query string
            top_k: Number of results to return (default from config)

        Returns:
            List of Document objects with similarity scores
        """
        top_k = top_k or self.config.top_k

        for attempt in range(self.config.max_retries + 1):
            try:
                self._ensure_initialized()

                results = self.manager.search(
                    query=query,
                    top_k=top_k,
                )

                # Convert SearchResult to Document with score filtering
                documents = []
                for result in results:
                    if result.score >= self.config.score_threshold:
                        documents.append(result.to_document())

                log.debug(
                    f"Search returned {len(documents)} documents (threshold={self.config.score_threshold})"
                )
                return documents

            except Exception as e:
                log.warning(f"Search attempt {attempt + 1} failed: {e}")
                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    log.error(f"Search failed after {self.config.max_retries + 1} attempts: {e}")
                    raise

        return []

    def close(self) -> None:
        """Close connections and free resources."""
        if self._manager is not None:
            self._manager.close()
            self._manager = None
            self._initialized = False

        # Force garbage collection
        gc.collect()
        log.debug("RetrieverManager resources released")

    def __enter__(self) -> RetrieverManager:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


class MilvusRetriever(BaseRetriever):
    """
    LangChain-compatible retriever.

    Supports both dense-only (Milvus) and hybrid (dense + BM25) retrieval
    based on configuration.
    """

    # Pydantic V2 config
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Configuration fields that shouldn't be included in serialization
    config: RetrieverConfig = field(default_factory=RetrieverConfig)
    _manager: RetrieverManager | None = None
    _hybrid_retriever = None

    def __init__(self, config: RetrieverConfig | None = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config or RetrieverConfig()
        self._manager = None
        self._hybrid_retriever = None

    @property
    def manager(self) -> RetrieverManager:
        """Get RetrieverManager instance (lazy initialization)."""
        if self._manager is None:
            self._manager = RetrieverManager(self.config)
        return self._manager

    @property
    def hybrid_retriever(self):
        """Get HybridRetriever instance (lazy initialization)."""
        if self._hybrid_retriever is None:
            from core.retrieval.hybrid_retriever import HybridRetriever, HybridRetrieverConfig

            hybrid_config = HybridRetrieverConfig(
                final_top_k=self.config.top_k,
            )
            self._hybrid_retriever = HybridRetriever(
                dense_manager=self.manager.manager,
                config=hybrid_config,
            )
        return self._hybrid_retriever

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager=None,
    ) -> list[Document]:
        """Get relevant documents for a query using hybrid or dense retrieval."""
        if self.config.use_hybrid:
            try:
                return self.hybrid_retriever.retrieve(query, top_k=self.config.top_k)
            except Exception as e:
                log.warning(f"Hybrid retrieval failed, falling back to dense: {e}")
        return self.manager.search(query)

    def close(self) -> None:
        """Close connections and free resources."""
        if self._manager is not None:
            self._manager.close()
            self._manager = None


# =============================================================================
# Module-level helpers with lazy initialization
# =============================================================================

# Global instances (lazy loaded)
_retriever_manager: RetrieverManager | None = None
_retriever: MilvusRetriever | None = None
_retriever_tool = None


def get_retriever_manager(config: RetrieverConfig | None = None) -> RetrieverManager:
    """
    Get or create a RetrieverManager instance.

    Uses a global instance for efficiency, but creates new one
    if different config is provided.

    Args:
        config: Retriever configuration (uses defaults if not provided)

    Returns:
        RetrieverManager instance
    """
    global _retriever_manager

    if _retriever_manager is None or (config is not None and config != _retriever_manager.config):
        # Clean up old instance
        if _retriever_manager is not None:
            _retriever_manager.close()

        _retriever_manager = RetrieverManager(config)
        log.debug("Created new RetrieverManager instance")

    return _retriever_manager


def get_retriever(config: RetrieverConfig | None = None) -> MilvusRetriever:
    """
    Get or create a LangChain-compatible retriever.

    Uses a global instance for efficiency.

    Args:
        config: Retriever configuration (uses defaults if not provided)

    Returns:
        MilvusRetriever instance
    """
    global _retriever

    if _retriever is None or (config is not None):
        _retriever = MilvusRetriever(config)
        log.debug("Created new MilvusRetriever instance")

    return _retriever


def get_retriever_tool(
    config: RetrieverConfig | None = None,
    force_new: bool = False,
):
    """
    Get or create a retriever tool for use with LangChain agents.

    This is the main entry point for creating retriever tools.
    Uses lazy initialization to avoid loading resources until needed.

    Args:
        config: Retriever configuration (uses defaults if not provided)
        force_new: Force creation of new tool instance

    Returns:
        LangChain retriever tool

    Example:
        >>> tool = get_retriever_tool()
        >>> # Use with agent
        >>> agent = create_tool_calling_agent(llm, [tool], prompt)
    """
    global _retriever_tool

    if _retriever_tool is None or force_new:
        retriever = get_retriever(config)
        _retriever_tool = create_retriever_tool(
            retriever,
            config.tool_name if config else RETRIEVER_TOOL_NAME,
            config.tool_description if config else RETRIEVER_TOOL_DESCRIPTION,
        )
        log.debug("Created new retriever tool")

    return _retriever_tool


def cleanup_retriever_resources() -> None:
    """
    Clean up all retriever-related resources.

    Call this when experiencing memory issues or when done
    using the retriever tools.
    """
    global _retriever_manager, _retriever, _retriever_tool

    if _retriever_manager is not None:
        _retriever_manager.close()
        _retriever_manager = None

    if _retriever is not None:
        _retriever.close()
        _retriever = None

    _retriever_tool = None

    gc.collect()
    log.info("Retriever resources cleaned up")


# =============================================================================
# CLI for testing
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="RAG Retriever Tools Test")
    parser.add_argument(
        "--query",
        type=str,
        default="git 合并冲突如何解决？",
        help="Test query",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=4,
        help="Number of results",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Clean up resources after search",
    )

    args = parser.parse_args()

    print(f"\n{'=' * 60}")
    print("RAG Retriever Test")
    print(f"{'=' * 60}")
    print(f"Query: {args.query}")
    print(f"Top-K: {args.top_k}")
    print(f"{'=' * 60}\n")

    try:
        # Use context manager for proper cleanup
        config = RetrieverConfig(top_k=args.top_k)

        with RetrieverManager(config) as manager:
            results = manager.search(args.query)

            print(f"Found {len(results)} documents:\n")
            for i, doc in enumerate(results, 1):
                score = doc.metadata.get("score", 0)
                print(f"--- Document {i} (score: {score:.4f}) ---")
                print(f"Source: {doc.metadata.get('source', 'N/A')}")
                print(f"Title: {doc.metadata.get('title', 'N/A')}")
                print(f"Content: {doc.page_content[:200]}...")
                print()

    except Exception as e:
        print(f"Error: {e}")
        raise

    finally:
        if args.cleanup:
            cleanup_retriever_resources()
            print("Resources cleaned up.\n")

    print(f"{'=' * 60}")
    print("Test completed")
    print(f"{'=' * 60}\n")
