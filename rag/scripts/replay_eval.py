#!/usr/bin/env python3
"""
Offline replay evaluator — scores pre-recorded (query, answer, contexts)
records WITHOUT running the agent pipeline or touching the network.

This is the fully-offline, data-only evaluation entry point:
  - No harness.invoke(), no retrieval, no generation.
  - The judge uses the local Ollama Qwen3 + local BGE embeddings only.
  - Data comes from a JSONL file (see data/eval/replay_samples.jsonl).

Use cases:
  - Evaluate a batch of recorded answers in an air-gapped environment.
  - Re-score historical production inferences after a judge / prompt change.
  - CI regression on a frozen dataset with deterministic, offline scoring.

Usage:
    python scripts/replay_eval.py data/eval/replay_samples.jsonl
    python scripts/replay_eval.py data/eval/replay_samples.jsonl --no-judge
    python scripts/replay_eval.py data/eval/replay_samples.jsonl --fail-on-regression
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.eval.history import (  # noqa: E402
    compare_runs,
    get_git_commit,
    load_history,
    save_run,
)
from agent.eval.scorer import EvalScorer  # noqa: E402
from agent.eval.types import EvalCase, EvalReport, EvalResult  # noqa: E402
from utils.log_utils import log  # noqa: E402

__all__ = ["load_replay_records", "record_to_case", "ReplayEvaluator"]


# =============================================================================
# JSONL loading
# =============================================================================


def _normalize_context(ctx: Any) -> str:
    """Accept str or {'content': ...} dict; return the text."""
    if isinstance(ctx, str):
        return ctx
    if isinstance(ctx, dict):
        return ctx.get("content", "") or ctx.get("text", "") or ""
    return str(ctx)


def load_replay_records(path: str) -> list[dict[str, Any]]:
    """
    Load replay records from a JSONL file.

    Lines starting with '#' and blank lines are ignored (the file can carry
    a header comment, like data/eval/replay_samples.jsonl).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Replay dataset not found: {path}")
    records: list[dict[str, Any]] = []
    for lineno, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            rec = json.loads(line)
            if isinstance(rec, dict):
                records.append(rec)
        except json.JSONDecodeError as e:
            log.warning(f"Skipping malformed line {lineno} in {path}: {e}")
    log.info(f"Loaded {len(records)} replay records from {path}")
    return records


def record_to_case(rec: dict[str, Any]):
    """
    Convert a replay record into (EvalCase, contexts).

    Replay records carry trustworthy-eval fields (query / answer / contexts /
    reference_answer). Rule-based golden fields (expected_sections / keywords)
    are left empty so they do not interfere — section/keyword coverage
    gracefully default to 1.0 in the scorer.

    Returns:
        (EvalCase, list_of_context_strings)
    """
    contexts = [_normalize_context(c) for c in (rec.get("contexts") or [])]
    contexts = [c for c in contexts if c.strip()]
    case = EvalCase(
        id=rec.get("id", ""),
        query=rec.get("query", ""),
        reference_answer=rec.get("reference_answer", "") or "",
        expected_intent=rec.get("intent", ""),
        # No rule-based expectations in replay mode.
        expected_sections=[],
        expected_keywords=[],
        expected_min_sources=0,
        tags=list(rec.get("tags") or []),
        source="replay",
    )
    return case, contexts


# =============================================================================
# Replay evaluator — no harness, no network
# =============================================================================


class ReplayEvaluator:
    """
    Scores replay records purely from data + the local judge.

    Unlike EvalRunner, it never calls harness.invoke(): the answer and
    contexts are taken verbatim from the dataset.
    """

    def __init__(
        self,
        scorer: EvalScorer | None = None,
        pass_threshold: float = 0.6,
    ):
        self._scorer = scorer or EvalScorer()
        self.pass_threshold = pass_threshold

    def score_record(self, rec: dict[str, Any]) -> EvalResult:
        case, contexts = record_to_case(rec)
        answer = rec.get("answer", "") or ""
        intent = rec.get("intent", "") or ""
        source_count = rec.get("source_count")
        if source_count is None:
            source_count = len(contexts)

        score = self._scorer.score(
            case=case,
            actual_answer=answer,
            actual_intent=intent,
            actual_sources=source_count,
            retrieved_contexts=contexts,
        )
        return EvalResult(
            case_id=case.id,
            score=score,
            actual_answer=answer,
            actual_intent=intent,
            actual_sources=source_count,
            retrieved_contexts=contexts,
        )

    async def score_all_async(
        self,
        records: list[dict[str, Any]],
        concurrency: int = 4,
    ) -> EvalReport:
        """Score all records with bounded concurrency (judge calls)."""
        import asyncio

        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def _bounded(rec):
            async with semaphore:
                return self.score_record(rec)

        tasks = [asyncio.create_task(_bounded(r)) for r in records]
        results = await asyncio.gather(*tasks)
        return self._build_report(list(results))

    def _build_report(self, results: list[EvalResult]) -> EvalReport:
        total = len(results)
        valid = [r for r in results if r.error is None]
        passed = sum(1 for r in valid if r.score.overall_score >= self.pass_threshold)
        failed = total - passed
        avg_score = sum(r.score.overall_score for r in valid) / len(valid) if valid else 0.0

        def _avg(attr: str) -> float | None:
            vals = [getattr(r.score, attr) for r in valid if getattr(r.score, attr) is not None]
            return sum(vals) / len(vals) if vals else None

        return EvalReport(
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


# =============================================================================
# CLI
# =============================================================================


def _fmt(v: float | None) -> str:
    return f"{v:.3f}" if isinstance(v, (int, float)) else "  n/a"


def _print_summary(summary) -> None:
    print("\n" + "=" * 60)
    print(f"Replay run {summary.run_id}  (tag={summary.tag}, commit={summary.git_commit})")
    print("=" * 60)
    print(
        f"  total / passed / failed : {summary.total_cases} / {summary.passed} / {summary.failed}"
    )
    print(f"  average_score           : {_fmt(summary.average_score)}")
    print(f"  avg_faithfulness        : {_fmt(summary.avg_faithfulness)}")
    print(f"  avg_answer_relevancy    : {_fmt(summary.avg_answer_relevancy)}")
    print(f"  avg_context_precision   : {_fmt(summary.avg_context_precision)}")
    print(f"  avg_context_recall      : {_fmt(summary.avg_context_recall)}")
    print(f"  avg_hallucination       : {_fmt(summary.avg_hallucination)}")
    print(f"  judge_used              : {summary.judge_used}")
    print(f"  detail                  : {summary.detail_path}")
    print("=" * 60)


async def _run(args: argparse.Namespace) -> int:
    records = load_replay_records(args.dataset)
    if not records:
        log.error("No records to evaluate.")
        return 2

    scorer = EvalScorer(use_judge=not args.no_judge)
    evaluator = ReplayEvaluator(scorer=scorer, pass_threshold=args.pass_threshold)

    log.info(
        f"Replay-evaluating {len(records)} records "
        f"(concurrency={args.concurrency}, judge={'off' if args.no_judge else 'on'})"
    )
    report = await evaluator.score_all_async(records, concurrency=args.concurrency)

    dataset_tag = f"replay:{Path(args.dataset).name}"
    summary = save_run(
        report=report,
        tag=args.tag,
        dataset=dataset_tag,
        git_commit=get_git_commit(),
    )
    _print_summary(summary)

    if args.fail_on_regression:
        prior = [
            s for s in load_history() if s.dataset == dataset_tag and s.run_id != summary.run_id
        ]
        baseline = prior[-1] if prior else None
        if baseline is None:
            print("\nNo baseline available — skipping regression gate.")
            return 0
        reg = compare_runs(baseline, summary)
        print(f"\n--- Regression vs baseline {baseline.run_id} ---")
        for d in reg.deltas:
            mark = "!!" if d.regressed else "  "
            ds = f"{d.delta:+.3f}" if d.delta is not None else "  n/a"
            print(f"  {mark} {d.metric:<22} {_fmt(d.baseline)} -> {_fmt(d.current)} (Δ {ds})")
        print(f"\n  => {'PASS' if reg.passed else 'FAIL'}: {reg.summary}")
        return 0 if reg.passed else 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline replay evaluator: score recorded (query,answer,contexts) from JSONL."
    )
    parser.add_argument("dataset", help="Path to a JSONL replay dataset.")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--no-judge", action="store_true", help="Rule-based only (no judge LLM calls)."
    )
    parser.add_argument("--tag", default="replay")
    parser.add_argument("--pass-threshold", type=float, default=0.6)
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit 1 if any metric regresses vs the previous replay run.",
    )
    args = parser.parse_args(argv)

    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
