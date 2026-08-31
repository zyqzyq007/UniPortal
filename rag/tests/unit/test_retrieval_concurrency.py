#!/usr/bin/env python3
"""
F11 — hybrid retriever parallel executor is instance-scoped + configurable,
and close() releases it.

Previously ``_executor`` was a class-level ``ThreadPoolExecutor(max_workers=2)``
shared across every request — a process-wide serialization point. It is now
instance-scoped with ``RETRIEVAL_PARALLEL_WORKERS`` (default 4) and shut down in
``close()``.

F12 — sync invoke()/stream() serialized by a process lock so the shared sync
SQLite checkpointer connection is not written concurrently across threads.

Run: pytest tests/unit/test_retrieval_concurrency.py tests/unit/test_checkpoint_serde_compat.py -v
"""

from __future__ import annotations

import sys
import threading
import time

import pytest

sys.path.insert(0, ".")


# ===========================================================================
# F11
# ===========================================================================


class TestRetrieverExecutorInstanceScoped:
    def test_executor_is_instance_attribute_not_class(self):
        from core.retrieval.hybrid_retriever import HybridRetriever

        class _FakeDense:
            def query(self, **kwargs):
                return []

        a = HybridRetriever(dense_manager=_FakeDense())
        b = HybridRetriever(dense_manager=_FakeDense())
        assert a._executor is not b._executor
        a.close()
        b.close()

    def test_executor_worker_count_configurable(self, monkeypatch):
        from core.retrieval.hybrid_retriever import HybridRetriever

        class _FakeDense:
            def query(self, **kwargs):
                return []

        monkeypatch.setenv("RETRIEVAL_PARALLEL_WORKERS", "8")
        hr = HybridRetriever(dense_manager=_FakeDense())
        # ThreadPoolExecutor exposes _max_workers (CPython); guard with getattr.
        assert getattr(hr._executor, "_max_workers", None) == 8
        hr.close()

    def test_close_shuts_down_executor(self):
        from core.retrieval.hybrid_retriever import HybridRetriever

        class _FakeDense:
            def query(self, **kwargs):
                return []

        hr = HybridRetriever(dense_manager=_FakeDense())
        hr.close()
        # After shutdown, submitting raises RuntimeError.
        with pytest.raises(RuntimeError):
            hr._executor.submit(lambda: None)

    def test_close_is_idempotent(self):
        from core.retrieval.hybrid_retriever import HybridRetriever

        class _FakeDense:
            def query(self, **kwargs):
                return []

        hr = HybridRetriever(dense_manager=_FakeDense())
        hr.close()
        hr.close()  # must not raise


# ===========================================================================
# F12 — sync invoke() serialised across threads
# ===========================================================================


class TestSyncInvokeLock:
    def test_sync_invoke_lock_exists(self):
        from agent.harness.orchestrator import AgentHarness

        h = AgentHarness()
        assert isinstance(h._sync_invoke_lock, type(threading.Lock()))
        h.close()

    def test_concurrent_sync_invokes_do_not_interleave_graph_calls(self, monkeypatch):
        """Two threads calling invoke() must execute graph.invoke() strictly
        sequentially (the lock serializes them). We assert mutual exclusion by
        recording overlap while the graph is 'running'."""
        from agent.harness.orchestrator import AgentHarness

        h = AgentHarness()
        in_critical = 0
        max_overlap = 0
        guard = threading.Lock()

        class _FakeGraph:
            def invoke(self, inputs, config=None):
                nonlocal in_critical, max_overlap
                with guard:
                    in_critical += 1
                    max_overlap = max(max_overlap, in_critical)
                time.sleep(0.05)  # hold the critical section
                with guard:
                    in_critical -= 1
                return {"messages": []}

        h._graph = _FakeGraph()
        # Force thinking mode (not fast) so invoke() hits the graph path.
        h._planner.plan = lambda **kw: type(
            "P", (), {"plan_type": type("PT", (), {"FAST": "fast"})()}
        )()  # not FAST
        # Simpler: monkeypatch planner to return a non-FAST plan.
        from agent.harness.planner import PlanType

        h._planner.plan = lambda **kw: type("Plan", (), {"plan_type": PlanType.THINKING})()

        def _call():
            h.invoke("q", thread_id="t")

        threads = [threading.Thread(target=_call) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            # F-EG-07: bound the join so a deadlocked invoke() surfaces as a
            # failure instead of hanging the CI job.
            t.join(timeout=10)
            assert not t.is_alive(), "invoke thread did not finish in 10s (deadlock?)"

        assert max_overlap == 1, (
            f"sync invoke() calls overlapped in the graph critical section "
            f"(max_overlap={max_overlap}); the lock failed to serialize"
        )
        h.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
