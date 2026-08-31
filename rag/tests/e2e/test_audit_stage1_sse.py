#!/usr/bin/env python3
"""
Stage 1 audit bugfix test — B3 (SSE/stream error leaks internal exception text).

The streaming endpoint's ``except Exception as e: yield _sse({"type":"error",
"message": str(e)})`` forwards the raw exception message to the client. That
message can contain internal paths, DB connection strings, or stack internals.
The fix returns a generic message to the client and logs the detail server-side.

This test forces a failure inside the stream generator (by patching the harness
to raise) and asserts the client-visible error frame does NOT contain the
leaked internal string.

Run: uv run --frozen python -m pytest tests/e2e/test_audit_stage1_sse.py -v
"""

from __future__ import annotations

import json
import sys

import pytest

sys.path.insert(0, ".")

# A secret-like string the raw exception would carry but the client must NOT see.
INTERNAL_LEAK = "/data/secrets/agent_memory.db::admin_token=abc123"


def _read_stream(client, body: dict):
    """Open the stream endpoint and collect all SSE frames."""
    with client.stream("POST", "/api/chat/stream", json=body) as resp:
        assert resp.status_code == 200
        raw = b""
        for chunk in resp.iter_bytes():
            raw += chunk
    # Parse `data: {...}` lines.
    frames = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("data:"):
            try:
                frames.append(json.loads(line[len("data:") :].strip()))
            except Exception:  # noqa: BLE001
                pass
    return frames


def test_b3_stream_error_does_not_leak_internal_text(client, monkeypatch):
    """When the harness stream raises mid-generation, the SSE error frame MUST
    use a generic message and MUST NOT echo the raw exception text."""
    import agent.harness as harness_mod

    class _ExplodingHarness:
        async def astart(self):
            return self

        async def aclose(self):
            pass

        async def astream(self, *a, **k):
            raise RuntimeError(f"internal detail: {INTERNAL_LEAK}")
            yield ""  # noqa: B901 — make this a legal async generator body

    monkeypatch.setattr(harness_mod, "get_agent_harness", lambda *a, **k: _ExplodingHarness())

    body = {
        "message": "git 合并冲突如何解决？",
        "mode": "thinking",
        "stream": True,
    }
    frames = _read_stream(client, body)

    error_frames = [f for f in frames if f.get("type") == "error"]
    assert error_frames, f"no error frame emitted; frames={frames}"
    msg = error_frames[0].get("message", "")
    assert INTERNAL_LEAK not in msg, f"SSE error frame leaked internal exception text:\n{msg!r}"
    # And the generic message should be present (non-empty, not the raw str(e)).
    assert msg and "internal detail" not in msg, (
        f"error message is still the raw exception: {msg!r}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
