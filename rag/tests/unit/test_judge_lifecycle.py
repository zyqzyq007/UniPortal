#!/usr/bin/env python3
"""
F-judge — LLMJudge SQLite verdict-cache connection lifecycle guard.

The LLMJudge singleton (agent.eval.judge.get_judge) opens a SQLite connection
for its verdict cache. Previously this connection was never closed — not on app
shutdown, not in test teardown — so it leaked until interpreter exit, surfacing
as ``ResourceWarning: unclosed database`` across many tests (the pyproject
filterwarnings had to be relaxed to "default" to mask it).

These tests pin the three parts of the fix:

1. ``DEFAULT_JUDGE_CACHE_PATH`` is a module-level attribute so tests/conftest.py
   can redirect it to tmp_path (AGENTS.md §6/§10 persistence contract).
2. ``_VerdictCache.close()`` is idempotent and actually closes the connection.
3. ``reset_judge()`` closes the singleton's cache connection (used by the
   api/main.py lifespan on shutdown).

Run: pytest tests/unit/test_judge_lifecycle.py -v
"""

from __future__ import annotations

import sqlite3
import sys

import pytest

sys.path.insert(0, ".")


def test_default_cache_path_is_module_level_attribute():
    """The judge cache path MUST live behind a module-level attribute so
    tests/conftest.py can redirect it (AGENTS.md §6/§10)."""
    import agent.eval.judge as judge_mod

    assert hasattr(judge_mod, "DEFAULT_JUDGE_CACHE_PATH")
    assert isinstance(judge_mod.DEFAULT_JUDGE_CACHE_PATH, str)
    assert judge_mod.DEFAULT_JUDGE_CACHE_PATH.endswith("judge_cache.db")


def test_verdict_cache_close_closes_connection(tmp_path):
    """close() must actually close the underlying sqlite connection."""
    from agent.eval.judge import _VerdictCache

    cache = _VerdictCache(str(tmp_path / "judge_cache.db"))
    conn = cache._conn
    cache.close()
    # A closed connection raises ProgrammingError on further use.
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_verdict_cache_close_is_idempotent(tmp_path):
    """Closing twice must not raise (reset_judge may call close on an
    already-closed cache during double-teardown)."""
    from agent.eval.judge import _VerdictCache

    cache = _VerdictCache(str(tmp_path / "judge_cache.db"))
    cache.close()
    cache.close()  # must not raise


def test_reset_judge_closes_singleton_connection(tmp_path, monkeypatch):
    """reset_judge() must close the shared singleton's cache connection so the
    api/main.py shutdown path does not leak an unclosed database."""
    import agent.eval.judge as judge_mod

    # Redirect the cache path to tmp (mirrors tests/conftest.py tmp_data_dir).
    monkeypatch.setattr(judge_mod, "DEFAULT_JUDGE_CACHE_PATH", str(tmp_path / "judge_cache.db"))
    # Start clean — no leftover singleton from other tests.
    if judge_mod._judge is not None:
        judge_mod._judge.close()
    judge_mod._judge = None

    try:
        judge = judge_mod.get_judge()
        conn = judge._cache._conn
        judge_mod.reset_judge()
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")
    finally:
        # Leave the world clean for subsequent tests.
        judge_mod._judge = None
