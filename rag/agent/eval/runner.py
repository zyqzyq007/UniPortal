"""
Evaluation runner.

Runs golden cases through the live agent pipeline (retrieve -> grade ->
generate) and scores each case with the combined rule-based + LLM-as-judge
scorer. Supports both synchronous (legacy) and asynchronous, concurrency-
bounded execution.

Key fixes vs. the original implementation:
  - intent / source_count are extracted from the actual graph result instead
    of reading non-existent ``shared_state`` keys.
  - reuses the shared agent harness singleton instead of building a new one
    per case (which leaked checkpointer connections).
  - captures retrieved contexts so the judge can score faithfulness /
    hallucination / context precision.
  - adds ``run_all_async`` with an asyncio.Semaphore for bounded concurrency.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

from agent.eval.scorer import EvalScorer
from agent.eval.types import EvalCase, EvalReport, EvalResult
from utils.log_utils import log

__all__ = ["EvalRunner", "DEFAULT_PASS_THRESHOLD", "DEFAULT_CONCURRENCY"]

DEFAULT_PASS_THRESHOLD = 0.6
DEFAULT_CONCURRENCY = 4


def _content_id(text: str) -> str:
    """Deterministic chunk id from text content (mirrors scripts/run_benchmark
    _content_id and prepare_benchmark _chunk_id): sha1 of normalised text[:12].
    Used so golden expected_context_ids (computed the same way) align with the
    ids extracted from retrieved contexts at eval time."""
    norm = " ".join((text or "").strip().split())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


def _extract_contexts(messages: list) -> list[str]:
    """Extract retrieved context strings from ToolMessages in the result."""
    from langchain_core.messages import ToolMessage

    contexts: list[str] = []
    seen = set()
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        content = msg.content
        if isinstance(content, list):
            content = " ".join(
                item.get("text", "") if isinstance(item, dict) else str(item) for item in content
            )
        if isinstance(content, str):
            content = content.strip()
            if content and content not in seen:
                seen.add(content)
                contexts.append(content)
    return contexts


def _count_sources(messages: list) -> int:
    """Count distinct retrieved source documents in the result messages."""
    return len(_extract_contexts(messages))


class EvalRunner:
    """
    Run golden cases through the agent pipeline and score them.

    The runner is stateless between runs and safe to reuse. It does NOT own a
    harness; it resolves the shared singleton lazily so tests can swap it.
    """

    def __init__(
        self,
        scorer: EvalScorer | None = None,
        pass_threshold: float = DEFAULT_PASS_THRESHOLD,
        use_checkpoint: bool = True,
    ):
        self._scorer = scorer or EvalScorer()
        self.pass_threshold = pass_threshold
        # When False, the harness is built WITHOUT a SQLite checkpointer. The
        # async checkpoint path depends on a langgraph-checkpoint-sqlite /
        # langgraph version pairing that is currently mismatched in the pinned
        # dependency set; eval cases are independent (no cross-case state
        # needed), so skipping the checkpointer is safe and avoids the serde
        # AttributeError that otherwise aborts every async case.
        self._use_checkpoint = use_checkpoint
        self._no_checkpoint_harness = None

    # ------------------------------------------------------------------ harness

    def _get_harness(self, case: EvalCase):
        """
        Resolve the agent harness.

        Uses the shared singleton via ``get_agent_harness`` with a per-case
        thread_id so each case gets an isolated conversation in the
        checkpointer (avoids cross-case message leakage). When checkpoints are
        disabled, a single no-memory harness is built once and reused (eval
        cases carry no conversational state between them).
        """
        if not self._use_checkpoint:
            if self._no_checkpoint_harness is None:
                from agent.harness import get_agent_harness
                from agent.harness.orchestrator import HarnessConfig

                self._no_checkpoint_harness = get_agent_harness(HarnessConfig(use_memory=False))
            return self._no_checkpoint_harness

        from agent.harness import get_agent_harness

        return get_agent_harness()

    # ------------------------------------------------------------------ extract

    @staticmethod
    def _extract_result(result: dict[str, Any] | None, query: str = ""):
        """
        Pull (answer, intent, sources, contexts, context_ids) out of a graph result.

        Stage D fixes:
        - context_ids: computed from each retrieved context via _content_id so
          golden expected_context_ids (same algorithm) can be matched.
        - intent: the graph has no intent node; classify the query directly with
          the real intent classifier (same one the API router uses) instead of
          guessing "rag_query".
        """
        if not result:
            return "", "", 0, [], []

        messages = result.get("messages", []) or []
        answer = ""
        if messages:
            last = messages[-1]
            answer = getattr(last, "content", str(last)) or ""

        contexts = _extract_contexts(messages)

        # Fast mode attaches sources as a structured list under _sources.
        fast_sources = result.get("_sources")
        if isinstance(fast_sources, list):
            sources_count = len(fast_sources)
            # Also fold fast-mode source content into contexts for the judge.
            for s in fast_sources:
                if isinstance(s, dict):
                    snippet = s.get("content") or s.get("text")
                    if snippet and snippet not in contexts:
                        contexts.append(snippet)
        else:
            sources_count = _count_sources(messages)

        # Deterministic chunk ids from the retrieved context texts (Stage D
        # REQ-RD-001). Mirrors the golden expected_context_ids algorithm so the
        # set-overlap precision/recall in scorer.score_context_ids works.
        context_ids = [_content_id(c) for c in contexts if c]

        # Intent: classify the query directly (Stage D REQ-RD-003). The graph
        # has no intent node, and eval bypasses the API router where intent is
        # normally classified — so we run the same classifier here. This makes
        # intent_accuracy reflect a real classification, not a constant.
        intent = ""
        if result.get("_fast_mode"):
            intent = "rag_query"
        elif query:
            try:
                from core.intent.classifier import get_intent_classifier

                ic = get_intent_classifier()
                ir = ic.classify(query)
                intent = getattr(getattr(ir, "intent", None), "value", "") or ""
            except Exception as e:  # noqa: BLE001
                log.debug(f"eval intent classification failed: {e}")
                intent = ""

        return answer, intent, sources_count, contexts, context_ids

    # ------------------------------------------------------------------ sync

    def run_case(self, case: EvalCase) -> EvalResult:
        """Run a single case synchronously and score it."""
        start = time.perf_counter()
        try:
            harness = self._get_harness(case)
            result = harness.invoke(case.query, thread_id=f"eval_{case.id}")
            answer, intent, sources, contexts, context_ids = self._extract_result(
                result, case.query
            )

            score = self._scorer.score(
                case=case,
                actual_answer=answer,
                actual_intent=intent,
                actual_sources=sources,
                retrieved_contexts=contexts,
                retrieved_context_ids=context_ids,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            return EvalResult(
                case_id=case.id,
                score=score,
                actual_answer=answer,
                actual_intent=intent,
                actual_sources=sources,
                retrieved_contexts=contexts,
                execution_time_ms=elapsed_ms,
            )
        except Exception as e:  # noqa: BLE001 - per-case isolation
            log.error(f"EvalRunner: case {case.id} failed: {e}")
            return EvalResult(
                case_id=case.id,
                execution_time_ms=(time.perf_counter() - start) * 1000,
                error=str(e),
            )

    def run_all(self, cases: list[EvalCase] | None = None) -> EvalReport:
        """Run all cases synchronously (legacy entry point)."""
        if cases is None:
            from agent.eval.dataset import load_dataset

            cases = load_dataset()

        results: list[EvalResult] = []
        for case in cases:
            log.info(f"EvalRunner: running case {case.id} - {case.query[:30]}...")
            results.append(self.run_case(case))
        return self._build_report(results)

    # ------------------------------------------------------------------ async

    async def run_case_async(self, case: EvalCase) -> EvalResult:
        """Run a single case asynchronously."""
        start = time.perf_counter()
        try:
            harness = self._get_harness(case)
            result = await harness.ainvoke(case.query, thread_id=f"eval_{case.id}")
            answer, intent, sources, contexts, context_ids = self._extract_result(
                result, case.query
            )

            score = self._scorer.score(
                case=case,
                actual_answer=answer,
                actual_intent=intent,
                actual_sources=sources,
                retrieved_contexts=contexts,
                retrieved_context_ids=context_ids,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            return EvalResult(
                case_id=case.id,
                score=score,
                actual_answer=answer,
                actual_intent=intent,
                actual_sources=sources,
                retrieved_contexts=contexts,
                execution_time_ms=elapsed_ms,
            )
        except Exception as e:  # noqa: BLE001
            log.error(f"EvalRunner: case {case.id} failed (async): {e}")
            return EvalResult(
                case_id=case.id,
                execution_time_ms=(time.perf_counter() - start) * 1000,
                error=str(e),
            )

    async def run_all_async(
        self,
        cases: list[EvalCase] | None = None,
        concurrency: int = DEFAULT_CONCURRENCY,
    ) -> EvalReport:
        """Run all cases with bounded concurrency."""
        if cases is None:
            from agent.eval.dataset import load_dataset

            cases = load_dataset()

        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def _bounded(case: EvalCase) -> EvalResult:
            async with semaphore:
                log.info(f"EvalRunner: running case {case.id} - {case.query[:30]}...")
                return await self.run_case_async(case)

        tasks = [asyncio.create_task(_bounded(c)) for c in cases]
        results = await asyncio.gather(*tasks)
        return self._build_report(list(results))

    # ------------------------------------------------------------------ report

    def _build_report(self, results: list[EvalResult]) -> EvalReport:
        total = len(results)
        valid = [r for r in results if r.error is None]
        passed = sum(1 for r in valid if r.score.overall_score >= self.pass_threshold)
        failed = total - passed
        avg_score = sum(r.score.overall_score for r in valid) / len(valid) if valid else 0.0

        def _avg(attr: str) -> float | None:
            vals = [getattr(r.score, attr) for r in valid if getattr(r.score, attr) is not None]
            return sum(vals) / len(vals) if vals else None

        report = EvalReport(
            total_cases=total,
            passed=passed,
            failed=failed,
            average_score=avg_score,
            avg_faithfulness=_avg("faithfulness"),
            avg_answer_relevancy=_avg("answer_relevancy"),
            avg_hallucination=_avg("hallucination_score"),
            avg_context_precision=_avg("context_precision"),
            avg_context_recall=_avg("context_recall"),
            results=results,
        )
        log.info(
            f"EvalRunner: {total} cases, {passed} passed, {failed} failed, avg={avg_score:.3f}"
        )
        return report
