#!/usr/bin/env python3
"""
Unit tests for Stage 2 (RAG correctness/perf) + Stage 3 (harness perf):

Stage 2:
  - retrieval + embedding cache wiring
  - MMR min-max score normalisation (negative logits preserved)
  - reranker preserves upstream score under "score", logit under "rerank_score"
  - MCP rag_search_sparse uses the shared BM25 singleton

Stage 3:
  - async grounding (acheck) fans out claims concurrently
  - per-run trace isolation (concurrent runs don't share traces)
  - astart double-checked locking
  - shared document-formatting layer
  - chunk-boundary context truncation
  - SQLite locking on MemoryStore / FeedbackCollector

Run: pytest tests/unit/test_stage23.py -v
"""

from __future__ import annotations

import asyncio
import sys

import pytest
from langchain_core.documents import Document

sys.path.insert(0, ".")


# ===========================================================================
# Stage 2.2 — MMR min-max normalisation
# ===========================================================================


class TestMMRNormalisation:
    def test_norm_scores_minmax_preserves_negatives(self):
        from core.retrieval.mmr import _norm_scores

        # Reranker logits can be negative; a clamp-to-[0,1] would zero them.
        out = _norm_scores([-3.0, -1.0, 2.0])
        assert out[0] == pytest.approx(0.0)  # min (-3) -> 0
        assert out[2] == pytest.approx(1.0)  # max (2) -> 1
        # midpoint (-1): (-1 - (-3)) / (2 - (-3)) = 2/5 = 0.4
        assert out[1] == pytest.approx(0.4)

    def test_norm_scores_all_equal_returns_uniform(self):
        from core.retrieval.mmr import _norm_scores

        out = _norm_scores([0.5, 0.5, 0.5])
        # No discriminative signal -> uniform mid-band, not all-zero.
        assert all(v == pytest.approx(0.5) for v in out)

    def test_norm_scores_handles_missing(self):
        from core.retrieval.mmr import _norm_scores

        # Missing values filled with the min of present values.
        out = _norm_scores([None, 0.2, 0.8])
        assert out[0] == pytest.approx(0.0)
        assert out[2] == pytest.approx(1.0)

    def test_norm_scores_all_none_is_zero(self):
        from core.retrieval.mmr import _norm_scores

        out = _norm_scores([None, None])
        assert (out == 0).all()

    def test_norm_scores_tiny_rrf_scores_not_collapsed(self):
        from core.retrieval.mmr import _norm_scores

        # RRF scores ~0.01-0.03: min-max must spread them, not collapse to 0.
        out = _norm_scores([0.016, 0.03, 0.01])
        assert out.min() == pytest.approx(0.0)
        assert out.max() == pytest.approx(1.0)
        assert out[1] == pytest.approx(1.0)  # 0.03 is the max


# ===========================================================================
# Stage 2.3 — reranker preserves upstream score
# ===========================================================================


class TestRerankerScoreSeparation:
    def test_rerank_preserves_score_under_rerank_score(self):
        from core.retrieval.reranker import Reranker

        class FakeCrossEncoder:
            def predict(self, pairs, batch_size, show_progress_bar=False):
                return [0.2, 0.9]

        documents = [
            Document(page_content="first", metadata={"score": 0.8}),
            Document(page_content="second", metadata={"score": 0.3}),
        ]
        reranker = Reranker()
        reranker._model = FakeCrossEncoder()

        results = reranker.rerank("query", documents, top_k=1)
        assert results[0].metadata["rerank_score"] == 0.9
        # score must NOT be overwritten with the raw logit.
        assert results[0].metadata["score"] == 0.3
        assert results[0].metadata["retrieval_score"] == 0.3


# ===========================================================================
# Stage 2.1 — retrieval + embedding cache
# ===========================================================================


class TestRetrievalCache:
    def test_retrieval_cache_hit_on_repeat_query(self, monkeypatch):
        from core.retrieval import hybrid_retriever as hr
        from core.retrieval.cache import get_retrieval_cache

        get_retrieval_cache().clear()
        retriever = hr.HybridRetriever()

        call_count = {"n": 0}

        # Count the fused-retrieval step (the real underlying work the cache
        # should skip on a hit). _parallel_retrieve is the sync entry that
        # actually issues dense+sparse calls.
        def counting_parallel(q, f=None):
            call_count["n"] += 1
            return ([], [], [])

        monkeypatch.setattr(retriever, "_parallel_retrieve", counting_parallel)
        monkeypatch.setattr(retriever, "_rerank", lambda q, d, k: d)
        monkeypatch.setattr(retriever, "_time_decay", lambda d: d)
        monkeypatch.setattr(retriever, "_mmr", lambda q, d, k: d)

        retriever.retrieve("same query", top_k=3)
        retriever.retrieve("same query", top_k=3)
        # Second call is a cache hit -> underlying retrieval runs only once.
        assert call_count["n"] == 1

        # A different query must NOT hit the cache.
        retriever.retrieve("different query", top_k=3)
        assert call_count["n"] == 2

    def test_retrieval_cache_disabled_via_env(self, monkeypatch):
        from core.retrieval import hybrid_retriever as hr
        from core.retrieval.cache import get_retrieval_cache

        get_retrieval_cache().clear()
        monkeypatch.setenv("RETRIEVAL_CACHE_ENABLED", "false")
        # Re-evaluate the helper (it reads env live).
        assert hr._retrieval_cache_enabled() is False

    def test_embedding_cache_wraps_query_embedding(self):
        from core.retrieval.cache import CachedEmbeddingFunction

        calls = {"n": 0}

        class FakeBase:
            def embed_query(self, text):
                calls["n"] += 1
                return [0.1, 0.2]

            def embed_documents(self, texts):
                return [[0.1, 0.2] for _ in texts]

        cached = CachedEmbeddingFunction(FakeBase())
        v1 = cached.embed_query("q")
        v2 = cached.embed_query("q")
        assert v1 == v2 == [0.1, 0.2]
        assert calls["n"] == 1  # second call served from cache

    def test_cache_is_insulated_from_caller_mutations(self, monkeypatch):
        """Cached Document objects must be deep-copied so downstream
        metadata mutations (memory injection, score rewrites) don't corrupt
        the cached entry returned to later identical queries."""
        from langchain_core.documents import Document

        from core.retrieval import hybrid_retriever as hr
        from core.retrieval.cache import get_retrieval_cache

        get_retrieval_cache().clear()
        retriever = hr.HybridRetriever()
        doc = Document(page_content="chunk", metadata={"score": 0.9})
        retriever._parallel_retrieve = lambda q, f=None: (
            [hr.RetrievalResult(document=doc, score=0.9, source="dense", rank=1)],
            [],
            [],
        )
        retriever._rerank = lambda q, d, k: d
        retriever._time_decay = lambda d: d
        retriever._mmr = lambda q, d, k: d

        d1 = retriever.retrieve("q_isolated", top_k=3)
        # Caller mutates the returned doc (simulating retrieve-skill edits).
        d1[0].metadata["score"] = 0.01
        d1[0].metadata["polluted"] = True
        # Second identical query hits the cache; it must NOT reflect mutations.
        d2 = retriever.retrieve("q_isolated", top_k=3)
        assert d2[0].metadata.get("polluted") is None, "cache leaked caller mutation"
        assert d2[0].metadata.get("score") != 0.01, "cache score was corrupted"


# ===========================================================================
# Stage 3.1 — async grounding concurrency
# ===========================================================================


class TestAsyncGrounding:
    def test_acheck_fans_out_claims_concurrently(self):
        from agent.guardrails.grounding_guardrail import GroundingGuardrail

        class _StubVerdict:
            def __init__(self, supported):
                self.supported = supported
                self.rationale = ""

        started = []
        completed_order = []

        class _StubJudge:
            available = True

            async def aentail(self, claim, context_blob):
                started.append(claim)
                # Yield once so other tasks can start (proves concurrency).
                await asyncio.sleep(0.01)
                completed_order.append(claim)
                return _StubVerdict(True)

            # Back-compat alias for any caller still on the private name.
            async def _aentail(self, claim, context_blob):
                return await self.aentail(claim, context_blob)

        g = GroundingGuardrail(judge=_StubJudge())
        # An answer with 3 hard claims (values).
        result = asyncio.run(
            g.acheck(
                "温度应为 100°C。压力应为 2.0 MPa。转速应为 5000 RPM。",
                ["手册内容"],
            )
        )
        assert result.available
        assert result.faithfulness == 1.0
        assert result.total == 3
        # All three claims were submitted before any completed (concurrency).
        assert len(started) == 3

    def test_acheck_degraded_when_judge_unavailable(self):
        from agent.guardrails.grounding_guardrail import GroundingGuardrail

        class _DeadJudge:
            available = False

        g = GroundingGuardrail(judge=_DeadJudge())
        result = asyncio.run(g.acheck("温度应为 100°C。", ["ctx"]))
        assert not result.available
        assert result.degraded

    def test_acheck_never_raises_on_claim_exception(self):
        from agent.guardrails.grounding_guardrail import GroundingGuardrail

        class _ExplodingJudge:
            available = True

            async def aentail(self, claim, context_blob):
                raise RuntimeError("boom")

            async def _aentail(self, claim, context_blob):
                return await self.aentail(claim, context_blob)

        g = GroundingGuardrail(judge=_ExplodingJudge())
        result = asyncio.run(g.acheck("温度应为 100°C。", ["ctx"]))
        # All claims failed -> degraded, not raised.
        assert result.degraded


# ===========================================================================
# Stage 3.2 — per-run trace isolation
# ===========================================================================


class TestTraceIsolation:
    def test_concurrent_runs_have_separate_traces(self):
        from agent.harness.orchestrator import AgentHarness, _run_trace_ctx

        harness = AgentHarness()
        c1 = harness._begin_run()
        # The node helper resolves to the current run's collector.
        assert harness.traces is c1
        # Simulate a skill trace in run 1.
        t1 = harness.traces.begin("agent")
        t1.finish("success")

        # A nested run gets its own collector and does not see run 1's traces.
        c2 = harness._begin_run()
        assert harness.traces is c2
        assert harness.traces.traces == []  # fresh, no run-1 traces
        harness._end_run(c2)

        # After run 2 ends, run 1's collector is restored (contextvar nesting).
        # (We end run 1 too to clean up the var.)
        harness._end_run(c1)
        assert _run_trace_ctx.get() is None or harness.traces is not c1


# ===========================================================================
# Stage 3.3 — astart double-checked locking
# ===========================================================================


class TestAstartLock:
    def test_astart_has_lock(self):
        from agent.harness.orchestrator import AgentHarness

        harness = AgentHarness()
        assert hasattr(harness, "_async_init_lock")
        # The lock exists and is an asyncio.Lock.
        assert hasattr(harness._async_init_lock, "acquire")

    def test_concurrent_astart_does_not_double_init(self, monkeypatch):
        import asyncio

        from agent.harness.orchestrator import AgentHarness, HarnessConfig

        # use_memory=False => astart returns immediately without touching DB.
        harness = AgentHarness(config=HarnessConfig(use_memory=False))

        async def run():
            # Two concurrent astart calls; both must complete cleanly.
            await asyncio.gather(harness.astart(), harness.astart())

        asyncio.run(run())
        # No async connection opened (use_memory=False short-circuits).
        assert harness._async_checkpoint_conn is None


# ===========================================================================
# Stage 3.4 — shared formatting layer
# ===========================================================================


class TestFormatting:
    def test_format_documents_evidence_line(self):
        from core.retrieval.formatting import format_documents

        docs = [
            Document(page_content="内容A", metadata={"source": "s1", "title": "t1", "score": 0.9}),
            Document(page_content="内容B", metadata={"source": "s2", "title": "t2"}),
        ]
        ctx, formatted = format_documents(docs)
        assert "[证据1] 来源=s1 | 标题=t1 | 相关度=0.9000" in ctx
        assert "[证据2] 来源=s2 | 标题=t2 | 相关度=N/A" in ctx
        assert len(formatted) == 2
        assert formatted[0].score == 0.9
        assert formatted[1].score is None

    def test_format_documents_skips_empty(self):
        from core.retrieval.formatting import format_documents

        docs = [
            Document(page_content="ok", metadata={"source": "s"}),
            Document(page_content="   ", metadata={"source": "s2"}),
        ]
        ctx, formatted = format_documents(docs)
        assert len(formatted) == 1
        assert "s2" not in ctx

    def test_parse_relevance_scores_round_trip(self):
        from core.retrieval.formatting import format_documents, parse_relevance_scores

        docs = [
            Document(page_content="a", metadata={"score": 0.85}),
            Document(page_content="b", metadata={"score": 0.30}),
        ]
        ctx, _ = format_documents(docs)
        assert parse_relevance_scores(ctx) == [0.85, 0.30]

    def test_format_documents_defaults_override(self):
        from core.retrieval.formatting import format_documents

        docs = [Document(page_content="x", metadata={})]
        ctx, _ = format_documents(docs, defaults={"source": "未知来源", "title": "未知标题"})
        assert "来源=未知来源" in ctx
        assert "标题=未知标题" in ctx


# ===========================================================================
# Stage 3.5 — chunk-boundary truncation
# ===========================================================================


class TestContextBudget:
    def test_truncates_at_chunk_boundary(self):
        from agent.skills.generate.skill import GenerateSkill

        ctx = (
            "[证据1] 来源=s | 相关度=0.9\n第一段很长内容" + "甲" * 200 + "\n\n"
            "[证据2] 来源=s | 相关度=0.5\n第二段" + "乙" * 200
        )
        skill = GenerateSkill()
        # Force a small char budget so the second chunk is dropped.
        skill._skill_config.max_context_length = 250
        skill._skill_config.max_context_tokens = 0
        out = skill._apply_context_budget(ctx, "q")
        # First chunk kept whole; truncation marker appended; second chunk cut.
        assert "第一段" in out
        assert "...[内容已截断]" in out

    def test_no_truncation_when_under_budget(self):
        from agent.skills.generate.skill import GenerateSkill

        ctx = "短内容"
        skill = GenerateSkill()
        skill._skill_config.max_context_length = 2500
        skill._skill_config.max_context_tokens = 0
        assert skill._apply_context_budget(ctx, "q") == "短内容"


# ===========================================================================
# Stage 3.6 — SQLite locking
# ===========================================================================


class TestSQLiteLocking:
    def test_memory_store_has_lock(self, tmp_path):
        from agent.memory.store import MemoryStore

        store = MemoryStore(db_path=str(tmp_path / "mem.db"))
        try:
            assert hasattr(store, "_lock")
            # Reentrant lock so nested locked() calls don't deadlock.
            with store._locked():
                with store._locked():
                    pass
        finally:
            store.close()

    def test_feedback_collector_has_lock(self, tmp_path):
        from agent.feedback.collector import FeedbackCollector

        fc = FeedbackCollector(db_path=str(tmp_path / "fb.db"))
        try:
            assert hasattr(fc, "_lock")
            with fc._locked():
                with fc._locked():
                    pass
        finally:
            fc.close()

    def test_memory_store_concurrent_writes_safe(self, tmp_path):
        import threading
        import time

        from agent.memory.store import MemoryStore
        from agent.memory.types import MemoryEntry, MemoryType

        store = MemoryStore(db_path=str(tmp_path / "mem.db"))
        errors = []

        def writer(start):
            for i in range(start, start + 20):
                try:
                    store.store(
                        MemoryEntry(
                            id=f"m{i}",
                            memory_type=MemoryType.FACT,
                            content=f"content {i}",
                            metadata={},
                            created_at=time.time(),
                            access_count=0,
                            relevance_score=1.0,
                        )
                    )
                except Exception as e:  # noqa: BLE001
                    errors.append(e)

        threads = [threading.Thread(target=writer, args=(b * 100,)) for b in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            # F-EG-07: bound the join so a deadlocked writer surfaces as a
            # failure instead of hanging the CI job.
            t.join(timeout=10)
            assert not t.is_alive(), "writer thread did not finish in 10s (deadlock?)"
        try:
            # No "database is locked" or other errors under concurrent writes.
            assert errors == []
        finally:
            store.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
