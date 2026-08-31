#!/usr/bin/env python3
"""
Evaluation CLI — run the golden dataset through the live agent pipeline,
score with the local LLM-as-judge, persist the run, and (optionally) gate on
regression vs. the latest baseline.

Usage:
    # Full run with judge, persisted to history
    python scripts/run_eval.py

    # CI mode: fail (exit 1) if any metric regresses vs. baseline
    python scripts/run_eval.py --tag ci --fail-on-regression

    # Fast: rule-based scoring only (no judge LLM calls)
    python scripts/run_eval.py --no-judge --concurrency 8

    # Compare two specific runs without re-running
    python scripts/run_eval.py --compare-only --baseline <run_id> --current <run_id>
"""

from __future__ import annotations

import argparse
import asyncio
import json

# Allow running from repo root without install.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.eval import (  # noqa: E402
    EvalRunner,
    EvalScorer,
    load_dataset,
    load_history,
    save_run,
)
from agent.eval.history import compare_runs, get_git_commit  # noqa: E402
from agent.eval.types import EvalRunSummary  # noqa: E402
from utils.log_utils import log  # noqa: E402

DEFAULT_DATASET = "data/eval/golden.yaml"


def _fmt_metric(v: float | None) -> str:
    return f"{v:.3f}" if isinstance(v, (int, float)) else "  n/a"


def _print_summary(summary: EvalRunSummary) -> None:
    print("\n" + "=" * 60)
    print(f"Run {summary.run_id}  (tag={summary.tag}, commit={summary.git_commit})")
    print("=" * 60)
    print(
        f"  total / passed / failed : {summary.total_cases} / {summary.passed} / {summary.failed}"
    )
    print(f"  average_score           : {_fmt_metric(summary.average_score)}")
    print(f"  avg_faithfulness        : {_fmt_metric(summary.avg_faithfulness)}")
    print(f"  avg_answer_relevancy    : {_fmt_metric(summary.avg_answer_relevancy)}")
    print(f"  avg_context_precision   : {_fmt_metric(summary.avg_context_precision)}")
    print(f"  avg_context_recall      : {_fmt_metric(summary.avg_context_recall)}")
    print(f"  avg_hallucination       : {_fmt_metric(summary.avg_hallucination)}")
    print(f"  judge_used              : {summary.judge_used}")
    print(f"  detail                  : {summary.detail_path}")
    print("=" * 60)


def _find_run(run_id: str) -> EvalRunSummary | None:
    for s in load_history():
        if s.run_id == run_id:
            return s
    return None


async def _run(args: argparse.Namespace) -> int:
    dataset_path = args.dataset or DEFAULT_DATASET
    cases = load_dataset(dataset_path)
    if not cases:
        log.error(f"No cases loaded from {dataset_path}")
        return 2

    # Optionally filter by tag/difficulty.
    if args.tag_filter:
        cases = [c for c in cases if any(t in c.tags for t in args.tag_filter)]
    if args.difficulty:
        cases = [c for c in cases if c.difficulty == args.difficulty]
    if args.limit:
        cases = cases[: args.limit]

    if not cases:
        log.error("No cases after filtering.")
        return 2

    scorer = EvalScorer(use_judge=not args.no_judge)
    runner = EvalRunner(
        scorer=scorer,
        pass_threshold=args.pass_threshold,
        # Eval cases are independent; skip the checkpointer to avoid the
        # langgraph-checkpoint-sqlite / langgraph version serde mismatch.
        use_checkpoint=False,
    )

    log.info(
        f"Running {len(cases)} cases (concurrency={args.concurrency}, "
        f"judge={'off' if args.no_judge else 'on'})"
    )
    report = await runner.run_all_async(cases, concurrency=args.concurrency)

    summary = save_run(
        report=report,
        tag=args.tag,
        dataset=dataset_path,
        git_commit=get_git_commit(),
    )
    _print_summary(summary)

    # Regression gate.
    if args.fail_on_regression:
        baseline = None
        if args.baseline:
            baseline = _find_run(args.baseline)
            if baseline is None:
                log.error(f"Baseline run not found: {args.baseline}")
                return 2
        else:
            # Use the latest run on this dataset that is NOT the current run.
            prior = [
                s
                for s in load_history()
                if s.dataset == dataset_path and s.run_id != summary.run_id
            ]
            baseline = prior[-1] if prior else None

        if baseline is None:
            print("\nNo baseline available — skipping regression gate.")
            return 0

        reg = compare_runs(baseline, summary)
        print(f"\n--- Regression vs baseline {baseline.run_id} (commit {baseline.git_commit}) ---")
        for d in reg.deltas:
            mark = "!!" if d.regressed else ("  " if d.delta is not None else "??")
            ds = f"{d.delta:+.3f}" if d.delta is not None else "  n/a"
            print(
                f"  {mark} {d.metric:<22} "
                f"{_fmt_metric(d.baseline)} -> {_fmt_metric(d.current)}  (Δ {ds})"
            )
        print(f"\n  => {'PASS' if reg.passed else 'FAIL'}: {reg.summary}")
        return 0 if reg.passed else 1

    return 0


def _compare_only(args: argparse.Namespace) -> int:
    baseline = _find_run(args.baseline)
    current = _find_run(args.current)
    if baseline is None or current is None:
        log.error("Need both --baseline and --current run ids.")
        return 2
    reg = compare_runs(baseline, current)
    print(json.dumps(reg.to_dict(), ensure_ascii=False, indent=2))
    return 0 if reg.passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the RAG evaluation suite.")
    parser.add_argument(
        "--dataset", default=DEFAULT_DATASET, help="Path to golden dataset (YAML/JSON)."
    )
    parser.add_argument("--concurrency", type=int, default=4, help="Max concurrent cases.")
    parser.add_argument(
        "--no-judge", action="store_true", help="Disable LLM-as-judge (rule-based only)."
    )
    parser.add_argument("--tag", default="manual", help="Run tag (ci / nightly / manual).")
    parser.add_argument("--pass-threshold", type=float, default=0.6, help="Per-case pass score.")
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N cases.")
    parser.add_argument("--difficulty", default=None, help="Filter cases by difficulty.")
    parser.add_argument("--tag-filter", nargs="+", default=None, help="Filter cases by tag.")
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit 1 if any metric regresses vs baseline.",
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help="Baseline run id for regression (default: latest on dataset).",
    )
    parser.add_argument(
        "--compare-only", action="store_true", help="Compare two existing runs without re-running."
    )
    parser.add_argument(
        "--current", default=None, help="Current run id (used with --compare-only)."
    )
    args = parser.parse_args(argv)

    if args.compare_only:
        return _compare_only(args)

    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
