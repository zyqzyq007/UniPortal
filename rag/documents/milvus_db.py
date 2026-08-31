"""
Milvus Vector Database Manager - Lightweight Version

Optimized for low-resource servers (4GB RAM, limited CPU).

Features:
    - Lazy initialization to minimize memory footprint
    - Small batch sizes for memory efficiency
    - Explicit resource cleanup
    - Simplified architecture without singleton pattern
    - Memory-conscious embedding model loading
"""

from __future__ import annotations

import gc
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, TypeVar

from langchain_core.documents import Document
from pymilvus import DataType, MilvusClient, MilvusException
from pymilvus.client.types import MetricType

from utils.env_utils import COLLECTION_NAME
from utils.log_utils import log

# Type variables
T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Any])


class SearchMode(Enum):
    """Search mode enumeration."""

    DENSE_ONLY = "dense_only"
    SPARSE_ONLY = "sparse_only"
    HYBRID = "hybrid"


def _env(name: str, default: str) -> str:
    """Read a live attribute from utils.env_utils so test harnesses can
    redirect paths at runtime (AGENTS.md §6/§10 path sealability). Bypasses
    the def-time binding of a module-level constant default."""
    try:
        import utils.env_utils as _env_mod

        return getattr(_env_mod, name)
    except (ImportError, AttributeError):
        return default


def _env_int(name: str, default: int) -> int:
    return int(_env(name, str(default)))  # type: ignore[arg-type]


def _env_bool(name: str, default: bool) -> bool:
    """Read a bool attribute from utils.env_utils live (test-sealable)."""
    try:
        import utils.env_utils as _env_mod

        return bool(getattr(_env_mod, name))
    except (ImportError, AttributeError):
        return default


@dataclass
class MilvusConfig:
    """
    Configuration optimized for low-resource servers.

    Default values are conservative for 4GB RAM servers.
    Index type defaults to AUTOINDEX for Milvus Lite compatibility; on a
    standalone Milvus server set ``MILVUS_INDEX_TYPE=HNSW`` (or IVF_FLAT) plus
    ``MILVUS_INDEX_PARAMS`` / ``MILVUS_SEARCH_PARAMS`` for tunable recall.
    """

    uri: str = field(
        default_factory=lambda: __import__(
            "utils.env_utils", fromlist=["resolve_milvus_uri"]
        ).resolve_milvus_uri()
    )
    collection_name: str = field(
        default_factory=lambda: _env("COLLECTION_NAME", "rag_knowledge_base")
    )
    dense_dim: int = field(
        default_factory=lambda: (
            __import__("utils.env_utils", fromlist=["resolve_embedding_settings"])
            .resolve_embedding_settings()
            .dimension
        )
    )
    max_text_length: int = 4000  # Reduced from 6000
    max_metadata_length: int = 500  # Reduced from 1000
    batch_size: int = 20  # Small batch size for low memory
    max_retries: int = 3
    retry_delay: float = 2.0  # Longer delay for slow servers
    retry_backoff: float = 2.0
    connection_timeout: float = 60.0  # Longer timeout
    consistency_level: str = "Bounded"  # Less strict than "Strong"

    # Index type + build/search params. AUTOINDEX auto-tunes; HNSW/IVF accept
    # explicit params parsed from env (JSON). See _parse_index_env below.
    index_type: str = ""
    index_params: dict[str, Any] | None = None
    search_params: dict[str, Any] | None = None

    # Extra dynamic-field metadata to return from search (alongside the base
    # text/source/title). These are written as dynamic fields at insert time
    # (e.g. page, content_type, file_hash from PDF parsing). Listing them here
    # makes them visible to retriever formatting / grounding; previously search
    # returned only text/source/title and the rich chunk metadata was lost.
    extra_output_fields: tuple = (
        "page",
        "chunk_id",
        "content_type",
        "file_hash",
        "parent_id",
        "title_path",
        "display_text",
        "index_text",
        "contextual_index_version",
        "revision",
        "effective_date",
        "status",
        "authority",
        "document_family",
    )

    # Contextual index changes vector/sparse contents and therefore must be used
    # only with a new collection. Dynamic fields keep legacy schemas readable.
    contextual_index: bool = field(
        default_factory=lambda: _env_bool("CONTEXTUAL_INDEX_ENABLED", False)
    )

    # Native sparse vector (docs/specs/retrieval-backend-modernization, F-02).
    # When True, the collection gains a SPARSE_FLOAT_VECTOR field + SPARSE_INVERTED_INDEX,
    # and the sparse retrieval leg uses Milvus sparse_search (BGE-M3 lexical_weights)
    # instead of the self-implemented BM25. F-01: filter goes through search(filter=),
    # a first-class param — NOT hybrid_search's top-level filter (pymilvus 2.5.18 drops it).
    enable_sparse: bool = field(
        default_factory=lambda: (
            __import__("utils.env_utils", fromlist=["resolve_embedding_settings"])
            .resolve_embedding_settings()
            .sparse_enabled
        )
    )

    def __post_init__(self):
        # Read env vars live (not from cached module constants) so runtime
        # overrides and test monkeypatching take effect.
        import os

        if not self.index_type:
            self.index_type = os.getenv("MILVUS_INDEX_TYPE", "AUTOINDEX") or "AUTOINDEX"
        if self.index_params is None:
            self.index_params = _parse_index_env(os.getenv("MILVUS_INDEX_PARAMS"))
        if self.search_params is None:
            self.search_params = _parse_index_env(os.getenv("MILVUS_SEARCH_PARAMS"))


def _parse_index_env(raw: str | None) -> dict[str, Any] | None:
    """Parse a JSON index/search params env var; None on empty/invalid."""
    if not raw or not raw.strip():
        return None
    import json

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        log.warning(f"Invalid MILVUS_*_PARAMS JSON, ignored: {raw!r}")
    return None


@dataclass
class SearchResult:
    """Search result container."""

    id: int
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_document(self) -> Document:
        return Document(page_content=self.text, metadata={"score": self.score, **self.metadata})


class MilvusConnectionError(Exception):
    """Connection error."""

    pass


class MilvusOperationError(Exception):
    """Operation error."""

    pass


def retry_on_failure(
    max_retries: int | None = None,
    delay: float | None = None,
    backoff: float | None = None,
    exceptions: tuple[type, ...] = (MilvusException, ConnectionError, TimeoutError),
) -> Callable[[F], F]:
    """Retry decorator with exponential backoff."""

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(self: MilvusManager, *args: Any, **kwargs: Any) -> Any:
            config = self.config
            _max_retries = max_retries or config.max_retries
            _delay = delay or config.retry_delay
            _backoff = backoff or config.retry_backoff

            last_exception: Exception | None = None
            current_delay = _delay

            for attempt in range(_max_retries + 1):
                try:
                    return func(self, *args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < _max_retries:
                        log.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}): {e}. "
                            f"Retry in {current_delay:.1f}s..."
                        )
                        time.sleep(current_delay)
                        current_delay *= _backoff
                    else:
                        log.error(f"{func.__name__} failed after {_max_retries + 1} attempts")

            raise MilvusOperationError(
                f"{func.__name__} failed after {_max_retries + 1} retries"
            ) from last_exception

        return wrapper  # type: ignore

    return decorator


def _get_embedding_function():
    """
    Reuse the global singleton embedding model, wrapped with a query-embedding
    cache so repeated queries skip the (CPU-bound) embedding call.

    Delegates to models.embedding_models.get_local_embeddings() to ensure
    only one model instance is loaded across the entire process. The cache is
    opt-out via env ``RETRIEVAL_CACHE_ENABLED`` (default on) and only caches
    query embeddings (document embeddings are write-path, not cached).
    """
    from models.embedding_models import get_local_embeddings

    base = get_local_embeddings()

    import os

    if os.getenv("RETRIEVAL_CACHE_ENABLED", "true").lower() in ("1", "true", "yes", "on"):
        try:
            from core.retrieval.cache import cached_embedding_function

            return cached_embedding_function(base)
        except Exception:  # noqa: BLE001 - caching is best-effort
            return base
    return base


class MilvusManager:
    """
    Lightweight Milvus manager for low-resource servers.

    Key optimizations:
    - No singleton pattern (works with multiprocessing)
    - Lazy embedding model loading
    - Small default batch sizes
    - Explicit cleanup methods
    - Memory-efficient operations
    """

    def __init__(self, config: MilvusConfig | None = None) -> None:
        """Initialize with lazy loading."""
        self.config = config or MilvusConfig()
        self._client: MilvusClient | None = None
        self._embedding_fn = None  # Lazy loaded
        self._collection_loaded = False

        log.debug(f"MilvusManager created: {self.config.collection_name}")

    @property
    def client(self) -> MilvusClient:
        """Get Milvus client (lazy initialization)."""
        if self._client is None:
            self._connect()
        return self._client

    @property
    def embedding_function(self):
        """Get embedding function (lazy initialization)."""
        if self._embedding_fn is None:
            log.info("Loading embedding model...")
            self._embedding_fn = _get_embedding_function()
            log.info("Embedding model loaded")
        return self._embedding_fn

    def _connect(self) -> None:
        """Connect to Milvus server."""
        if self._client is not None:
            return

        try:
            self._client = MilvusClient(uri=self.config.uri, timeout=self.config.connection_timeout)
            log.info(f"Connected to Milvus: {self.config.uri}")
        except Exception as e:
            raise MilvusConnectionError(f"Connection failed: {e}") from e

    def close(self) -> None:
        """
        Explicitly close connections and free memory.

        Call this when done to release resources.
        """
        if self._client is not None:
            client = self._client
            try:
                if self._collection_loaded:
                    try:
                        client.release_collection(self.config.collection_name)
                    except Exception:
                        pass
            except Exception:
                pass
            finally:
                try:
                    client.close()
                except Exception:
                    pass
                self._client = None
                self._collection_loaded = False

        # Clear embedding function to free memory
        self._embedding_fn = None

        # Force garbage collection
        gc.collect()
        log.debug("MilvusManager resources released")

    def __enter__(self) -> MilvusManager:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - cleanup resources."""
        self.close()

    @retry_on_failure()
    def create_collection(self, drop_if_exists: bool = False) -> bool:
        """Create collection with lightweight schema."""
        log.info(f"Creating collection: {self.config.collection_name}")

        if self.config.collection_name in self.client.list_collections():
            if drop_if_exists:
                log.info("Dropping existing collection")
                try:
                    self.client.release_collection(self.config.collection_name)
                except Exception:
                    pass
                self.client.drop_collection(self.config.collection_name)
            else:
                log.info("Collection already exists")
                return True

        # Create schema
        schema = self.client.create_schema(auto_id=True, enable_dynamic_field=True)

        # Essential fields only
        schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field(
            field_name="text",
            datatype=DataType.VARCHAR,
            max_length=self.config.max_text_length,
            enable_analyzer=True,
            analyzer_params={"tokenizer": "jieba"},
        )
        schema.add_field(
            field_name="dense", datatype=DataType.FLOAT_VECTOR, dim=self.config.dense_dim
        )
        # Native sparse vector field (F-02). BGE-M3 lexical_weights enable Milvus
        # sparse_search to replace the self-implemented BM25 leg. Gated by
        # enable_sparse so MILVUS_SPARSE_INDEX=false reverts to the legacy schema.
        if self.config.enable_sparse:
            schema.add_field(field_name="sparse", datatype=DataType.SPARSE_FLOAT_VECTOR)
        # Metadata fields
        schema.add_field(
            field_name="source",
            datatype=DataType.VARCHAR,
            max_length=self.config.max_metadata_length,
        )
        schema.add_field(
            field_name="title",
            datatype=DataType.VARCHAR,
            max_length=self.config.max_metadata_length,
        )

        # Create index params. AUTOINDEX auto-tunes (Milvus Lite compatible);
        # HNSW / IVF_FLAT accept explicit build params from config.index_params.
        index_params = self.client.prepare_index_params()
        index_kwargs: dict[str, Any] = {
            "field_name": "dense",
            "index_type": self.config.index_type,
            "metric_type": MetricType.IP,
        }
        if self.config.index_params:
            index_kwargs.update(self.config.index_params)
        index_params.add_index(**index_kwargs)

        # Sparse vector index (F-02): SPARSE_INVERTED_INDEX with IP metric.
        if self.config.enable_sparse:
            index_params.add_index(
                field_name="sparse",
                index_type="SPARSE_INVERTED_INDEX",
                metric_type=MetricType.IP,
            )

        # Create collection
        self.client.create_collection(
            collection_name=self.config.collection_name, schema=schema, index_params=index_params
        )

        # Bind the embedding model fingerprint to this collection so a later
        # model swap (which would corrupt retrieval) is detectable.
        try:
            from documents.embedding_registry import get_registry

            get_registry().register(
                collection=self.config.collection_name,
                model_name=self._embedding_model_name(),
                dimension=self.config.dense_dim,
                sparse_enabled=self.config.enable_sparse,
            )
        except Exception as e:
            try:
                self.client.drop_collection(self.config.collection_name)
            except Exception:  # noqa: BLE001 - preserve the registry root cause
                pass
            raise MilvusOperationError(
                "Collection creation aborted because embedding fingerprint registration failed"
            ) from e

        log.info(f"Collection created: {self.config.collection_name}")
        return True

    def _embedding_model_name(self) -> str:
        """The actual embedding loader source used for fingerprinting."""
        from utils.env_utils import resolve_embedding_settings

        settings = resolve_embedding_settings()
        source = settings.model_source
        enable_sparse = getattr(
            getattr(self, "config", None),
            "enable_sparse",
            settings.sparse_enabled,
        )
        if enable_sparse:
            from models.bge_m3_embeddings import bge_m3_hybrid_asset_fingerprint

            source = f"{source}#hybrid-heads:{bge_m3_hybrid_asset_fingerprint(source)}"
        return source

    def collection_compatibility(self) -> dict[str, Any]:
        """Return the effective collection/embedding compatibility verdict."""
        try:
            if self.config.collection_name not in self.client.list_collections():
                return {
                    "compatible": True,
                    "reason": "collection_missing",
                    "record": None,
                }
            description = self.client.describe_collection(self.config.collection_name)
            fields = {
                field.get("name"): field
                for field in description.get("fields", [])
                if isinstance(field, dict) and field.get("name")
            }
            dense = fields.get("dense") or {}
            dense_params = dense.get("params") if isinstance(dense.get("params"), dict) else {}
            try:
                actual_dimension = int(dense_params.get("dim"))
            except (TypeError, ValueError):
                actual_dimension = None
            if actual_dimension != self.config.dense_dim:
                return {
                    "compatible": False,
                    "reason": "schema_dimension_mismatch",
                    "record": None,
                }
            actual_sparse = "sparse" in fields
            if actual_sparse != self.config.enable_sparse:
                return {
                    "compatible": False,
                    "reason": "schema_sparse_mismatch",
                    "record": None,
                }
            from documents.embedding_registry import get_registry

            return get_registry().compatibility(
                self.config.collection_name,
                self._embedding_model_name(),
                self.config.dense_dim,
                self.config.enable_sparse,
            )
        except Exception as e:  # noqa: BLE001 - report degraded without leaking internals
            log.warning(f"Collection compatibility check unavailable: {e}")
            return {
                "compatible": False,
                "reason": "registry_unavailable",
                "record": None,
            }

    def _assert_collection_compatible(self) -> None:
        verdict = self.collection_compatibility()
        if verdict["compatible"]:
            return
        raise MilvusOperationError(
            "Collection embedding fingerprint is incompatible "
            f"({verdict['reason']}); rebuild into a new collection"
        )

    def _ensure_collection_loaded(self) -> None:
        """Ensure collection exists and is loaded into memory."""
        if not self._collection_loaded:
            try:
                # Check if collection exists
                collections = self.client.list_collections()
                if self.config.collection_name not in collections:
                    log.warning(
                        f"Collection '{self.config.collection_name}' not found, creating..."
                    )
                    self.create_collection(drop_if_exists=False)

                self.client.load_collection(self.config.collection_name)
                self._collection_loaded = True
                log.debug(f"Collection '{self.config.collection_name}' loaded successfully")
            except Exception as e:
                log.warning(f"Collection load failed, reconnecting: {e}")
                # Reset stale connection and retry once
                self._reset_connection()
                collections = self.client.list_collections()
                if self.config.collection_name not in collections:
                    self.create_collection(drop_if_exists=False)
                self.client.load_collection(self.config.collection_name)
                self._collection_loaded = True

    def _reset_connection(self) -> None:
        """Reset Milvus client connection to recover from stale gRPC channels."""
        try:
            if self._client is not None:
                self._client.close()
        except Exception:
            pass
        self._client = None
        self._collection_loaded = False
        # Force new connection on next access
        _ = self.client
        log.debug("Milvus connection reset")

    @retry_on_failure()
    def add_documents(
        self, documents: list[Document], batch_size: int | None = None, show_progress: bool = True
    ) -> dict[str, Any]:
        """
        Add documents with memory-efficient batching.

        Uses small batches and explicit cleanup to minimize memory usage.
        """
        if not documents:
            return {"inserted": 0, "failed": 0, "total": 0}

        batch_size = batch_size or self.config.batch_size
        total = len(documents)
        inserted = 0
        failed = 0

        log.info(f"Adding {total} documents (batch_size={batch_size})")

        self._ensure_collection_loaded()
        self._assert_collection_compatible()

        # Pre-load embedding model only after the compatibility gate. This
        # avoids spending model memory for a write that must be rejected.
        _ = self.embedding_function

        # Process in small batches
        for i in range(0, total, batch_size):
            batch = documents[i : i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total + batch_size - 1) // batch_size

            try:
                # Generate embeddings for this batch. When the embedding function
                # is BGEM3Embeddings and sparse is enabled, produce dense+sparse
                # in one forward (encode_hybrid_batch); otherwise dense-only.
                # Late chunking (§3.5): when a chunk carries a pre-computed
                # _late_chunk_dense vector (from markdown_parser), use it instead
                # of re-embedding — it carries global section context. Sparse is
                # still computed per-chunk (F-05: lexical BoW needs per-doc TF).
                if self.config.contextual_index:
                    from core.retrieval.contextual_text import contextualize_document

                    indexed_batch = [contextualize_document(doc) for doc in batch]
                else:
                    indexed_batch = batch
                texts = [
                    doc.metadata.get("index_text", doc.page_content)
                    if isinstance(doc.metadata.get("index_text", doc.page_content), str)
                    else doc.page_content
                    for doc in indexed_batch
                ]
                sparse_vecs: list[dict[int, float]] | None = None
                emb_fn = self.embedding_function
                late_dense = [doc.metadata.get("_late_chunk_dense") for doc in indexed_batch]
                has_late = (not self.config.contextual_index) and any(
                    v is not None for v in late_dense
                )

                if self.config.enable_sparse and hasattr(emb_fn, "encode_hybrid_batch"):
                    hybrid = emb_fn.encode_hybrid_batch(texts)
                    sparse_vecs = [sparse for _dense, sparse in hybrid]
                    if has_late:
                        # Dense from late chunking; sparse from per-chunk encode.
                        embeddings = [
                            late_dense[idx] if late_dense[idx] is not None else hybrid[idx][0]
                            for idx in range(len(batch))
                        ]
                    else:
                        embeddings = [dense for dense, _sparse in hybrid]
                else:
                    if has_late:
                        embeddings = [
                            late_dense[idx]
                            if late_dense[idx] is not None
                            else emb_fn.embed_query(texts[idx])
                            for idx in range(len(batch))
                        ]
                    else:
                        embeddings = emb_fn.embed_documents(texts)

                # Prepare data for insertion
                data = []
                for idx, (doc, emb) in enumerate(zip(indexed_batch, embeddings)):
                    row = {
                        "text": str(doc.metadata.get("display_text", doc.page_content))[
                            : self.config.max_text_length
                        ],
                        "dense": emb,
                        "source": doc.metadata.get("source", "")[: self.config.max_metadata_length],
                        "title": doc.metadata.get("title", "")[: self.config.max_metadata_length],
                    }
                    # F-02: write sparse vector when the collection has the field.
                    if sparse_vecs is not None:
                        row["sparse"] = sparse_vecs[idx]
                    # Add additional metadata as dynamic fields (skip the internal
                    # _late_chunk_dense key — it's not metadata, just an embedding carrier).
                    for k, v in doc.metadata.items():
                        if k == "_late_chunk_dense":
                            continue
                        if k not in row and isinstance(v, str | int | float | bool):
                            row[k] = v
                    data.append(row)

                # Insert into Milvus
                self.client.insert(collection_name=self.config.collection_name, data=data)
                inserted += len(batch)

                if show_progress:
                    log.info(f"Batch {batch_num}/{total_batches}: {inserted}/{total} docs")

                # Clean up to free memory
                del embeddings
                del data

                # Periodic garbage collection
                if batch_num % 5 == 0:
                    gc.collect()

            except Exception as e:
                failed += len(batch)
                log.error(f"Batch {batch_num} failed: {e}")
                continue

        result = {
            "inserted": inserted,
            "failed": failed,
            "total": total,
            "success_rate": inserted / total if total > 0 else 0,
        }

        log.info(f"Insertion complete: inserted={inserted}, failed={failed}")
        return result

    @retry_on_failure()
    def search(
        self,
        query: str,
        top_k: int = 10,
        filter_expr: str | None = None,
    ) -> list[SearchResult]:
        """
        Search for similar documents.

        Memory-efficient search with explicit cleanup.
        """
        log.debug(f"Searching: query_length={len(query)}, top_k={top_k}")
        self._ensure_collection_loaded()
        self._assert_collection_compatible()
        query_embedding = self.embedding_function.embed_query(query)
        return self.search_by_vector(query_embedding, top_k=top_k, filter_expr=filter_expr)

    @retry_on_failure()
    def search_by_vector(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filter_expr: str | None = None,
    ) -> list[SearchResult]:
        """Dense search using a request-local precomputed query vector."""
        try:
            self._ensure_collection_loaded()
            self._assert_collection_compatible()
            search_params = {"metric_type": "IP"}
            if self.config.search_params:
                search_params.update(self.config.search_params)
            output_fields = ["text", "source", "title", *self.config.extra_output_fields]
            try:
                results = self.client.search(
                    collection_name=self.config.collection_name,
                    data=[query_embedding],
                    anns_field="dense",
                    search_params=search_params,
                    limit=top_k,
                    output_fields=output_fields,
                    filter=filter_expr,
                )
            except Exception as field_err:
                log.debug(
                    f"search with extra output_fields failed ({field_err}); retrying with base fields"
                )
                results = self.client.search(
                    collection_name=self.config.collection_name,
                    data=[query_embedding],
                    anns_field="dense",
                    search_params=search_params,
                    limit=top_k,
                    output_fields=["text", "source", "title"],
                    filter=filter_expr,
                )
            search_results = self._convert_search_results(results)
            log.debug(f"Found {len(search_results)} results")
            return search_results
        except Exception as e:
            log.error(f"Vector search failed: {e}")
            raise MilvusOperationError(f"Vector search failed: {e}") from e

    def _convert_search_results(self, results: Any) -> list[SearchResult]:
        search_results = []
        if results and len(results) > 0:
            ordered_hits = sorted(
                results[0],
                key=lambda hit: (
                    -float(hit.get("distance", 0.0)),
                    str((hit.get("entity", {}) or {}).get("chunk_id", "")),
                    str(hit.get("id", "")),
                ),
            )
            for hit in ordered_hits:
                entity = hit.get("entity", {})
                metadata = {
                    "source": entity.get("source", ""),
                    "title": entity.get("title", ""),
                }
                for field_name in self.config.extra_output_fields:
                    if field_name in entity and entity[field_name] not in (None, ""):
                        metadata[field_name] = entity[field_name]
                display_text = entity.get("display_text") or entity.get("text", "")
                search_results.append(
                    SearchResult(
                        id=hit.get("id", 0),
                        text=display_text,
                        score=hit.get("distance", 0.0),
                        metadata=metadata,
                    )
                )
        return search_results

    def sparse_search(
        self,
        query_sparse: dict[int, float],
        top_k: int = 10,
        filter_expr: str | None = None,
    ) -> list[SearchResult]:
        """Sparse vector search on the 'sparse' field (BGE-M3 lexical_weights).

        F-02: replaces the self-implemented BM25 leg with Milvus native sparse
        retrieval. F-01: filter goes through search(filter=), a first-class param
        on MilvusClient.search — NOT hybrid_search's top-level filter which
        pymilvus 2.5.18 silently drops (Prepare.hybrid_search_request_with_ranker
        never reads it).
        """
        log.debug(f"Sparse searching (top_k={top_k})")
        try:
            self._ensure_collection_loaded()
            self._assert_collection_compatible()

            output_fields = ["text", "source", "title"] + [
                f for f in self.config.extra_output_fields
            ]
            search_params = {"metric_type": "IP"}

            try:
                results = self.client.search(
                    collection_name=self.config.collection_name,
                    data=[query_sparse],
                    anns_field="sparse",
                    search_params=search_params,
                    limit=top_k,
                    output_fields=output_fields,
                    filter=filter_expr,  # F-01: first-class param on search()
                )
            except Exception as field_err:
                # Legacy collection without extra dynamic fields — retry with base.
                log.debug(f"sparse search with extra fields failed ({field_err}); retry base")
                results = self.client.search(
                    collection_name=self.config.collection_name,
                    data=[query_sparse],
                    anns_field="sparse",
                    search_params=search_params,
                    limit=top_k,
                    output_fields=["text", "source", "title"],
                    filter=filter_expr,
                )

            search_results = self._convert_search_results(results)
            log.debug(f"Sparse search found {len(search_results)} results")
            return search_results
        except Exception as e:
            log.error(f"Sparse search failed: {e}")
            raise MilvusOperationError(f"Sparse search failed: {e}") from e

    def query(
        self, filter_expr: str, output_fields: list[str] | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Query documents by filter expression."""
        output_fields = output_fields or ["text", "source", "title"]

        results = self.client.query(
            collection_name=self.config.collection_name,
            filter=filter_expr,
            output_fields=output_fields,
            limit=limit,
        )

        return results

    def delete_by_filter(self, filter_expr: str) -> dict[str, Any]:
        """Delete documents matching filter."""
        log.info(f"Deleting: {filter_expr}")
        result = self.client.delete(collection_name=self.config.collection_name, filter=filter_expr)
        return {"deleted_count": result}

    def get_collection_stats(self) -> dict[str, Any]:
        """Get collection statistics."""
        try:
            stats = self.client.get_collection_stats(self.config.collection_name)
            return {
                "collection_name": self.config.collection_name,
                "row_count": stats.get("row_count", 0),
            }
        except Exception as e:
            return {"error": str(e)}

    def health_check(self) -> dict[str, Any]:
        """Check connection health. Works with both Milvus server and Milvus Lite."""
        result = {
            "connected": False,
            "server_info": None,
            "error": None,
            "embedding_compatible": None,
            "embedding_compatibility": None,
        }

        try:
            # Milvus Lite (local .db) doesn't support get_server_version,
            # so we use list_collections as the connectivity check instead.
            collections = self.client.list_collections()
            result["collections"] = collections
            result["connected"] = True
            compatibility = self.collection_compatibility()
            result["embedding_compatible"] = compatibility["compatible"]
            result["embedding_compatibility"] = {
                "compatible": compatibility["compatible"],
                "reason": compatibility["reason"],
            }

            # Detect Milvus Lite from URI to avoid calling unsupported API
            uri = self.config.uri
            is_lite = uri and (uri.endswith(".db") or uri.startswith("./") or ".db" in uri)
            if is_lite:
                result["server_info"] = {"version": "lite", "mode": "local"}
            else:
                # Remote server — safe to call get_server_version
                try:
                    version = self.client.get_server_version()
                    result["server_info"] = {"version": version, "mode": "server"}
                except Exception:
                    result["server_info"] = {"version": "unknown", "mode": "unknown"}

        except Exception as e:
            result["error"] = str(e)

        return result


def get_milvus_manager(collection_name: str = COLLECTION_NAME) -> MilvusManager:
    """Create a MilvusManager instance."""
    config = MilvusConfig(collection_name=collection_name)
    return MilvusManager(config)


def cleanup_milvus_resources():
    """
    Force cleanup of all Milvus-related resources.

    Call this when experiencing memory issues.
    """
    gc.collect()
    log.info("Milvus resources cleaned up")


# =============================================================================
# Test / Demo
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Milvus Database Manager Test")
    parser.add_argument(
        "--collection",
        type=str,
        default=COLLECTION_NAME,
        help="Collection name",
    )
    parser.add_argument(
        "--action",
        type=str,
        choices=["health", "stats", "create", "search", "insert-test"],
        default="health",
        help="Action to perform",
    )
    parser.add_argument(
        "--query",
        type=str,
        default="测试查询",
        help="Search query (for search action)",
    )
    parser.add_argument(
        "--drop",
        action="store_true",
        help="Drop existing collection when creating",
    )

    args = parser.parse_args()

    # Create manager with context manager for automatic cleanup
    config = MilvusConfig(collection_name=args.collection)

    print(f"\n{'=' * 50}")
    print("Milvus Manager Test")
    print(f"Collection: {args.collection}")
    print(f"Action: {args.action}")
    print(f"{'=' * 50}\n")

    try:
        with MilvusManager(config) as manager:
            if args.action == "health":
                result = manager.health_check()
                print("Health Check Result:")
                print(f"  Connected: {result.get('connected')}")
                print(f"  Server Version: {result.get('server_info', {}).get('version', 'N/A')}")
                print(f"  Collections: {result.get('collections', [])}")
                if result.get("error"):
                    print(f"  Error: {result['error']}")

            elif args.action == "stats":
                result = manager.get_collection_stats()
                print("Collection Stats:")
                print(f"  Collection: {result.get('collection_name')}")
                print(f"  Row Count: {result.get('row_count', 0)}")
                if result.get("error"):
                    print(f"  Error: {result['error']}")

            elif args.action == "create":
                result = manager.create_collection(drop_if_exists=args.drop)
                print(f"Collection created: {result}")

            elif args.action == "search":
                print(f"Searching for: '{args.query}'")
                results = manager.search(args.query, top_k=5)
                print(f"\nFound {len(results)} results:")
                for i, r in enumerate(results, 1):
                    print(f"\n--- Result {i} (score: {r.score:.4f}) ---")
                    print(f"  Source: {r.metadata.get('source', 'N/A')}")
                    print(f"  Title: {r.metadata.get('title', 'N/A')}")
                    print(f"  Text: {r.text[:200]}...")

            elif args.action == "insert-test":
                # Insert a test document
                test_docs = [
                    Document(
                        page_content="这是一个测试文档，用于验证Milvus插入功能。",
                        metadata={"source": "test.py", "title": "测试文档"},
                    )
                ]
                result = manager.add_documents(test_docs)
                print(f"Insert result: {result}")

    except Exception as e:
        print(f"Error: {e}")
        raise

    print(f"\n{'=' * 50}")
    print("Test completed successfully")
    print(f"{'=' * 50}\n")
