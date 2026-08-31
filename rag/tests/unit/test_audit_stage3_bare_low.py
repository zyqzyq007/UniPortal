#!/usr/bin/env python3
"""
Stage 3 audit bugfix tests — B11 (bare-filename db crash) + B12 (Low sweep).

B11: InferenceStore / EmbeddingRegistry do `os.makedirs(os.path.dirname(db_path))`
with no `or "."` guard. A bare filename (dirname == "") crashes with
FileNotFoundError. Sibling stores (graph_store, parent_store, document_registry)
all guard this; these two were missed.

B12 (Low): (a) hallucination_score rationale uses len(hard_claims) as denominator
instead of `judged` (the actual score denominator); (b) graph fingerprint-drift
sets fingerprint_ok=False but not degraded=True (admin health misses it);
(c) get_feedback_collector singleton init is not locked (concurrent first
requests can create two instances).

Run: uv run --frozen python -m pytest tests/unit/test_audit_stage3_bare_low.py -v
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, ".")


# ---------------------------------------------------------------------------
# B11 — bare-filename db_path does not crash
# ---------------------------------------------------------------------------


def test_b11_inference_store_bare_filename(tmp_path, monkeypatch):
    """InferenceStore constructed with a bare filename MUST NOT crash."""
    monkeypatch.chdir(tmp_path)
    from agent.eval.inference_store import InferenceStore

    store = InferenceStore("myreg.db")  # bare filename, no directory component
    store.close()
    assert (tmp_path / "myreg.db").exists()


def test_b11_embedding_registry_bare_filename(tmp_path, monkeypatch):
    """EmbeddingRegistry constructed with a bare filename MUST NOT crash."""
    monkeypatch.chdir(tmp_path)
    from documents.embedding_registry import EmbeddingRegistry

    reg = EmbeddingRegistry("embreg.db")
    reg.close()
    assert (tmp_path / "embreg.db").exists()


# ---------------------------------------------------------------------------
# B12(a) — hallucination rationale denominator
# ---------------------------------------------------------------------------


def test_b12_hallucination_rationale_uses_judged_denominator(monkeypatch):
    """When some claims cannot be judged, the rationale MUST report X/judged
    (matching the score), not X/len(hard_claims)."""
    from agent.eval import judge as judge_mod
    from agent.eval.judge import LLMJudge

    judge = LLMJudge.__new__(LLMJudge)  # bypass __init__ (no LLM needed)

    # Control the claim set: 3 hard claims, then stub _entail to make the 3rd
    # unavailable (judged=2, unsupported=1 -> score 0.5; rationale must say 1/2).
    claims = ["claim-one", "claim-two", "claim-three-unavailable"]
    monkeypatch.setattr(judge_mod, "split_claims", lambda _answer: claims)
    monkeypatch.setattr(judge_mod, "is_hard_claim", lambda _c: True)

    verdicts = [
        type("V", (), {"supported": True})(),
        type("V", (), {"supported": False})(),
        None,  # unavailable
    ]
    call = {"i": 0}

    def _fake_entail(claim, context):
        v = verdicts[call["i"]]
        call["i"] += 1
        return v

    monkeypatch.setattr(judge, "_entail", _fake_entail)

    score, rationale = judge.hallucination_score("answer text", ["ctx"])

    # judged=2, unsupported=1 -> score=0.5; rationale must say 1/2 (not 1/3).
    assert score == pytest.approx(0.5)
    assert "1/2" in rationale, f"rationale should use judged(2) denominator: {rationale!r}"
    assert "1/3" not in rationale, f"rationale used len(hard_claims)(3): {rationale!r}"


# ---------------------------------------------------------------------------
# B12(b) — graph fingerprint-drift sets degraded
# ---------------------------------------------------------------------------


def test_b12_graph_fingerprint_drift_sets_degraded(monkeypatch, tmp_path):
    """On embedding dimension mismatch (model drift), the graph leg MUST set
    degraded=True (not just fingerprint_ok=False) so admin health surfaces it."""
    from core.retrieval.graph_retriever import GraphRetriever
    from documents.graph_store import GraphRow

    # A fake store whose load_all returns a row with a mismatched embedding dim.
    rows = [
        GraphRow(
            entity_id="e1",
            name="pump",
            type="component",
            source="s",
            parent_id="",
            chunk_text="",
            embedding=[0.1] * 16,  # wrong dim
        ),
    ]

    class _FakeStore:
        def load_all(self):
            return rows

    gr = GraphRetriever(store=_FakeStore())
    # _expected_dim returns the configured embedding dim (8 via env/profile);
    # force it so the row's 16-dim vector triggers the mismatch branch.
    monkeypatch.setattr(gr, "_expected_dim", lambda: 8)

    with gr._lock:
        gr._build_matrix_locked()

    assert gr._fingerprint_ok is False, "fingerprint_ok should be False on drift"
    assert getattr(gr, "_degraded", False) is True, (
        "degraded must be True on fingerprint drift so admin health surfaces it"
    )


# ---------------------------------------------------------------------------
# B12(c) — feedback collector singleton init is locked
# ---------------------------------------------------------------------------


def test_b12_feedback_collector_singleton_locked():
    """get_feedback_collector MUST use a lock at init (double-checked locking)
    so concurrent first calls don't create two instances (connection leak)."""
    import inspect

    from agent.feedback import collector as fc_mod

    # The module must expose a dedicated lock for singleton init.
    assert hasattr(fc_mod, "_collector_lock"), (
        "feedback collector missing a module-level init lock (_collector_lock)"
    )
    # And get_feedback_collector must reference the lock (defence-in-depth contract).
    src = inspect.getsource(fc_mod.get_feedback_collector)
    assert "_collector_lock" in src, (
        "get_feedback_collector does not acquire _collector_lock; concurrent init "
        "can create two FeedbackCollector instances (sqlite connection leak)"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
