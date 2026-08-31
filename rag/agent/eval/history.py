"""
Evaluation run history and regression comparison.

Each eval run is persisted as:
  - a per-case detail JSON under ``data/eval/runs/run_<id>.json``
  - a summary record appended to ``data/eval/runs/history.jsonl`` (one JSON
    object per line, easy to tail / stream)

The most recent summary on the default dataset is treated as the CI baseline;
``compare_runs`` produces a per-metric RegressionReport used as a gate.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from agent.eval.types import (
    EvalReport,
    EvalResult,
    EvalRunSummary,
    MetricDelta,
    RegressionReport,
)
from utils.log_utils import log

__all__ = [
    "RUNS_DIR",
    "HISTORY_PATH",
    "new_run_id",
    "get_git_commit",
    "save_run",
    "load_history",
    "latest_summary",
    "compare_runs",
    "DEFAULT_THRESHOLDS",
]

RUNS_DIR = Path("data/eval/runs")
HISTORY_PATH = RUNS_DIR / "history.jsonl"

# Per-metric regression thresholds. A metric "regresses" when its delta is
# worse than these magnitudes. For "higher is better" metrics, delta is
# current - baseline; regression when delta <= -threshold.
DEFAULT_THRESHOLDS: dict[str, float] = {
    "average_score": 0.05,
    "avg_faithfulness": 0.05,
    "avg_answer_relevancy": 0.05,
    "avg_context_precision": 0.05,
    "avg_context_recall": 0.05,
    "avg_hallucination": 0.05,  # hallucination: lower is better
}

# Which metrics are "higher is better" vs "lower is better".
HIGHER_IS_BETTER = {
    "average_score",
    "avg_faithfulness",
    "avg_answer_relevancy",
    "avg_context_precision",
    "avg_context_recall",
}
LOWER_IS_BETTER = {"avg_hallucination"}


def new_run_id() -> str:
    """Generate a sortable, unique run id."""
    ts = time.strftime("%Y%m%d_%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"run_{ts}_{short}"


def get_git_commit() -> str:
    """Best-effort current git commit hash (short)."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            cwd=os.getcwd(),
        )
        return out.decode().strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _ensure_dirs() -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def _report_to_summary(
    report: EvalReport,
    run_id: str,
    tag: str,
    dataset: str,
    git_commit: str,
    detail_path: str,
) -> EvalRunSummary:
    return EvalRunSummary(
        run_id=run_id,
        timestamp=report.timestamp,
        git_commit=git_commit,
        tag=tag,
        dataset=dataset,
        total_cases=report.total_cases,
        passed=report.passed,
        failed=report.failed,
        average_score=report.average_score,
        avg_faithfulness=report.avg_faithfulness,
        avg_answer_relevancy=report.avg_answer_relevancy,
        avg_hallucination=report.avg_hallucination,
        avg_context_precision=report.avg_context_precision,
        avg_context_recall=report.avg_context_recall,
        judge_used=any(r.score.judge_used for r in report.results),
        detail_path=str(detail_path),
    )


def _result_to_dict(r: EvalResult) -> dict[str, Any]:
    return {
        "case_id": r.case_id,
        "score": {
            "section_coverage": r.score.section_coverage,
            "keyword_coverage": r.score.keyword_coverage,
            "intent_accuracy": r.score.intent_accuracy,
            "source_count_ok": r.score.source_count_ok,
            "faithfulness": r.score.faithfulness,
            "answer_relevancy": r.score.answer_relevancy,
            "hallucination_score": r.score.hallucination_score,
            "context_precision": r.score.context_precision,
            "context_recall": r.score.context_recall,
            "judge_used": r.score.judge_used,
            "overall_score": r.score.overall_score,
            "details": r.score.details,
        },
        "actual_answer": r.actual_answer,
        "actual_intent": r.actual_intent,
        "actual_sources": r.actual_sources,
        "retrieved_contexts": r.retrieved_contexts,
        "execution_time_ms": r.execution_time_ms,
        "error": r.error,
    }


def save_run(
    report: EvalReport,
    tag: str = "manual",
    dataset: str = "data/eval/golden.yaml",
    run_id: str | None = None,
    git_commit: str | None = None,
) -> EvalRunSummary:
    """
    Persist a full run: detail JSON + append summary to history.jsonl.

    Returns the EvalRunSummary (also written to history).
    """
    _ensure_dirs()
    run_id = run_id or new_run_id()
    git_commit = git_commit or get_git_commit()
    detail_path = RUNS_DIR / f"{run_id}.json"

    detail = {
        "run_id": run_id,
        "tag": tag,
        "dataset": dataset,
        "git_commit": git_commit,
        "timestamp": report.timestamp,
        "summary": {
            "total_cases": report.total_cases,
            "passed": report.passed,
            "failed": report.failed,
            "average_score": report.average_score,
            "avg_faithfulness": report.avg_faithfulness,
            "avg_answer_relevancy": report.avg_answer_relevancy,
            "avg_hallucination": report.avg_hallucination,
            "avg_context_precision": report.avg_context_precision,
            "avg_context_recall": report.avg_context_recall,
        },
        "results": [_result_to_dict(r) for r in report.results],
    }
    detail_path.write_text(
        json.dumps(detail, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary = _report_to_summary(report, run_id, tag, dataset, git_commit, str(detail_path))
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary.to_dict(), ensure_ascii=False) + "\n")

    log.info(f"Eval run saved: {run_id} (detail={detail_path})")
    return summary


def load_history(limit: int | None = None) -> list[EvalRunSummary]:
    """Load run summaries from history.jsonl, newest last."""
    if not HISTORY_PATH.exists():
        return []
    summaries: list[EvalRunSummary] = []
    with HISTORY_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                summaries.append(EvalRunSummary(**d))
            except Exception:  # noqa: BLE001 - skip malformed lines
                continue
    if limit:
        summaries = summaries[-limit:]
    return summaries


def latest_summary(dataset: str | None = None) -> EvalRunSummary | None:
    """
    Most recent summary, optionally filtered by dataset path.

    Used as the CI regression baseline.
    """
    history = load_history()
    if dataset:
        history = [s for s in history if s.dataset == dataset]
    return history[-1] if history else None


def _metric_delta(
    metric: str,
    baseline: float | None,
    current: float | None,
    thresholds: dict[str, float],
) -> MetricDelta:
    """Compute a single metric delta and whether it regressed."""
    threshold = thresholds.get(metric, 0.05)
    if baseline is None or current is None:
        # Cannot compare; treat as non-regression but flag missing data.
        return MetricDelta(
            metric=metric,
            baseline=baseline,
            current=current,
            delta=None,
            regressed=False,
        )
    delta = current - baseline
    regressed = False
    if metric in HIGHER_IS_BETTER:
        regressed = delta <= -threshold
    elif metric in LOWER_IS_BETTER:
        regressed = delta >= threshold  # hallucination increased
    return MetricDelta(
        metric=metric,
        baseline=baseline,
        current=current,
        delta=delta,
        regressed=regressed,
    )


def compare_runs(
    baseline: EvalRunSummary,
    current: EvalRunSummary,
    thresholds: dict[str, float] | None = None,
) -> RegressionReport:
    """
    Compare two run summaries and produce a regression report.

    Used as the CI gate: ``report.passed == False`` means at least one metric
    regressed beyond its threshold.
    """
    thresholds = thresholds or DEFAULT_THRESHOLDS

    metric_pairs = [
        ("average_score", baseline.average_score, current.average_score),
        ("avg_faithfulness", baseline.avg_faithfulness, current.avg_faithfulness),
        ("avg_answer_relevancy", baseline.avg_answer_relevancy, current.avg_answer_relevancy),
        ("avg_context_precision", baseline.avg_context_precision, current.avg_context_precision),
        ("avg_context_recall", baseline.avg_context_recall, current.avg_context_recall),
        ("avg_hallucination", baseline.avg_hallucination, current.avg_hallucination),
    ]

    deltas = [_metric_delta(name, b, c, thresholds) for name, b, c in metric_pairs]
    regressions = [d for d in deltas if d.regressed]
    passed = len(regressions) == 0

    if passed:
        summary = "No regression: all metrics within thresholds."
    else:
        summary = "Regression detected: " + ", ".join(
            f"{d.metric} {d.baseline}->{d.current} (Δ={d.delta:+.3f})" for d in regressions
        )

    return RegressionReport(
        baseline_run_id=baseline.run_id,
        current_run_id=current.run_id,
        deltas=deltas,
        regressions=regressions,
        passed=passed,
        summary=summary,
    )
