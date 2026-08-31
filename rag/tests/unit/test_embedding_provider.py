"""Unit tests for the embedding provider dispatch (api-only-deploy).

Covers REQ-AO-001 / 010 / 011 and findings F-02 (empty-key fail-fast),
F-05 (live-env resolve + singleton isolation), plus the local-mode no-regression
guarantee.
"""

from __future__ import annotations

import pytest

import models.embedding_models as emb_mod
from models.embedding_models import (
    _resolve_provider,
    get_embeddings,
    get_local_embeddings,
    reset_embeddings,
)


@pytest.fixture(autouse=True)
def _isolate_singleton(monkeypatch):
    """F-05: ensure the unified singleton never leaks across tests."""
    monkeypatch.setenv("MILVUS_SPARSE_INDEX", "false")
    reset_embeddings()
    yield
    reset_embeddings()


# ---------------------------------------------------------------------------
# _resolve_provider — live env, validated (F-05)
# ---------------------------------------------------------------------------


class TestResolveProvider:
    def test_explicit_api(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "api")
        assert _resolve_provider() == "api"

    def test_explicit_local(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
        assert _resolve_provider() == "local"

    def test_case_insensitive_and_trimmed(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "  API  ")
        assert _resolve_provider() == "api"

    def test_invalid_value_raises(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "ollama")
        with pytest.raises(ValueError, match="auto|local|api"):
            _resolve_provider()

    def test_auto_with_torch_resolves_local(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "auto")
        monkeypatch.setattr(emb_mod, "_torch_available", lambda: True)
        assert _resolve_provider() == "local"

    def test_auto_without_torch_resolves_api(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "auto")
        monkeypatch.setattr(emb_mod, "_torch_available", lambda: False)
        assert _resolve_provider() == "api"


# ---------------------------------------------------------------------------
# Empty-key fail-fast (F-02)
# ---------------------------------------------------------------------------


class TestEmptyKeyFailFast:
    def test_api_provider_empty_key_raises_with_migration_hint(self, monkeypatch):
        """F-02: a bare `uv sync` (no torch) auto-resolves to api; an empty key
        must raise immediately with an actionable message, not at HTTP 401.

        Reads config live from os.getenv (F-05), so setenv drives the behaviour."""
        monkeypatch.setenv("EMBEDDING_PROVIDER", "api")
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        with pytest.raises(RuntimeError) as exc_info:
            get_embeddings()
        message = str(exc_info.value)
        assert "DASHSCOPE_API_KEY" in message
        assert "local-models" in message  # migration guidance
        assert "EMBEDDING_PROVIDER=local" in message


# ---------------------------------------------------------------------------
# Provider switching via setenv + reset (F-05)
# ---------------------------------------------------------------------------


class TestProviderSwitch:
    def test_setenv_takes_effect_after_reset(self, monkeypatch):
        """F-05: switching provider requires only setenv + reset_embeddings
        (no setattr on the module constant) thanks to live os.getenv reads."""
        # First call: stubbed to api → builds a fake api instance.
        monkeypatch.setenv("EMBEDDING_PROVIDER", "api")
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-1")
        instance_a = get_embeddings()
        assert type(instance_a).__name__ == "DashScopeEmbeddings"

        # Switch to local without resetting: stale singleton returned.
        monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
        assert get_embeddings() is instance_a  # still cached

        # Reset clears the singleton; next call honours the new env.
        reset_embeddings()
        # Stub the local constructor so we don't load real torch weights here.
        sentinel = object()
        monkeypatch.setattr(emb_mod, "_get_local_embeddings", lambda: sentinel)
        instance_b = get_embeddings()
        assert instance_b is sentinel

    def test_singleton_cached_within_same_provider(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "api")
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-x")
        a = get_embeddings()
        b = get_embeddings()
        assert a is b


# ---------------------------------------------------------------------------
# get_local_embeddings alias (PM-08)
# ---------------------------------------------------------------------------


class TestAlias:
    def test_alias_dispatches_to_api(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "api")
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-alias")
        instance = get_local_embeddings()
        assert type(instance).__name__ == "DashScopeEmbeddings"


# ---------------------------------------------------------------------------
# Local-mode no-regression (REQ-AO-010) — guarded by torch availability
# ---------------------------------------------------------------------------


class TestLocalNoRegression:
    def test_local_provider_routes_to_local_constructor(self, monkeypatch):
        """REQ-AO-010: explicit local still hits the HuggingFace path."""
        monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
        sentinel = object()
        monkeypatch.setattr(emb_mod, "_get_local_embeddings", lambda: sentinel)
        assert get_embeddings() is sentinel

    def test_explicit_local_missing_torch_raises_clear_message(self, monkeypatch):
        """REQ-AO-010 / F-02 mirror: local + missing extra → actionable error."""
        monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
        # Force the inner HuggingFaceEmbeddings import to fail as if the extra
        # were absent.
        import sys

        monkeypatch.setitem(sys.modules, "langchain_huggingface", None)
        with pytest.raises(ImportError) as exc_info:
            get_embeddings()
        assert "local-models" in str(exc_info.value)
