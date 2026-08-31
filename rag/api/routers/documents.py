"""
Documents Router for Enterprise RAG Platform

Handles document upload, management, and indexing.
Uses SQLite-backed registry for persistent document tracking.
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from langchain_core.documents import Document
from pydantic import BaseModel

from documents.document_registry import DocumentStatus, get_document_registry
from utils.env_utils import GRAPH_RAG_ENABLED
from utils.log_utils import log

router = APIRouter()

# Module-level upload temp directory (B6). Exposed so tests/conftest.py's
# tmp_data_dir fixture can redirect it to tmp_path, keeping uploads hermetic
# (previously hardcoded "/tmp" leaked temp files when the background cleanup
# was mocked out). Conforms to AGENTS.md §6/§10 persistence-path contract.
UPLOAD_TMP_DIR = "/tmp"

# Max accepted upload size (bytes). Env-configurable; default 50 MB. Checked
# before reading the body so an oversized upload can't exhaust RAM (B10).
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))


# =============================================================================
# Models
# =============================================================================


class DocumentInfo(BaseModel):
    """Document information model."""

    id: str
    filename: str
    status: DocumentStatus
    chunks: int = 0
    created_at: float
    size_bytes: int = 0
    file_hash: str = ""


class DocumentListResponse(BaseModel):
    """Document list response."""

    documents: list[DocumentInfo]
    total: int


class UploadResponse(BaseModel):
    """Document upload response."""

    id: str
    filename: str
    status: DocumentStatus
    message: str


# =============================================================================
# Helpers
# =============================================================================


def _compute_file_hash(content: bytes) -> str:
    """Compute SHA256 hash of file content."""
    return hashlib.sha256(content).hexdigest()


def _secure_filename(filename: str) -> str:
    """
    Sanitise a user-supplied filename for safe use in a filesystem path.

    Strips directory components and path separators so that a name like
    ``../../etc/x.md`` cannot escape the destination directory. Falls back to
    a generic name when nothing safe remains. The original (sanitised) name
    is still used for display/duplicate-detection.
    """
    import os
    import re

    if not filename:
        return "upload"
    # Take the basename only (handles both / and \ and any leading ../).
    name = os.path.basename(filename.replace("\\", "/"))
    # Drop any remaining path separators / dots-only / control chars.
    name = re.sub(r"[\/\x00-\x1f]", "_", name)
    # Collapse ".." sequences that survived.
    name = name.replace("..", "_")
    name = name.strip(". ") or "upload"
    return name


def _escape_filter_value(value: str) -> str:
    """Escape special characters in Milvus filter expression values."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _split_documents(documents: list[Document]) -> list[Document]:
    """Split documents using semantic chunking with fallback.

    Mirrors MarkdownParser's two-stage strategy:
    1. Small docs (< ~1200 tokens) are kept intact.
    2. Large docs are split by SemanticChunker (embedding-based breakpoints).
    3. On failure, fall back to RecursiveCharacterTextSplitter.
    """
    try:
        from langchain_experimental.text_splitter import SemanticChunker
    except ImportError:
        SemanticChunker = None  # type: ignore

    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError:
        try:
            from langchain.text_splitter import (
                RecursiveCharacterTextSplitter,  # type: ignore[no-redef]
            )
        except ImportError:
            RecursiveCharacterTextSplitter = None  # type: ignore

    # Stage 1: separate small docs (keep intact) from large docs (need splitting)
    small: list[Document] = []
    large: list[Document] = []
    for doc in documents:
        text = doc.page_content or ""
        if not text:
            continue
        # Threshold: ~1200 tokens. Mixed Chinese/English ≈ 3.2 chars/token.
        if len(text) > 3840:
            large.append(doc)
        else:
            small.append(doc)

    # parent_store small-to-big wiring (Stage B): tag each parent doc's chunks
    # with parent_id so expand_to_parents can swap them for full-doc context.
    import hashlib

    from documents.parent_store import get_parent_store, make_parent_id

    parent_store = get_parent_store()

    def _tag_parent(doc: Document) -> str | None:
        source = doc.metadata.get("source") or ""
        if not source:
            return None
        # Stable int section index from the content hash (make_parent_id
        # requires an int). Same doc -> same pid (idempotent INSERT OR REPLACE).
        content_hash = hashlib.sha1(doc.page_content.encode()).hexdigest()[:8]
        section_index = int(content_hash, 16)
        pid = make_parent_id(source, section_index)
        try:
            parent_store.store(pid, content=doc.page_content, source=source, title="")
        except Exception as e:
            log.warning(f"parent_store write failed: {e}")
        return pid

    # small docs are kept intact; tag each with its own parent_id (parent = self)
    result: list[Document] = []
    for doc in small:
        pid = _tag_parent(doc)
        if pid:
            doc.metadata["parent_id"] = pid
        result.append(doc)

    if not large:
        return result

    # Stage 2: semantic chunking for large docs
    semantic_splitter = None
    if SemanticChunker is not None:
        try:
            from models.embedding_models import get_local_embeddings

            embeddings = get_local_embeddings()
            semantic_splitter = SemanticChunker(
                embeddings,
                breakpoint_threshold_type="percentile",
            )
        except Exception as e:
            log.debug(f"SemanticChunker init failed: {e}")

    # Stage 3: recursive fallback splitter (if semantic unavailable/failed)
    recursive_splitter = None
    if RecursiveCharacterTextSplitter is not None:
        recursive_splitter = RecursiveCharacterTextSplitter(
            chunk_size=900,
            chunk_overlap=120,
            separators=[
                "\n\n",
                "\n",
                "。",
                "！",
                "？",
                ".",
                "!",
                "?",
                "；",
                ";",
                "，",
                ",",
                " ",
                "",
            ],
        )

    # Split each large parent doc individually so chunks can be tagged with the
    # parent's parent_id (batched split loses the doc->chunks mapping).
    for doc in large:
        pid = _tag_parent(doc)
        pieces: list[Document] = []
        if semantic_splitter is not None:
            try:
                pieces = semantic_splitter.split_documents([doc])
                log.info(f"Semantic split: 1 doc -> {len(pieces)} chunks")
            except Exception as e:
                log.warning(f"Semantic split failed for doc: {e}")
                pieces = []
        if not pieces and recursive_splitter is not None:
            try:
                pieces = recursive_splitter.split_documents([doc])
                log.info(f"Fallback split: 1 doc -> {len(pieces)} chunks")
            except Exception as e2:
                log.warning(f"Fallback split failed: {e2}")
                pieces = []
        if not pieces:
            pieces = [doc]
        for piece in pieces:
            if pid:
                piece.metadata["parent_id"] = pid
            result.append(piece)

    return result


def _recover_stale_processing(registry, filename: str, file_hash: str) -> None:
    """
    Flip orphaned ``processing`` rows to ``failed`` (B7).

    A background indexing task that dies (process killed, exception before the
    status update) leaves its registry row in ``processing`` forever, which
    then blocks any re-upload of the same content. We treat a ``processing``
    row older than the stale threshold as dead: marking it ``failed`` lets a
    fresh upload proceed. Never raises — recovery is best-effort.
    """
    import time

    # Stale threshold: a healthy index of a single doc completes well under a
    # minute; anything still processing past this is almost certainly orphaned.
    stale_seconds = 120.0
    now = time.time()
    for row in (registry.find_by_filename(filename), registry.find_by_file_hash(file_hash)):
        if not row:
            continue
        if row.get("status") != "processing":
            continue
        created = row.get("created_at")
        if isinstance(created, (int, float)) and (now - float(created)) > stale_seconds:
            try:
                registry.update_status(row["id"], "failed")
                log.warning(
                    f"Recovered stale 'processing' doc {row.get('id')} "
                    f"(age {now - float(created):.0f}s) -> failed"
                )
            except Exception as e:  # noqa: BLE001
                log.debug(f"stale-processing recovery skipped: {e}")


def _check_duplicate(filename: str, file_hash: str) -> str | None:
    """
    Check if a file already exists in the vector database or registry.

    Returns an error message if duplicate found, None otherwise. A registry
    record stuck in ``processing`` for longer than the stale threshold is
    treated as an orphaned background task (B7): it is flipped to ``failed``
    and does NOT block re-upload, so a dead worker never wedges the doc.
    """
    # Check registry first (fast, always available)
    registry = get_document_registry()

    # B7: recover orphaned "processing" rows before they block uploads.
    _recover_stale_processing(registry, filename, file_hash)

    existing_by_name = registry.find_by_filename(filename)
    if existing_by_name:
        return f"文件 '{filename}' 已上传过，请勿重复上传"

    existing_by_hash = registry.find_by_file_hash(file_hash)
    if existing_by_hash:
        return f"相同内容的文件已存在（来源: {existing_by_hash.get('filename', '未知')}），请勿重复上传"

    # Also check Milvus (for data from previous sessions)
    try:
        from documents.milvus_db import get_milvus_manager

        manager = get_milvus_manager()

        safe_name = _escape_filter_value(filename)
        safe_hash = _escape_filter_value(file_hash)

        results = manager.query(
            filter_expr=f'source == "{safe_name}"',
            output_fields=["source"],
            limit=1,
        )
        if results:
            return f"文件 '{filename}' 已上传过，请勿重复上传"

        results = manager.query(
            filter_expr=f'file_hash == "{safe_hash}"',
            output_fields=["source"],
            limit=1,
        )
        if results:
            existing_name = results[0].get("source", "未知")
            return f"相同内容的文件已存在（来源: {existing_name}），请勿重复上传"

    except Exception as e:
        log.debug(f"Milvus duplicate check skipped: {e}")

    return None


# =============================================================================
# Endpoints
# =============================================================================


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """
    Upload and process a document.

    Supported formats: .md, .txt, .pdf, .docx, .pptx, .html, .htm
    (DOCX/PPTX/HTML require their optional libs: python-docx, python-pptx,
    beautifulsoup4.)
    """
    allowed_extensions = {".md", ".txt", ".pdf", ".docx", ".pptx", ".html", ".htm"}
    filename = file.filename or "unknown"
    ext = os.path.splitext(filename)[1].lower()

    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400, detail=f"Unsupported file type: {ext}. Allowed: {allowed_extensions}"
        )

    # Reject oversized uploads BEFORE reading the body into memory (B10).
    # file.size comes from Content-Length when available; the post-read len()
    # check below is a backstop for requests that omit/spoof Content-Length.
    declared_size = getattr(file, "size", None)
    if declared_size is not None and declared_size > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "文件过大")

    doc_id = str(uuid.uuid4())[:8]
    log.info(f"Uploading document: {filename} (id={doc_id})")

    try:
        content = await file.read()
        size = len(content)
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "文件过大")
        file_hash = _compute_file_hash(content)

        # Check for duplicates
        duplicate_msg = _check_duplicate(filename, file_hash)
        if duplicate_msg:
            log.warning(f"Duplicate upload rejected: {filename} (hash={file_hash[:16]}...)")
            raise HTTPException(status_code=409, detail=duplicate_msg)

        # Save temporarily — sanitise the filename to prevent path traversal
        # (a user-supplied name like ../../etc/x must not escape /tmp). The
        # sanitised name is also used as the document source/registry name so
        # path fragments don't leak into chunk metadata or the listing.
        safe_name = _secure_filename(filename)
        temp_path = os.path.join(UPLOAD_TMP_DIR, f"{doc_id}_{safe_name}")
        with open(temp_path, "wb") as f:
            f.write(content)

        # Register document (persistent)
        registry = get_document_registry()
        registry.put(
            doc_id=doc_id,
            filename=safe_name,
            status="processing",
            chunks=0,
            created_at=time.time(),
            size_bytes=size,
            file_hash=file_hash,
        )

        # Process in background
        background_tasks.add_task(
            _process_document,
            doc_id,
            temp_path,
            safe_name,
            file_hash,
        )

        return UploadResponse(
            id=doc_id,
            filename=safe_name,
            status="processing",
            message="Document uploaded and processing started",
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to upload document: {e}")
        raise HTTPException(status_code=500, detail="服务暂时不可用，请稍后重试")


def _extract_graph_if_enabled(documents: list[Document], source: str, file_hash: str) -> None:
    """Run GraphRAG entity/relation extraction at ingestion time.

    Gated by ``GRAPH_RAG_ENABLED`` (REQ-GR-008, default off → no-op). On any
    failure the main ingestion path is unaffected: the doc is already indexed
    in Milvus + BM25, so graph extraction is strictly additive (REQ-GR-003).
    The shared retrieval-cache version is bumped so new graph hits are visible.
    """
    if not GRAPH_RAG_ENABLED:
        return
    try:
        from documents.graph_extractor import get_graph_extractor
        from documents.graph_store import get_graph_store
        from models.embedding_models import get_embeddings
        from utils.env_utils import resolve_embedding_settings

        extractor = get_graph_extractor()
        entities, relations = extractor.extract(documents, source=source, file_hash=file_hash)
        if not entities and not relations:
            return
        # Embed entities with the shared BGE singleton so graph cosine matches
        # the dense leg's vector space.
        emb = get_embeddings()
        embedding_settings = resolve_embedding_settings()
        texts = [e.name for e in entities]
        vectors = emb.embed_documents(texts) if texts else []
        for e, v in zip(entities, vectors, strict=False):
            e.embedding = v
        # Use the ACTUAL returned dimension, not the env-configured one: if the
        # embedding model was swapped (e.g. BGE-small → BGE-large), the env value
        # is stale but the vectors reflect the live model. Recording the real dim
        # keeps the graph retriever's fingerprint check accurate (F-09).
        actual_dim = len(vectors[0]) if vectors else embedding_settings.dimension
        store = get_graph_store()
        store.upsert(
            entities,
            relations,
            source=source,
            file_hash=file_hash,
            embedding_model=embedding_settings.model_source,
            embedding_dim=actual_dim,
        )
        # Invalidate the graph retriever's cached matrix + the retrieval cache.
        try:
            from core.retrieval.cache import bump_retrieval_cache_version
            from core.retrieval.graph_retriever import get_graph_retriever

            get_graph_retriever().add_documents(documents)
            bump_retrieval_cache_version()
        except Exception as cache_err:  # noqa: BLE001
            log.warning(f"graph cache bump skipped: {cache_err}")
        log.info(f"GraphRAG: {source} → {len(entities)} entities, {len(relations)} relations")
    except Exception as e:  # noqa: BLE001 — never block ingestion
        log.warning(f"GraphRAG extraction skipped for {source}: {e}")


def _remove_graph_if_enabled(source: str) -> None:
    """Delete a source's graph data + invalidate caches (mirror of BM25 remove)."""
    if not GRAPH_RAG_ENABLED:
        return
    try:
        from core.retrieval.cache import bump_retrieval_cache_version
        from core.retrieval.graph_retriever import get_graph_retriever
        from documents.graph_store import get_graph_store

        removed = get_graph_store().remove_by_source(source)
        if removed:
            get_graph_retriever().remove_by_source(source)
            # Self-contained cache bump: delete_document calls BM25's bump BEFORE
            # this function, so a retrieval that raced between the two would
            # rebuild the cache with the now-stale graph hits. Bumping again here
            # (O(1) version increment) guarantees post-deletion queries never
            # serve graph results for the removed source.
            bump_retrieval_cache_version()
            log.info(f"GraphRAG: removed {removed} entities for source={source}")
    except Exception as e:  # noqa: BLE001
        log.warning(f"GraphRAG cleanup failed for {source}: {e}")


def _build_raptor_if_enabled(documents: list[Document], source: str, file_hash: str) -> None:
    """Build an additive ready RAPTOR generation; failures never block ingestion."""
    from core.retrieval.raptor_store import raptor_enabled

    if not raptor_enabled():
        return
    try:
        from core.retrieval.cache import bump_retrieval_cache_version, embedding_fingerprint
        from core.retrieval.raptor_store import get_raptor_store
        from models.embedding_models import get_embeddings

        embedding = None
        embedding_identity = "lexical"
        try:
            embedding = get_embeddings()
            embedding_identity = embedding_fingerprint(embedding)
        except Exception as embedding_exc:
            log.warning(
                f"RAPTOR embeddings unavailable for {source}; lexical summaries retained: "
                f"{type(embedding_exc).__name__}"
            )
        get_raptor_store().build_source(
            source,
            documents,
            content_hash=file_hash,
            embedding_fingerprint=embedding_identity,
            embedding=embedding,
        )
        bump_retrieval_cache_version()
    except Exception as exc:  # optional ingestion path
        log.warning(f"RAPTOR build skipped for {source}: {exc}")


def _remove_raptor_if_present(source: str) -> None:
    """Remove RAPTOR visibility for a deleted source without forcing store creation."""
    try:
        from core.retrieval.raptor_store import RAPTOR_DB_PATH, get_raptor_store, raptor_enabled

        if not raptor_enabled() and not os.path.isfile(RAPTOR_DB_PATH):
            return
        if get_raptor_store().remove_by_source(source):
            from core.retrieval.cache import bump_retrieval_cache_version

            bump_retrieval_cache_version()
    except Exception as exc:
        log.warning(f"RAPTOR cleanup failed for {source}: {exc}")


def _build_visual_if_enabled(
    documents: list[Document],
    file_path: str,
    source: str,
    file_hash: str,
) -> None:
    """Render and index every PDF page as an optional atomic generation."""
    from core.retrieval.visual_retriever import visual_enabled

    if not visual_enabled():
        return
    try:
        from core.retrieval.cache import bump_retrieval_cache_version
        from core.retrieval.visual_retriever import get_visual_retriever

        page_text: dict[int, list[str]] = {}
        for document in documents:
            page = (document.metadata or {}).get("page")
            if isinstance(page, int) and document.page_content.strip():
                page_text.setdefault(page, []).append(document.page_content.strip())
        get_visual_retriever().index_pdf(
            source,
            file_path,
            file_hash,
            ocr_text_by_page={page: "\n".join(texts) for page, texts in page_text.items()},
        )
        bump_retrieval_cache_version()
    except Exception as exc:
        log.warning(f"visual page indexing skipped for {source}: {exc}")


def _remove_visual_if_present(source: str) -> None:
    try:
        from core.retrieval.visual_retriever import (
            VISUAL_INDEX_PATH,
            get_visual_retriever,
            visual_enabled,
        )

        if not visual_enabled() and not os.path.isfile(VISUAL_INDEX_PATH):
            return
        if get_visual_retriever().remove_by_source(source):
            from core.retrieval.cache import bump_retrieval_cache_version

            bump_retrieval_cache_version()
    except Exception as exc:
        log.warning(f"visual page cleanup failed for {source}: {exc}")


def _process_document(doc_id: str, file_path: str, filename: str, file_hash: str):
    """Process and index a document (background task)."""
    registry = get_document_registry()
    try:
        log.info(f"Processing document: {doc_id}")

        ext = os.path.splitext(filename)[1].lower()

        if ext == ".md":
            from documents.markdown_parser import MarkdownParser

            parser = MarkdownParser()
            documents = parser.parse_markdown_to_documents(file_path)
        elif ext == ".pdf":
            from documents.pdf_parser import parse_pdf_to_documents

            documents = parse_pdf_to_documents(file_path, filename)
            documents = _split_documents(documents)
        elif ext in (".docx", ".pptx", ".html", ".htm"):
            # Multi-format parsers (optional libs). Falls back to text on error.
            try:
                from documents.format_parsers import parse_by_extension

                documents = parse_by_extension(file_path, source=filename)
                documents = _split_documents(documents)
            except RuntimeError as fmt_err:
                log.warning(f"Multi-format parse failed ({ext}), skipping: {fmt_err}")
                raise
        else:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
            # Split by paragraph first so the splitter can respect natural boundaries.
            documents = []
            for para in content.split("\n\n"):
                para = para.strip()
                if para:
                    documents.append(Document(page_content=para, metadata={"source": filename}))
            documents = _split_documents(documents)

        # Normalize the source after parsing. MarkdownParser sees the temporary
        # upload path (which is prefixed with doc_id); exposing that value would
        # break source filters and later deletion by the registry filename.
        for doc in documents:
            doc.metadata["source"] = filename
            doc.metadata["file_hash"] = file_hash

        # Contextual indexing is opt-in and must target an isolated/new
        # collection. Prepare once so Milvus dense/native-sparse and BM25 use
        # the same index_text while page_content remains original display text.
        from core.retrieval.contextual_text import contextualize_documents_if_enabled

        documents = contextualize_documents_if_enabled(documents)

        # Index into Milvus
        from documents.milvus_db import get_milvus_manager

        manager = get_milvus_manager()
        result = manager.add_documents(documents)

        # Sync BM25 index
        try:
            from core.retrieval.bm25_retriever import get_bm25_retriever
            from core.retrieval.cache import bump_retrieval_cache_version

            bm25 = get_bm25_retriever()
            bm25.add_documents(documents)
            # Invalidate cached retrieval results so the new docs are visible to
            # the read path immediately (cache key is version-scoped).
            bump_retrieval_cache_version()
            log.info(f"BM25 index updated: +{len(documents)} docs")
        except Exception as bm25_err:
            log.warning(f"BM25 sync failed (non-critical): {bm25_err}")

        # GraphRAG extraction (docs/specs/graphrag). Opt-in via GRAPH_RAG_ENABLED;
        # failure never blocks main ingestion — the doc is already in Milvus/BM25.
        _extract_graph_if_enabled(documents, filename, file_hash)
        _build_raptor_if_enabled(documents, filename, file_hash)
        if ext == ".pdf":
            _build_visual_if_enabled(documents, file_path, filename, file_hash)

        # Update registry
        registry.update_status(doc_id, "indexed", result.get("inserted", 0))
        log.info(f"Document processed: {doc_id}, chunks={len(documents)}")

    except Exception as e:
        log.error(f"Failed to process document {doc_id}: {e}")
        registry.update_status(doc_id, "failed")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    skip: int = 0,
    limit: int = Query(20, ge=1, le=200),
):
    """List all documents."""
    registry = get_document_registry()
    docs = registry.list_all(skip=skip, limit=limit)
    return DocumentListResponse(
        documents=[DocumentInfo(**d) for d in docs],
        total=registry.count(),
    )


@router.get("/{doc_id}", response_model=DocumentInfo)
async def get_document(doc_id: str):
    """Get document details."""
    registry = get_document_registry()
    doc = registry.get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentInfo(**doc)


@router.delete("/{doc_id}")
async def delete_document(doc_id: str):
    """Delete a document from registry, Milvus, and BM25."""
    registry = get_document_registry()
    doc = registry.get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # Remove from Milvus
    try:
        from documents.milvus_db import get_milvus_manager

        manager = get_milvus_manager()
        file_hash = doc.get("file_hash", "")
        if file_hash:
            safe_hash = _escape_filter_value(file_hash)
            manager.delete_by_filter(filter_expr=f'file_hash == "{safe_hash}"')
            log.info(f"Deleted document from Milvus: {doc_id}")
        else:
            safe_name = _escape_filter_value(doc["filename"])
            manager.delete_by_filter(filter_expr=f'source == "{safe_name}"')
            log.info(f"Deleted document from Milvus by filename: {doc['filename']}")
    except Exception as e:
        log.error(f"Failed to delete from Milvus: {e}")

    # Remove from BM25 index (incremental)
    try:
        from core.retrieval.bm25_retriever import get_bm25_retriever
        from core.retrieval.cache import bump_retrieval_cache_version

        get_bm25_retriever().remove_by_source(doc["filename"])
        # Invalidate cached retrieval results computed against the old index.
        bump_retrieval_cache_version()
        log.info(f"BM25 index updated: removed source={doc['filename']}")
    except Exception as e:
        log.warning(f"BM25 cleanup failed: {e}")

    # GraphRAG cleanup (docs/specs/graphrag). Mirror the BM25 removal so a
    # deleted doc's entities/relations do not linger in the graph leg. The
    # cache was already bumped above; this only touches the graph store.
    _remove_graph_if_enabled(doc["filename"])
    _remove_raptor_if_present(doc["filename"])
    _remove_visual_if_present(doc["filename"])

    registry.delete(doc_id)
    return {"status": "success", "message": f"Document {doc_id} deleted"}


@router.post("/reindex")
async def reindex_all_documents(background_tasks: BackgroundTasks):
    """Reindex all markdown files from the md/ directory."""
    background_tasks.add_task(_reindex_all)
    return {
        "status": "success",
        "message": "Reindexing started in background",
    }


def _reindex_all():
    """Reindex all markdown files from md/ directory."""
    import glob

    from core.retrieval.bm25_retriever import get_bm25_retriever
    from documents.markdown_parser import MarkdownParser
    from documents.milvus_db import get_milvus_manager

    md_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "md"
    )
    md_files = glob.glob(os.path.join(md_dir, "*.md"))

    if not md_files:
        log.warning(f"No markdown files found in {md_dir}")
        return

    log.info(f"Reindexing {len(md_files)} markdown files from {md_dir}")

    registry = get_document_registry()
    parser = MarkdownParser()
    manager = get_milvus_manager()

    total_inserted = 0
    for md_path in md_files:
        filename = os.path.basename(md_path)
        try:
            # Parse document
            documents = parser.parse_markdown_to_documents(md_path)
            if not documents:
                log.warning(f"No documents parsed from {filename}")
                continue

            # Add file_hash metadata
            with open(md_path, "rb") as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
            for doc in documents:
                doc.metadata["file_hash"] = file_hash

            from core.retrieval.contextual_text import contextualize_documents_if_enabled

            documents = contextualize_documents_if_enabled(documents)

            # Insert into Milvus
            result = manager.add_documents(documents)
            inserted = result.get("inserted", 0)
            total_inserted += inserted
            _build_raptor_if_enabled(documents, filename, file_hash)

            # Update registry
            doc_id = str(uuid.uuid4())[:8]
            registry.put(
                doc_id=doc_id,
                filename=filename,
                status="indexed",
                chunks=inserted,
                created_at=time.time(),
                size_bytes=os.path.getsize(md_path),
                file_hash=file_hash,
            )

            log.info(f"Reindexed: {filename}, {inserted} chunks")

        except Exception as e:
            log.error(f"Failed to reindex {filename}: {e}")

    # Rebuild BM25 index from Milvus
    try:
        from core.retrieval.cache import bump_retrieval_cache_version

        bm25 = get_bm25_retriever()
        bm25.clear()
        results = manager.query(
            filter_expr="id > 0", output_fields=["text", "source", "title"], limit=10000
        )
        if results:
            from langchain_core.documents import Document as LCDoc

            docs = [
                LCDoc(
                    page_content=r.get("text", ""),
                    metadata={"source": r.get("source", ""), "title": r.get("title", "")},
                )
                for r in results
                if r.get("text")
            ]
            if docs:
                bm25.add_documents(docs)
                log.info(f"BM25 index rebuilt: {len(docs)} docs")
        # Full rebuild invalidates all cached retrieval results.
        bump_retrieval_cache_version()
    except Exception as e:
        log.warning(f"BM25 rebuild failed: {e}")

    log.info(f"Reindex complete: {total_inserted} chunks from {len(md_files)} files")
