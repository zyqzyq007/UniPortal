"""
Agent evaluation subsystem.

Trustworthy RAG evaluation with a local LLM-as-judge (faithfulness /
answer relevancy / hallucination / context precision & recall), externalised
golden datasets, run-history with regression comparison, and a feedback
flywheel (online inference capture -> candidate promotion -> retrieval tuning).

Public API:
    EvalRunner       — run golden cases through the live pipeline and score
    LLMJudge         — local Qwen3 judge (also the online re-eval engine)
    load_dataset     — load YAML/JSON golden datasets
    save_run / compare_runs — eval history + CI regression gate
"""

from agent.eval.candidates import (
    CandidateRecord,
    list_candidates,
    promote_candidate_to_golden,
    promote_to_candidate,
)
from agent.eval.dataset import append_cases, load_dataset
from agent.eval.flywheel import get_retrieval_misses, on_negative_feedback
from agent.eval.history import (
    DEFAULT_THRESHOLDS,
    compare_runs,
    latest_summary,
    load_history,
    save_run,
)
from agent.eval.inference_store import InferenceRecord, InferenceStore, get_inference_store
from agent.eval.judge import LLMJudge, TrustworthyMetrics, get_judge
from agent.eval.runner import EvalRunner
from agent.eval.sampler import should_sample
from agent.eval.scorer import EvalScorer
from agent.eval.types import (
    EvalCase,
    EvalReport,
    EvalResult,
    EvalRunSummary,
    EvalScore,
    MetricDelta,
    RegressionReport,
)

__all__ = [
    # types
    "EvalCase",
    "EvalScore",
    "EvalResult",
    "EvalReport",
    "EvalRunSummary",
    "MetricDelta",
    "RegressionReport",
    # runner / scorer
    "EvalRunner",
    "EvalScorer",
    # judge
    "LLMJudge",
    "TrustworthyMetrics",
    "get_judge",
    # dataset
    "load_dataset",
    "append_cases",
    # history / regression
    "save_run",
    "load_history",
    "latest_summary",
    "compare_runs",
    "DEFAULT_THRESHOLDS",
    # inference capture
    "InferenceRecord",
    "InferenceStore",
    "get_inference_store",
    "should_sample",
    # flywheel
    "CandidateRecord",
    "promote_to_candidate",
    "list_candidates",
    "promote_candidate_to_golden",
    "on_negative_feedback",
    "get_retrieval_misses",
]
