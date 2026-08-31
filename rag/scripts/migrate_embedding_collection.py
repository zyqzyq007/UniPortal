#!/usr/bin/env python3
"""Rebuild parent-store content into a new Milvus collection.

The command never mutates or drops the active collection. It re-splits the
persisted parent sections, embeds them with the effective provider/model, and
registers the target collection fingerprint before optional sample queries.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def rebuild_collection(
    target: str,
    sample_queries: list[str] | None = None,
    *,
    skip_recall_check: bool = False,
    contextual_index: bool = False,
) -> dict:
    from langchain_core.documents import Document

    from api.routers.documents import _split_documents
    from documents.document_registry import get_document_registry
    from documents.milvus_db import MilvusConfig, MilvusManager
    from documents.parent_store import get_parent_store
    from utils.env_utils import COLLECTION_NAME, resolve_embedding_settings, resolve_milvus_uri

    target = target.strip()
    if not target:
        raise ValueError("target collection must not be empty")
    if target == COLLECTION_NAME:
        raise ValueError("target collection must differ from active COLLECTION_NAME")

    queries = [query.strip() for query in (sample_queries or []) if query.strip()]
    if not queries and not skip_recall_check:
        raise ValueError(
            "at least one sample query is required; use --skip-recall-check only "
            "after explicit risk review"
        )

    settings = resolve_embedding_settings()
    parents = get_parent_store().list_all()
    if not parents:
        raise ValueError("parent_store is empty; no trusted source content is available")

    source_documents = [
        Document(
            page_content=row["content"],
            metadata={
                "source": row.get("source") or "",
                "title": row.get("title") or "",
                "parent_id": row["parent_id"],
            },
        )
        for row in parents
        if row.get("content")
    ]
    if not source_documents:
        raise ValueError("parent_store has no non-empty trusted source content")

    registry = get_document_registry()
    registry_count = registry.count()
    indexed_rows = registry.list_all(skip=0, limit=max(1, registry_count))
    indexed_sources = {
        str(row.get("filename") or "")
        for row in indexed_rows
        if row.get("status") == "indexed" and row.get("filename")
    }
    parent_sources = {
        str(document.metadata.get("source") or "")
        for document in source_documents
        if document.metadata.get("source")
    }
    missing_sources = sorted(indexed_sources - parent_sources)
    if missing_sources:
        raise RuntimeError("missing indexed sources in parent_store: " + ", ".join(missing_sources))

    chunks = _split_documents(source_documents)
    manager = MilvusManager(
        MilvusConfig(
            uri=resolve_milvus_uri(),
            collection_name=target,
            dense_dim=settings.dimension,
            enable_sparse=settings.sparse_enabled,
            contextual_index=contextual_index,
        )
    )
    target_created = False
    migration_verified = False
    try:
        if target in manager.client.list_collections():
            raise ValueError("target collection already exists; choose a new name")
        manager.create_collection(drop_if_exists=False)
        target_created = True
        write_result = manager.add_documents(chunks, show_progress=True)
        if write_result.get("inserted") != len(chunks) or write_result.get("failed"):
            raise RuntimeError(f"incomplete target write: {write_result}")

        compatibility = manager.collection_compatibility()
        if not compatibility["compatible"]:
            raise RuntimeError(
                f"target compatibility verification failed: {compatibility['reason']}"
            )

        samples = {}
        for query in queries:
            samples[query] = len(manager.search(query, top_k=3))
            if samples[query] == 0:
                raise RuntimeError(f"sample recall verification failed: zero hits for {query!r}")
        migration_verified = True
        return {
            "source_parents": len(source_documents),
            "target_chunks": len(chunks),
            "inserted": write_result["inserted"],
            "target_collection": target,
            "embedding_provider": settings.provider,
            "embedding_model": settings.model,
            "embedding_model_source": settings.model_source,
            "embedding_dimension": settings.dimension,
            "sparse_enabled": settings.sparse_enabled,
            "sample_hits": samples,
            "recall_check_skipped": not queries,
            "indexed_sources": len(indexed_sources),
            "contextual_index": contextual_index,
        }
    finally:
        if target_created and not migration_verified:
            try:
                manager.client.drop_collection(target)
            except Exception:
                pass
        manager.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild persisted parent content into a new embedding collection."
    )
    parser.add_argument("--target-collection", required=True)
    parser.add_argument(
        "--sample-query",
        action="append",
        default=[],
        help="Required verification query; repeat for multiple samples.",
    )
    parser.add_argument(
        "--skip-recall-check",
        action="store_true",
        help="Explicitly accept migration risk and allow no sample query.",
    )
    parser.add_argument(
        "--contextual-index",
        action="store_true",
        help="Build bounded display_text/index_text fields in the new collection.",
    )
    args = parser.parse_args()
    try:
        print(
            rebuild_collection(
                args.target_collection,
                args.sample_query,
                skip_recall_check=args.skip_recall_check,
                contextual_index=args.contextual_index,
            )
        )
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1
    print(
        "Migration verified. Switch COLLECTION_NAME explicitly after review; "
        "keep the old collection and its embedding settings for rollback."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
