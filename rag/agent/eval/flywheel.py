"""
Feedback flywheel — closes the loop between production feedback and evaluation.

Triggered when a user submits negative feedback (thumbs_down / correction /
flag). It:

  1. Promotes the matching inference into the candidate pool
     (agent.eval.candidates) — the source of future golden cases.
  2. Re-evaluates the inference with the LLM-as-judge and records the quality
     score on the feedback row, so feedback can be triaged by severity.
  3. When the judge finds the answer unsupported by the retrieved context,
     logs a retrieval miss for offline tuning (the "lightweight self-tuning"
     half of the flywheel — no RL, just signal collection).

All steps are best-effort and isolated from the feedback write path: a
flywheel failure never blocks feedback submission.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any

from agent.eval.candidates import promote_to_candidate
from agent.eval.inference_store import InferenceRecord, get_inference_store
from agent.eval.judge import get_judge
from utils.log_utils import log

__all__ = [
    "on_negative_feedback",
    "get_retrieval_misses",
    "RETRIEVAL_MISSES_DB",
]

RETRIEVAL_MISSES_DB = "./data/eval/retrieval_misses.db"
_misses_lock = threading.Lock()


def _retrieval_misses_conn() -> sqlite3.Connection:
    import os

    os.makedirs(os.path.dirname(RETRIEVAL_MISSES_DB), exist_ok=True)
    conn = sqlite3.connect(RETRIEVAL_MISSES_DB, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS retrieval_misses (
            id           TEXT PRIMARY KEY,
            trace_id     TEXT,
            session_id   TEXT,
            query        TEXT,
            answer       TEXT,
            faithfulness REAL,
            context_precision REAL,
            feedback_type TEXT,
            created_at   REAL
        )
        """
    )
    conn.commit()
    return conn


def _record_retrieval_miss(
    inference: InferenceRecord,
    metrics,
    feedback_type: str,
) -> None:
    """Persist a retrieval-miss signal for offline tuning."""
    import uuid

    try:
        with _misses_lock:
            conn = _retrieval_misses_conn()
            conn.execute(
                """
                INSERT OR REPLACE INTO retrieval_misses
                (id, trace_id, session_id, query, answer,
                 faithfulness, context_precision, feedback_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    inference.trace_id,
                    inference.session_id,
                    inference.query,
                    inference.answer,
                    metrics.faithfulness,
                    metrics.context_precision,
                    feedback_type,
                    time.time(),
                ),
            )
            conn.commit()
            conn.close()
        log.info(
            f"Retrieval miss recorded: trace={inference.trace_id[:12]}... "
            f"faithfulness={metrics.faithfulness}"
        )
    except Exception as e:  # noqa: BLE001
        log.warning(f"Failed to record retrieval miss: {e}")


def get_retrieval_misses(limit: int = 100) -> list:
    """Read recent retrieval-miss signals (for offline tuning / dashboards)."""
    try:
        with _misses_lock:
            conn = _retrieval_misses_conn()
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM retrieval_misses ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            conn.close()
        return [dict(r) for r in rows]
    except Exception:  # noqa: BLE001
        return []


def on_negative_feedback(
    trace_id: str,
    message_id: str,
    feedback_type: str,
    corrected_answer: str = "",
) -> dict[str, Any]:
    """
    Flywheel entry point. Called after a negative-feedback row is written.

    Args:
        trace_id: the inference trace_id (joins to the inference store).
        message_id: fallback lookup key if trace_id is empty.
        feedback_type: thumbs_down | correction | flag
        corrected_answer: for corrections — becomes the golden answer.

    Returns a small summary dict (always populated, even on failure).
    """
    result: dict[str, Any] = {
        "promoted": False,
        "judge_run": False,
        "miss_recorded": False,
        "error": None,
    }
    try:
        store = get_inference_store()
        inference = store.get(trace_id) if trace_id else None
        if inference is None and message_id:
            inference = store.get_by_message(message_id)
        if inference is None:
            result["error"] = "no matching inference found"
            return result

        # 1. Promote to candidate pool.
        candidate = promote_to_candidate(
            inference=inference,
            feedback_type=feedback_type,
            corrected_answer=corrected_answer,
        )
        result["promoted"] = candidate is not None

        # 2. Re-evaluate with the judge (best-effort).
        contexts = [d.get("content", "") for d in inference.retrieved_docs if isinstance(d, dict)]
        judge = get_judge()
        metrics = None
        if judge.available and inference.answer.strip():
            metrics = judge.evaluate(
                question=inference.query,
                answer=inference.answer,
                contexts=contexts,
                reference_answer=corrected_answer,
            )
            result["judge_run"] = metrics.judge_used

            # 3. Retrieval miss: faithfulness low => context didn't support answer.
            if (
                metrics.judge_used
                and metrics.faithfulness is not None
                and metrics.faithfulness < 0.5
            ):
                _record_retrieval_miss(inference, metrics, feedback_type)
                result["miss_recorded"] = True

        return result
    except Exception as e:  # noqa: BLE001
        result["error"] = str(e)
        log.warning(f"Flywheel on_negative_feedback failed: {e}")
        return result
