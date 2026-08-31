#!/usr/bin/env python3
"""
SQLite store lifecycle + persistence-contract guard.

Across the codebase several SQLite-backed stores follow the same singleton
pattern: a module-level ``get_*()`` lazy singleton plus a module-level
``DEFAULT_*_PATH`` for the db location. A past bug class left these connections
unclosed on app shutdown and in test teardown, leaking until interpreter exit
and surfacing as ``ResourceWarning: unclosed database`` (which pyproject.toml
had to relax to "default" to mask).

This module pins the contract for every such store:

1. ``DEFAULT_*_PATH`` module-level attribute exists (AGENTS.md §6/§10 — every
   on-disk path MUST live behind a module-level attribute so tests/conftest.py
   can redirect it to tmp_path).
2. A ``reset_*()`` helper exists that closes + clears the singleton.
3. After ``reset_*()``, the singleton's underlying connection is actually closed
   (raises ProgrammingError on use).

Run: pytest tests/unit/test_sqlite_lifecycle.py -v
"""

from __future__ import annotations

import sqlite3
import sys

import pytest

sys.path.insert(0, ".")

# (module, DEFAULT_PATH attr, singleton holder attr, reset fn)
_STORES = [
    ("agent.eval.judge", "DEFAULT_JUDGE_CACHE_PATH", "_judge", "reset_judge"),
    ("agent.memory.store", "DEFAULT_DB_PATH", "_memory_store", "reset_memory_store"),
    (
        "agent.feedback.collector",
        "DEFAULT_DB_PATH",
        "_feedback_collector",
        "reset_feedback_collector",
    ),
    (
        "agent.feedback.escalation",
        "DEFAULT_DB_PATH",
        "_escalation_manager",
        "reset_escalation_manager",
    ),
    ("documents.parent_store", "DEFAULT_DB_PATH", "_store", "reset_parent_store"),
    ("documents.document_registry", "DEFAULT_DB_PATH", "_registry", "reset_document_registry"),
    (
        "documents.embedding_registry",
        "DEFAULT_DB_PATH",
        "_registry",
        "reset_embedding_registry",
    ),
]


@pytest.mark.parametrize(
    "module_name, path_attr, holder_attr, reset_fn",
    _STORES,
    ids=[s[0] for s in _STORES],
)
def test_store_exposes_module_level_path(module_name, path_attr, holder_attr, reset_fn):
    """Every on-disk path MUST be a module-level attribute (AGENTS.md §6/§10)."""
    import importlib

    mod = importlib.import_module(module_name)
    assert hasattr(mod, path_attr), f"{module_name} must expose {path_attr}"
    assert isinstance(getattr(mod, path_attr), str)


@pytest.mark.parametrize(
    "module_name, path_attr, holder_attr, reset_fn",
    _STORES,
    ids=[s[0] for s in _STORES],
)
def test_store_has_reset_singleton_helper(module_name, path_attr, holder_attr, reset_fn):
    """Every singleton store MUST expose a reset_*() helper for shutdown/tests."""
    import importlib

    mod = importlib.import_module(module_name)
    assert hasattr(mod, reset_fn), f"{module_name} must expose {reset_fn}()"
    assert callable(getattr(mod, reset_fn))


@pytest.mark.parametrize(
    "module_name, path_attr, holder_attr, reset_fn",
    _STORES,
    ids=[s[0] for s in _STORES],
)
def test_reset_closes_singleton_connection(
    module_name, path_attr, holder_attr, reset_fn, monkeypatch, tmp_path
):
    """reset_*() must actually close the singleton's sqlite connection."""
    import importlib

    mod = importlib.import_module(module_name)
    # Redirect the cache/db path to tmp (mirrors tests/conftest.py tmp_data_dir).
    monkeypatch.setattr(mod, path_attr, str(tmp_path / "store.db"))
    # Start clean.
    holder = getattr(mod, holder_attr)
    if holder is not None:
        holder.close()
    setattr(mod, holder_attr, None)

    try:
        # Force the singleton to be built, then grab its connection.
        # Each module exposes a get_*() getter; resolve it generically.
        get_fn_name = {
            "_judge": "get_judge",
            "_memory_store": "get_memory_store",
            "_feedback_collector": "get_feedback_collector",
            "_escalation_manager": "get_escalation_manager",
            "_store": "get_parent_store",
            "_registry": "get_document_registry",
        }[holder_attr]
        if module_name == "documents.embedding_registry":
            get_fn_name = "get_registry"
        instance = getattr(mod, get_fn_name)()
        if module_name in {"documents.parent_store", "documents.embedding_registry"}:
            assert instance._db_path == str(tmp_path / "store.db")
        conn = instance._cache._conn if holder_attr == "_judge" else instance._conn
        getattr(mod, reset_fn)()
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")
    finally:
        setattr(mod, holder_attr, None)
