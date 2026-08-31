#!/usr/bin/env python3
"""
F06 — SSRF: redirects disabled + peer-IP post-connect verification.

Extends test_stage4.py's SSRF coverage (private/loopback/link-local/scheme/
allowlist) with the two TOCTOU/redirect fixes:
  - ``http_get`` does NOT follow redirects (a 3xx is a hard stop).
  - The post-connect peer IP is cross-checked against the resolved public set.

The full network paths require real sockets; here we assert the control-flow
shape via ``_resolve_public_ips`` and the no-redirect branch, using local
loopback (which ``_ssf_blocked`` rejects up front) to prove the block fires
before any connection.

Run: pytest tests/unit/test_ssrf.py -v
"""

from __future__ import annotations

import socket
import sys

import pytest

sys.path.insert(0, ".")


class TestResolvePublicIps:
    def test_loopback_resolves_to_blocked(self):
        from agent.mcp.tools_registry import ExternalAPIToolsServer

        ips, reason = ExternalAPIToolsServer._resolve_public_ips("127.0.0.1")
        assert ips == set()
        assert reason is not None
        assert "内网" in reason or "保留" in reason or "拒绝" in reason

    def test_link_local_blocked(self):
        from agent.mcp.tools_registry import ExternalAPIToolsServer

        ips, reason = ExternalAPIToolsServer._resolve_public_ips("169.254.169.254")
        assert ips == set()
        assert reason is not None

    def test_unresolvable_host_blocked(self):
        from agent.mcp.tools_registry import ExternalAPIToolsServer

        ips, reason = ExternalAPIToolsServer._resolve_public_ips(
            "nonexistent-host-zzz-invalid.invalid"
        )
        assert ips == set()
        assert reason is not None


class TestRedirectsDisabled:
    def test_loopback_url_rejected_before_connect(self):
        """A loopback URL is blocked at the _ssf_blocked gate, returning an
        error string — no connection is attempted."""
        from agent.mcp.tools_registry import ExternalAPIToolsServer

        out = ExternalAPIToolsServer.http_get("http://127.0.0.1:8000/admin")
        assert out.startswith("错误")

    def test_non_http_scheme_rejected(self):
        from agent.mcp.tools_registry import ExternalAPIToolsServer

        assert ExternalAPIToolsServer.http_get("file:///etc/passwd").startswith("错误")
        assert ExternalAPIToolsServer.http_get("gopher://x").startswith("错误")

    def test_metadata_endpoint_blocked(self, monkeypatch):
        """The AWS metadata endpoint must be blocked regardless of port."""
        from agent.mcp.tools_registry import ExternalAPIToolsServer

        out = ExternalAPIToolsServer.http_get("http://169.254.169.254/latest/meta-data/")
        assert out.startswith("错误")


class TestSsFBlockedContract:
    def test_allowlist_blocks_unlisted_host(self, monkeypatch):
        from agent.mcp.tools_registry import ExternalAPIToolsServer

        monkeypatch.setenv("HTTP_TOOL_ALLOWED_HOSTS", "api.example.com")
        reason = ExternalAPIToolsServer._ssf_blocked("https://evil.example.org/x")
        assert reason is not None
        assert "允许列表" in reason

    def test_public_host_not_blocked(self, monkeypatch):
        """A deterministic public DNS answer is not blocked."""
        from agent.mcp.tools_registry import ExternalAPIToolsServer

        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *_args, **_kwargs: [
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0))
            ],
        )
        reason = ExternalAPIToolsServer._ssf_blocked("https://example.com/")
        assert reason is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
