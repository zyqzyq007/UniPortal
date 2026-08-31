#!/usr/bin/env python3
"""Re-embed all GraphRAG entities with the current embedding model (F-03 migration).

When the embedding model changes (e.g. BGE-small 512d → BGE-M3 1024d), the
persisted entity BLOBs in graph_store.db are stale — graph_retriever's
``_build_matrix_locked`` detects the dim mismatch and degrades to empty
(``degraded=True``, graph leg returns []). This script re-embeds every entity
name with the current model, updates the BLOBs, and refreshes graph_meta.

MUST be run after switching EMBEDDING_MODEL and before relying on GraphRAG.
Run: uv run --frozen python scripts/rebuild_graph_embeddings.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.log_utils import log


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-embed GraphRAG entities (F-03 migration).")
    parser.add_argument("--batch-size", type=int, default=32, help="Entities per embedding batch.")
    parser.add_argument("--dry-run", action="store_true", help="Show counts without writing.")
    args = parser.parse_args()

    from documents.graph_store import GraphStore, get_graph_store
    from models.embedding_models import get_embeddings
    from utils.env_utils import resolve_embedding_settings

    embedding_settings = resolve_embedding_settings()

    store: GraphStore = get_graph_store()
    entities = store.all_entity_names()
    if not entities:
        print("No entities in graph_store — nothing to migrate.")
        return 0

    old_dim = store.get_meta("embedding_dim")
    print(f"Entities: {len(entities)}")
    print(f"Old embedding_dim (graph_meta): {old_dim}")
    print(
        f"New model: {embedding_settings.model} "
        f"(source={embedding_settings.model_source}, dim {embedding_settings.dimension})"
    )

    if args.dry_run:
        print("[dry-run] would re-embed all entities. Exiting without write.")
        return 0

    # Re-embed entity names in batches.
    emb_fn = get_embeddings()
    new_embeddings: dict[str, list[float]] = {}
    total = len(entities)
    for i in range(0, total, args.batch_size):
        batch = entities[i : i + args.batch_size]
        names = [name for _eid, name in batch]
        vectors = emb_fn.embed_documents(names)
        for (eid, _name), vec in zip(batch, vectors):
            new_embeddings[eid] = vec
        done = min(i + args.batch_size, total)
        print(f"  embedded {done}/{total}")

    updated = store.update_embeddings(
        new_embeddings,
        embedding_model=embedding_settings.model_source,
        embedding_dim=embedding_settings.dimension,
    )

    # Verify: no stale-dim BLOBs remain.

    stale = 0
    for eid, _name in entities:
        # read back via load_all-style (simplified single check)
        with store._lock:  # noqa: SLF001
            cur = store._conn.execute("SELECT embedding FROM entities WHERE id = ?", (eid,))
            row = cur.fetchone()
            blob = row["embedding"] if row else None
            if blob and len(blob) // 4 != embedding_settings.dimension:
                stale += 1

    print(
        {
            "updated": updated,
            "total_entities": total,
            "new_dim": embedding_settings.dimension,
            "stale_blobs_remaining": stale,
        }
    )
    if stale:
        log.warning(f"{stale} entities still have wrong-dim BLOBs after migration")
        return 1

    # Reset graph_retriever singleton so it rebuilds the matrix on next query.
    try:
        from core.retrieval.graph_retriever import reset_graph_retriever

        reset_graph_retriever()
        print("graph_retriever singleton reset — matrix will rebuild on next query.")
    except Exception as e:  # noqa: BLE001
        log.debug(f"graph_retriever reset skipped (may not be initialized): {e}")

    print("Migration complete. GraphRAG entities re-embedded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
