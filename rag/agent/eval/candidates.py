"""
Candidate pool promotion — the feedback flywheel's first step.

When a user flags a response (thumbs_down / correction / flag), the matching
inference is promoted from the inference store into the candidate pool under
``data/eval/candidates/``. A candidate is a proto-EvalCase awaiting review:

  - For corrections, ``corrected_answer`` becomes the golden reference_answer
    directly (zero-cost golden data).
  - For thumbs_down / flag, the original answer + retrieved contexts are kept
    so an annotator can decide the expected behaviour.

Candidates are then curated into ``golden.yaml`` via the CLI (or the
``promote_candidate`` helper here).
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from agent.eval.dataset import append_cases
from agent.eval.inference_store import InferenceRecord
from agent.eval.types import EvalCase
from utils.log_utils import log

__all__ = [
    "CANDIDATES_DIR",
    "promote_to_candidate",
    "list_candidates",
    "load_candidate",
    "promote_candidate_to_golden",
    "CandidateRecord",
]

CANDIDATES_DIR = Path("data/eval/candidates")


class CandidateRecord:
    """A candidate awaiting golden-dataset promotion."""

    def __init__(
        self,
        candidate_id: str,
        trace_id: str,
        message_id: str,
        session_id: str,
        query: str,
        answer: str,
        retrieved_docs: list[dict[str, Any]],
        feedback_type: str,
        corrected_answer: str = "",
        source: str = "feedback",
        created_at: float | None = None,
    ):
        self.candidate_id = candidate_id
        self.trace_id = trace_id
        self.message_id = message_id
        self.session_id = session_id
        self.query = query
        self.answer = answer
        self.retrieved_docs = retrieved_docs
        self.feedback_type = feedback_type
        self.corrected_answer = corrected_answer
        self.source = source
        self.created_at = created_at or time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "trace_id": self.trace_id,
            "message_id": self.message_id,
            "session_id": self.session_id,
            "query": self.query,
            "answer": self.answer,
            "retrieved_docs": self.retrieved_docs,
            "feedback_type": self.feedback_type,
            "corrected_answer": self.corrected_answer,
            "source": self.source,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CandidateRecord:
        return cls(
            candidate_id=d.get("candidate_id", ""),
            trace_id=d.get("trace_id", ""),
            message_id=d.get("message_id", ""),
            session_id=d.get("session_id", ""),
            query=d.get("query", ""),
            answer=d.get("answer", ""),
            retrieved_docs=d.get("retrieved_docs", []),
            feedback_type=d.get("feedback_type", ""),
            corrected_answer=d.get("corrected_answer", ""),
            source=d.get("source", "feedback"),
            created_at=d.get("created_at"),
        )

    def to_eval_case(self, case_id: str = "") -> EvalCase:
        """Convert into an EvalCase ready for the golden dataset."""
        # Corrections give us a free golden answer; otherwise the answer is
        # empty until an annotator fills it in.
        ref = self.corrected_answer.strip()
        return EvalCase(
            id=case_id or f"fb_{self.candidate_id}",
            query=self.query,
            reference_answer=ref,
            expected_intent="rag_query",
            expected_min_sources=1 if self.retrieved_docs else 0,
            tags=[self.feedback_type, self.source],
            source=self.source,
        )


def promote_to_candidate(
    inference: InferenceRecord,
    feedback_type: str,
    corrected_answer: str = "",
    source: str = "feedback",
) -> CandidateRecord | None:
    """
    Persist an inference as a candidate in the candidate pool.

    Returns the CandidateRecord, or None if the inference has no query.
    """
    if not inference or not inference.query.strip():
        return None

    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    candidate_id = uuid.uuid4().hex[:12]
    rec = CandidateRecord(
        candidate_id=candidate_id,
        trace_id=inference.trace_id,
        message_id=inference.message_id,
        session_id=inference.session_id,
        query=inference.query,
        answer=inference.answer,
        retrieved_docs=inference.retrieved_docs,
        feedback_type=feedback_type,
        corrected_answer=corrected_answer,
        source=source,
    )
    path = CANDIDATES_DIR / f"{candidate_id}.json"
    path.write_text(
        json.dumps(rec.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info(
        f"Candidate promoted: {candidate_id} (feedback={feedback_type}, "
        f"trace={inference.trace_id[:12]}...)"
    )
    return rec


def list_candidates() -> list[CandidateRecord]:
    """List all candidates in the pool, oldest first."""
    if not CANDIDATES_DIR.exists():
        return []
    out: list[CandidateRecord] = []
    for p in sorted(CANDIDATES_DIR.glob("*.json")):
        try:
            out.append(CandidateRecord.from_dict(json.loads(p.read_text(encoding="utf-8"))))
        except Exception:  # noqa: BLE001
            continue
    return out


def load_candidate(candidate_id: str) -> CandidateRecord | None:
    path = CANDIDATES_DIR / f"{candidate_id}.json"
    if not path.exists():
        return None
    try:
        return CandidateRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return None


def promote_candidate_to_golden(
    candidate_id: str,
    dataset_path: str = "data/eval/golden.yaml",
    case_id: str = "",
    reference_answer_override: str | None = None,
    delete_candidate: bool = True,
) -> EvalCase | None:
    """
    Promote a reviewed candidate into the golden dataset.

    Args:
        candidate_id: candidate to promote.
        dataset_path: target golden dataset file.
        case_id: explicit eval-case id (defaults to ``fb_<candidate_id>``).
        reference_answer_override: optional manual golden answer; otherwise
            the candidate's corrected_answer is used.
        delete_candidate: remove the candidate file after promotion.

    Returns the promoted EvalCase, or None if the candidate was not found.
    """
    candidate = load_candidate(candidate_id)
    if candidate is None:
        return None

    case = candidate.to_eval_case(case_id=case_id)
    if reference_answer_override is not None and reference_answer_override.strip():
        case.reference_answer = reference_answer_override.strip()

    # Only promote if there is a usable reference answer.
    if not case.reference_answer.strip():
        log.warning(
            f"Candidate {candidate_id} has no reference answer; "
            "set reference_answer_override or a corrected_answer first."
        )
        return None

    n = append_cases(dataset_path, [case])
    if n == 0:
        log.info(f"Candidate {candidate_id} already in dataset (id={case.id}).")
    else:
        log.info(f"Candidate {candidate_id} promoted to {dataset_path} as {case.id}.")

    if delete_candidate:
        path = CANDIDATES_DIR / f"{candidate_id}.json"
        if path.exists():
            path.unlink()
    return case
