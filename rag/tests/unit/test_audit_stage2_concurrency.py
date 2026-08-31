#!/usr/bin/env python3
"""
Stage 2 audit bugfix tests — B7 (BM25 concurrency) + B8 (EscalationManager).

B7: the BM25 singleton holds three parallel lists mutated in place by
add_documents / remove_by_source / _build_index, while retrieve iterates them.
Under concurrent indexing + query (BackgroundTasks vs run_in_executor) a reader
can observe a half-updated index and raise IndexError (silently swallowed to
[] by _sparse_retrieve). The fix adds an RLock and snapshots at retrieve entry.

B8: EscalationManager shares agent_memory.db with MemoryStore/FeedbackCollector
(which lock for exactly this reason) but has no lock — concurrent writes raise
"database is locked". The fix adds an RLock mirroring FeedbackCollector.

Run: uv run --frozen python -m pytest tests/unit/test_audit_stage2_concurrency.py -v
"""

from __future__ import annotations

import sys
import threading
import time

import pytest

sys.path.insert(0, ".")


# ---------------------------------------------------------------------------
# B7 — BM25 index is thread-safe under concurrent add + retrieve
# ---------------------------------------------------------------------------


def test_b7_bm25_concurrent_add_and_retrieve_no_errors():
    """Hammer add_documents + retrieve from many threads. Without a lock the
    parallel-list mutation raises IndexError mid-iteration (or returns stale
    half-states); with the lock it must be clean."""
    from langchain_core.documents import Document

    from core.retrieval.bm25_retriever import BM25Retriever

    bm25 = BM25Retriever()
    errors: list[Exception] = []

    def _writer():
        try:
            for i in range(40):
                bm25.add_documents(
                    [
                        Document(
                            page_content=f"git 合并冲突 文档 {i} 排查", metadata={"source": f"s{i}"}
                        )
                    ]
                )
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    def _reader():
        try:
            for _ in range(40):
                bm25.retrieve("git 合并冲突")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=_writer) for _ in range(4)]
    threads += [threading.Thread(target=_reader) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"concurrent BM25 access raised: {errors[:3]}"
    # And the final state is consistent: stats document_count matches the lists.
    st = bm25.stats
    assert st["document_count"] == len(bm25._documents) == len(bm25._doc_tokens)


def test_b7_bm25_remove_during_query_no_errors():
    """remove_by_source mutating the lists while a retrieve iterates must not
    raise (the classic concurrent-del-on-shared-list failure)."""
    from langchain_core.documents import Document

    from core.retrieval.bm25_retriever import BM25Retriever

    bm25 = BM25Retriever()
    bm25.add_documents(
        [
            Document(page_content=f"git 合并冲突 {i}", metadata={"source": f"s{i}"})
            for i in range(50)
        ]
    )
    errors: list[Exception] = []

    def _remover():
        try:
            for i in range(50):
                bm25.remove_by_source(f"s{i}")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    def _query():
        try:
            for _ in range(50):
                bm25.retrieve("git 合并冲突")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    t1 = threading.Thread(target=_remover)
    t2 = threading.Thread(target=_query)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)
    assert not errors, f"concurrent remove+retrieve raised: {errors[:3]}"


# ---------------------------------------------------------------------------
# B8 — EscalationManager is thread-safe on the shared agent_memory.db
# ---------------------------------------------------------------------------


def test_b8_escalation_concurrent_creates_no_lock_error(tmp_path):
    """Concurrent create_escalation writes must not raise 'database is locked'
    and must persist all records. Uses a private db file to avoid the shared
    singleton."""
    from agent.feedback.escalation import EscalationManager
    from agent.feedback.types import EscalationLevel

    mgr = EscalationManager(db_path=str(tmp_path / "esc.db"))
    errors: list[Exception] = []

    def _writer(i):
        try:
            for _ in range(20):
                mgr.create_escalation(EscalationLevel.HIGH, f"sess-{i}", answer="a")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=_writer, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    lock_errors = [e for e in errors if "locked" in str(e).lower()]
    assert not lock_errors, f"database is locked errors: {lock_errors[:3]}"
    # All 120 records should persist (6 threads × 20).
    pending = mgr.get_pending()
    assert len(pending) == 120, f"expected 120 escalations, got {len(pending)}"
    mgr.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
