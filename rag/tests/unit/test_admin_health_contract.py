#!/usr/bin/env python3
"""
Reranker 健康状态契约测试 — 固化 ready/cold 下顶层 status == "healthy"。

背景（bug1）: 系统管理页 reranker 卡片在 ready/cold(模型未加载进内存)时
渲染叉号,但顶部徽章显示「正常」,产生「绿√ + 红✗」矛盾。根因是后端
``api/routers/admin.py:138-140`` 的 ``all_healthy`` 把 ready/cold 视为正常
(顶层 status="healthy"),而前端图标逻辑把 ready/cold 当故障。本测试固化
后端契约,确保 ready/cold 的顶层 status 始终为 "healthy",防止未来误改。

Run: pytest tests/unit/test_admin_health_contract.py -q
"""

from __future__ import annotations

import sys
from typing import Literal

import pytest

sys.path.insert(0, ".")


def _reranker_status_payload(*, loaded: bool, load_error: str | None, cached: bool) -> dict:
    """Build a Reranker.status()-shaped dict for the given readiness state."""
    load_attempted = load_error is not None or loaded
    return {
        "model": "bge-reranker-v2-m3",
        "model_source": "BAAI/bge-reranker-v2-m3",
        "device": "cpu",
        "cached": cached,
        "load_attempted": load_attempted,
        "loaded": loaded,
        "degraded": (not loaded) and load_attempted and load_error is not None,
        "load_error": load_error,
    }


class _FakeReranker:
    """Minimal stand-in returning a fixed status() payload."""

    def __init__(self, status_payload: dict):
        self._payload = status_payload

    def status(self) -> dict:
        return self._payload


def _install_reranker(monkeypatch, payload: dict) -> None:
    """Patch the admin health path so RERANKER_ENABLED + get_reranker reflect ``payload``."""
    monkeypatch.setattr("utils.env_utils.RERANKER_ENABLED", True)
    fake = _FakeReranker(payload)

    # admin.py imports get_reranker lazily inside the handler
    import core.retrieval.reranker as reranker_mod

    monkeypatch.setattr(reranker_mod, "get_reranker", lambda: fake)


@pytest.fixture
def health_client(client, monkeypatch):
    """Reuse the sealed in-process client (RERANKER_ENABLED off by default)."""

    class _HealthyMilvus:
        def __init__(self):
            self.closed = False

        def health_check(self):
            return {
                "connected": True,
                "embedding_compatible": True,
                "embedding_compatibility": {
                    "compatible": True,
                    "reason": "compatible",
                },
            }

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        "documents.milvus_db.get_milvus_manager",
        lambda: _HealthyMilvus(),
    )
    return client


@pytest.mark.parametrize(
    "state, payload",
    [
        (
            "ready",
            _reranker_status_payload(loaded=False, load_error=None, cached=True),
        ),
        (
            "cold",
            _reranker_status_payload(loaded=False, load_error=None, cached=False),
        ),
        (
            "healthy",
            _reranker_status_payload(loaded=True, load_error=None, cached=True),
        ),
    ],
)
def test_reranker_transient_states_top_level_status_is_healthy(
    health_client, monkeypatch, state, payload
):
    """[REQ-RS-006] ready/cold/healthy 下顶层 ``status`` MUST 为 ``"healthy"``。

    顶层 all_healthy 集合为 ("healthy","degraded","ready","cold"),故 ready/cold
    不得拉低整体状态——否则前端顶部徽章与卡片图标再次产生矛盾。
    """
    _install_reranker(monkeypatch, payload)

    resp = health_client.get("/api/admin/health")
    assert resp.status_code == 200
    body = resp.json()

    assert body["status"] == "healthy", (
        f"reranker={state}: top-level status must be 'healthy', got {body['status']!r}"
    )
    assert body["services"]["reranker"]["status"] == state, (
        f"reranker service status must be {state!r}, got {body['services']['reranker']['status']!r}"
    )


def test_reranker_degraded_does_not_lower_top_level_status(health_client, monkeypatch):
    """degraded(load 失败,降级运行)MUST NOT 使顶层 status 降为 ``"degraded"``。

    后端 ``all_healthy`` 集合为 ("healthy","degraded","ready","cold"):degraded
    表示「降级但仍可用」(reranker 挂了回退 RRF 顺序,检索仍工作),与 unhealthy
    (服务不可用)语义不同。故 degraded 与 ready/cold 一样不计入顶层降级。
    仅 unhealthy 才拉低顶层(见 milvus 断开场景)。
    """
    payload = _reranker_status_payload(loaded=False, load_error="cuda init failed", cached=True)
    _install_reranker(monkeypatch, payload)

    resp = health_client.get("/api/admin/health")
    body = resp.json()

    assert body["services"]["reranker"]["status"] == "degraded"
    # degraded is in the all_healthy set, so top-level stays "healthy".
    assert body["status"] == "healthy"


def test_embedding_incompatibility_degrades_health_and_exposes_fingerprint(
    health_client, monkeypatch
):
    class _IncompatibleMilvus:
        def health_check(self):
            return {
                "connected": True,
                "embedding_compatible": False,
                "embedding_compatibility": {
                    "compatible": False,
                    "reason": "model_mismatch",
                },
            }

        def close(self):
            pass

    monkeypatch.setattr(
        "documents.milvus_db.get_milvus_manager",
        lambda: _IncompatibleMilvus(),
    )

    response = health_client.get("/api/admin/health")
    body = response.json()
    assert body["status"] == "degraded"
    assert body["services"]["milvus"]["status"] == "degraded"
    assert set(body["runtime_config"]) == {"schema_version", "fingerprint"}
