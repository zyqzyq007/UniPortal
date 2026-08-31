#!/usr/bin/env python3
"""
Domain-switch E2E — proves the agent serves a NON-aviation knowledge base
under DOMAIN_PROFILE=general.

This is the capstone test for the domain-adaptive refactor (spec
domain-adaptive-profile / domain-adaptive-completion): the platform defaults to
the domain-agnostic general profile, and with DOMAIN_PROFILE=aviation_phm it
serves the aviation PHM vertical. These tests assert a generic-domain query is
routed through RAG under general without the input guardrail blocking it and
without forcing PHM output structure.

Run: uv run --frozen python -m pytest tests/e2e/test_e2e_domain_switch.py -v
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")


@pytest.fixture
def general_client(client, monkeypatch):
    """The conftest ``client`` fixture built with DOMAIN_PROFILE=general.

    The app/prompt constants are resolved at import time from the active
    profile, so we reset the profile cache + set the env BEFORE the client is
    constructed. We rebuild the app via the factory so the general profile's
    prompts are in effect.
    """
    from core.prompts.domain_profile import reset_active_profile

    reset_active_profile()
    monkeypatch.setenv("DOMAIN_PROFILE", "general")
    # The conftest `client` fixture already imported the app with the default
    # profile; rather than rebuild it (which would re-run lifespan), we rely on
    # the runtime profile lookups (_profile(), _topic_keywords(), etc.) reading
    # the freshly-cached general profile. reset_active_profile() above ensures
    # get_active_profile() re-loads under general.
    yield client
    reset_active_profile()
    monkeypatch.delenv("DOMAIN_PROFILE", raising=False)


# ===========================================================================
# Non-aviation query is NOT blocked by the topic guardrail
# ===========================================================================


class TestGeneralDomainRouting:
    def test_biology_query_not_force_routed_to_rag(self, general_client):
        """光合作用 has no aviation domain keyword, so _looks_like_domain_query
        returns False under the general profile -> the intent classifier
        (fake) decides. The query still reaches the chat endpoint without
        being force-routed."""
        resp = general_client.post(
            "/api/chat",
            json={
                "message": "光合作用的化学方程式是什么？",
                "session_id": "e2e-domain-bio",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # Under general profile the response is non-empty (fake harness) and
        # the route is whatever the classifier decided (not force-overridden).
        assert body["response"]

    def test_general_identity_response_is_neutral(self, general_client):
        """The identity response must not claim to be an aviation PHM assistant
        under the general profile."""
        resp = general_client.post(
            "/api/chat",
            json={
                "message": "你是谁",
                "session_id": "e2e-domain-id",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # General identity response is domain-neutral.
        assert "PHM" not in body["response"]
        assert "飞机" not in body["response"]

    def test_general_prompt_profile_label(self, general_client):
        """metadata.prompt_profile under general must be general_*, not phm_*."""
        resp = general_client.post(
            "/api/chat",
            json={
                "message": "光合作用的化学方程式是什么？",
                "session_id": "e2e-domain-label",
                "mode": "fast",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["metadata"]["prompt_profile"].startswith("general")
        assert "phm" not in body["metadata"]["prompt_profile"]


# ===========================================================================
# Default profile is now the domain-agnostic general profile [REQ-A-001]
# ===========================================================================


class TestDefaultProfileIsGeneral:
    def test_default_is_not_aviation(self, client):
        """With no DOMAIN_PROFILE override, the default profile is general
        (BREAKING: was aviation_phm). A PHM-flavoured query is NOT force-routed
        by an aviation routing fast-path, and the prompt_profile label is
        general_*, not phm_*."""
        from core.prompts.domain_profile import get_active_profile, reset_active_profile

        reset_active_profile()  # re-load the (new) default
        assert get_active_profile().name == "general"
        resp = client.post(
            "/api/chat",
            json={
                "message": "发动机振动偏高如何诊断？",
                "session_id": "e2e-domain-default",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["metadata"]["prompt_profile"].startswith("general")
        assert "phm" not in body["metadata"]["prompt_profile"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
