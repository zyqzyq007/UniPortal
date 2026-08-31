#!/usr/bin/env python3
"""
F-05 — prompt signature must cover the intent prompt.

Bug2 Layer ③ changes prompts['intent'], but api/main.py:84 and the
/api/prompt-status endpoint (chat.py:492) only hashed GENERATE_SYSTEM_PROMPT.
Changing the intent prompt left the signature unchanged, so ops/audit could
not detect intent-prompt drift (REQ-RG-016 ineffective).

The fix extends the signature to aggregate the generate + intent prompts.

Run: uv run --frozen python -m pytest tests/unit/test_prompt_signature.py -v
"""

from __future__ import annotations

import hashlib
import sys

import pytest

sys.path.insert(0, ".")


@pytest.fixture(autouse=True)
def _reset_profile():
    from core.prompts.domain_profile import reset_active_profile

    reset_active_profile()
    yield
    reset_active_profile()


class TestPromptSignatureCoversIntent:
    """[REQ-RG-016/F-05] The signature MUST change when the intent prompt changes."""

    def test_signature_aggregates_intent_prompt(self):
        """The prompt-status signature must hash both generate and intent
        prompts, so changing either is detectable."""
        from core.prompts.profile_prompts import (
            GENERATE_SYSTEM_PROMPT,
            INTENT_CLASSIFICATION_PROMPT,
            PER_DOC_GRADE_HUMAN_PROMPT,
            PER_DOC_GRADE_SYSTEM_PROMPT,
        )

        client = pytest.importorskip("fastapi.testclient").TestClient
        # Reuse the in-process app (the conftest client fixture disables the
        # reranker but the prompt-status endpoint is independent of retrieval).
        from api.main import app

        with client(app) as c:
            resp = c.get("/api/chat/prompt-status")
            assert resp.status_code == 200
            actual_sig = resp.json()["generate_prompt_signature"]

        # The expected signature aggregates generate + intent prompts.
        expected = hashlib.sha1(
            (
                GENERATE_SYSTEM_PROMPT
                + INTENT_CLASSIFICATION_PROMPT
                + PER_DOC_GRADE_SYSTEM_PROMPT
                + PER_DOC_GRADE_HUMAN_PROMPT
            ).encode("utf-8")
        ).hexdigest()[:12]
        assert actual_sig == expected, (
            "signature must aggregate generate + intent prompts (F-05); "
            f"got {actual_sig}, expected {expected}"
        )

    def test_intent_prompt_change_detected_by_signature(self, monkeypatch):
        """If the intent prompt text changes, the signature must change."""
        import api.routers.chat as chat_mod

        original = chat_mod.INTENT_CLASSIFICATION_PROMPT
        client = pytest.importorskip("fastapi.testclient").TestClient
        from api.main import app

        with client(app) as c:
            base_sig = c.get("/api/chat/prompt-status").json()["generate_prompt_signature"]

        # Mutate the intent prompt as seen by the endpoint (chat.py binds the
        # constant at import, so patch chat_mod's binding, not profile_prompts).
        monkeypatch.setattr(
            chat_mod,
            "INTENT_CLASSIFICATION_PROMPT",
            original + "\n# additional rule",
        )
        with client(app) as c:
            mutated_sig = c.get("/api/chat/prompt-status").json()["generate_prompt_signature"]

        assert base_sig != mutated_sig, "intent prompt change must alter the signature (F-05)"
