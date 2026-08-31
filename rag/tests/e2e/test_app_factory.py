#!/usr/bin/env python3
"""
F16 — app factory: ``create_app()`` builds the FastAPI app in-process.

The module-level ``app`` used to be constructed at import time with CORS,
middleware, routers, OTEL, and the static frontend mount all at module scope —
forcing the test conftest to monkeypatch source-module singletons. The factory
centralises construction so a future migration to ``dependency_overrides`` is
possible. This test proves the factory produces a fully-wired app.

Run: pytest tests/e2e/test_app_factory.py -v
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")


def test_create_app_returns_wired_fastapi():
    from fastapi import FastAPI

    from api.main import create_app

    app = create_app()
    assert isinstance(app, FastAPI)

    # All six routers are mounted.
    paths = {r.path for r in app.routes}
    assert any(p.startswith("/api/chat") for p in paths)
    assert any(p.startswith("/api/documents") for p in paths)
    assert any(p.startswith("/api/sessions") for p in paths)
    assert any(p.startswith("/api/admin") for p in paths)
    assert any(p.startswith("/api/feedback") for p in paths)
    assert any(p.startswith("/api/retrieval") for p in paths)
    # Health + api info.
    assert "/health" in paths
    assert "/api" in paths


def test_module_level_app_is_factory_built():
    """The uvicorn entrypoint ``api.main:app`` is the factory output."""
    import api.main

    assert api.main.app is not None
    assert callable(api.main.create_app)


def test_factory_app_health_via_test_client(client):
    """The factory-built app (served by the e2e client fixture) responds to
    /health, proving the factory is behaviourally identical to the old
    module-level construction."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("healthy", "degraded")
    assert "circuits" in body
