#!/usr/bin/env python3
"""
Stage 3 audit bugfix tests — B9 (limit caps) + B10 (upload size).

B9: list/history endpoints accept an unbounded `limit` query param. A caller
can request ?limit=1e8 and force the server to load an unbounded number of
records into memory. The fix adds `le=` caps (FastAPI returns 422 on violation).

B10: the upload endpoint reads the entire file into memory with no size cap. A
multi-GB upload exhausts RAM. The fix checks size against MAX_UPLOAD_BYTES and
returns 413.

Run: uv run --frozen python -m pytest tests/unit/test_audit_stage3_limits_upload.py -v
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")


# ---------------------------------------------------------------------------
# B9 — limit is capped
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/api/chat/history/any-session?limit=100000",
        "/api/sessions?limit=100000",
        "/api/admin/eval/runs?limit=100000",
        "/api/admin/retrieval-misses?limit=100000",
        "/api/documents?limit=100000",
    ],
)
def test_b9_limit_rejects_huge_value(client, path):
    """An absurdly large limit MUST be rejected with 422 (Pydantic validation)
    rather than accepted and materialized into memory."""
    resp = client.get(path)
    assert resp.status_code == 422, (
        f"{path} -> {resp.status_code}, expected 422 (limit cap missing)"
    )


def test_b9_limit_accepts_in_range(client):
    """A reasonable limit MUST still work (not 422)."""
    resp = client.get("/api/sessions?limit=50")
    assert resp.status_code != 422, f"limit=50 rejected with 422: {resp.status_code}"


# ---------------------------------------------------------------------------
# B10 — upload rejects oversize files
# ---------------------------------------------------------------------------


def test_b10_upload_rejects_oversize(client, monkeypatch):
    """An upload exceeding MAX_UPLOAD_BYTES MUST return 413 without reading
    the whole body into memory."""
    import api.routers.documents as docs_mod

    monkeypatch.setattr(docs_mod, "MAX_UPLOAD_BYTES", 100)

    # A fake UploadFile carrying a size claim over the cap (never actually read).
    class _FakeFile:
        filename = "big.txt"
        size = 10_000  # claimed size >> cap (100)

        async def read(self):
            return b"x" * 10_000

        async def close(self):
            pass

    resp = client.post(
        "/api/documents/upload",
        files={"file": ("big.txt", b"x" * 10_000, "text/plain")},
    )
    assert resp.status_code == 413, (
        f"oversize upload -> {resp.status_code}, expected 413; body={resp.text[:200]}"
    )


def test_b10_upload_accepts_small(client):
    """A small upload MUST still succeed (not 413)."""
    content = "# small\na tiny doc\n"
    resp = client.post(
        "/api/documents/upload",
        files={"file": ("small.md", content.encode(), "text/markdown")},
    )
    assert resp.status_code != 413, f"small upload rejected with 413: {resp.status_code}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
