#!/usr/bin/env python3
"""
REQ-CS-005/006/007/008 — checkpoint serde compatibility regression.

Guards against the langgraph-checkpoint-sqlite 2.0.10 × langchain-core 1.2.30
serde API mismatch that made every thinking-mode ``invoke()``/``ainvoke()``
raise ``AttributeError: 'JsonPlusSerializer' object has no attribute 'dumps'``
(the async path also hit ``.loads()``). Fixed by aligning
``langgraph-checkpoint-sqlite`` to 3.x (which uses ``dumps_typed`` /
``json.dumps``) and removing the now-obsolete import-time + ``astart()``
monkeypatches.

Strategy: the serde bug lives in ``SqliteSaver.put()``/``aput()`` (they call the
removed ``.dumps()``/``.loads()``). A fake graph would bypass the checkpointer
entirely, so we instead drive the *real* checkpointer that the harness
constructs (``_setup_checkpointing`` sync, ``astart`` async) through a round-trip
write+read, plus a true end-to-end ``invoke()`` smoke guarded by ``requires_ollama``.

Run: pytest tests/unit/test_checkpoint_serde_compat.py -v
"""

from __future__ import annotations

import asyncio
import sys

import pytest

sys.path.insert(0, ".")

from agent.harness.orchestrator import (  # noqa: E402
    DEFAULT_CHECKPOINT_PATH,
    HarnessConfig,
)

# ---------------------------------------------------------------------------
# A minimal checkpoint payload that exercises the serde path the bug hit:
# SqliteSaver.put() serialises ``checkpoint`` (via serde.dumps_typed) AND
# ``metadata`` (via the removed jsonplus_serde.dumps() in 2.0.10). Passing
# non-trivial metadata forces the second serialisation, which is exactly the
# AttributeError site.
# ---------------------------------------------------------------------------


def _sample_checkpoint(thread_id: str) -> tuple[dict, dict, dict]:
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    checkpoint = {
        "v": 4,
        "id": "1ef4f797-8335-6428-8001-8a1503f9b875",
        "ts": "2026-06-24T00:00:00+00:00",
        "channel_values": {"messages": []},
        "channel_versions": {},
        "versions_seen": {},
    }
    metadata = {"source": "input", "step": 1, "writes": {}, "parent_config": None}
    return config, checkpoint, metadata


# ===========================================================================
# REQ-CS-008 — persistence contract: DEFAULT_CHECKPOINT_PATH is a module attr
# ===========================================================================


class TestPersistenceContract:
    def test_default_checkpoint_path_is_module_attribute(self):
        """The default checkpoint path MUST be exposed as a module-level attribute
        so tests/conftest.py tmp_data_dir can monkeypatch it (AGENTS.md §10)."""
        assert isinstance(DEFAULT_CHECKPOINT_PATH, str)
        assert DEFAULT_CHECKPOINT_PATH, "DEFAULT_CHECKPOINT_PATH must be non-empty"

    def test_default_checkpoint_path_monkeypatch_taken_up(self, monkeypatch, tmp_path):
        """A fresh HarnessConfig() MUST pick up a monkeypatched module path — the
        dataclass default resolves lazily in __post_init__, not at class-def time
        (a plain ``str = DEFAULT_CHECKPOINT_PATH`` default would freeze at import)."""
        from agent.harness import orchestrator

        fake = str(tmp_path / "sealed.db")
        monkeypatch.setattr(orchestrator, "DEFAULT_CHECKPOINT_PATH", fake)
        cfg = HarnessConfig()
        assert cfg.checkpoint_path == fake, (
            "HarnessConfig.checkpoint_path did not pick up the monkeypatched "
            "DEFAULT_CHECKPOINT_PATH — checkpointer writes would leak to ./data/"
        )

    def test_explicit_checkpoint_path_still_overrides_default(self, tmp_path):
        """Explicit config still wins over the module default."""
        explicit = str(tmp_path / "explicit.db")
        cfg = HarnessConfig(checkpoint_path=explicit)
        assert cfg.checkpoint_path == explicit

    def test_checkpoint_path_is_always_str_never_none(self):
        """The field annotation is ``str`` (not ``str | None``) and the
        default_factory resolves it eagerly in __post_init__, so no None ever
        reaches the sqlite3.connect/aiosqlite.connect call sites (critic F-CS-02)."""
        cfg = HarnessConfig()
        assert isinstance(cfg.checkpoint_path, str)
        assert cfg.checkpoint_path is not None


# ===========================================================================
# REQ-CS-005 — sync SqliteSaver.put()+get() round-trips without serde error
#
# This is the exact path run_eval.py (sync harness.invoke()) exercises. The
# harness builds the SqliteSaver in _setup_checkpointing(); we then drive its
# put()/get_tuple() directly with a metadata-bearing payload (the 2.0.10
# AttributeError site), which fails the moment the serde shim is missing.
# ===========================================================================


class TestSyncCheckpointSerde:
    def test_sync_saver_put_get_without_attribute_error(self, tmp_path):
        from agent.harness.orchestrator import AgentHarness

        ckpt = str(tmp_path / "checkpoints.db")
        h = AgentHarness(config=HarnessConfig(checkpoint_path=ckpt))
        # __init__ builds the graph, but only sets up checkpointing when skills
        # are registered (get_agent_harness path). Drive _setup_checkpointing
        # directly to construct the real SqliteSaver against the tmp path.
        h._setup_checkpointing()
        try:
            saver = h._memory
            assert saver is not None, "sync SqliteSaver not constructed"
            config, checkpoint, metadata = _sample_checkpoint("serde-sync")
            try:
                saver.put(config, checkpoint, metadata, {})
            except AttributeError as e:
                pytest.fail(f"SqliteSaver.put() raised serde AttributeError: {e}")
            got = saver.get_tuple({"configurable": {"thread_id": "serde-sync"}})
            assert got is not None, "checkpoint written but not readable back"
        finally:
            h.close()

    def test_sync_checkpoint_file_lands_in_tmp(self, tmp_path):
        from agent.harness.orchestrator import AgentHarness

        ckpt = str(tmp_path / "checkpoints.db")
        h = AgentHarness(config=HarnessConfig(checkpoint_path=ckpt))
        h._setup_checkpointing()
        try:
            saver = h._memory
            config, checkpoint, metadata = _sample_checkpoint("sealed-sync")
            saver.put(config, checkpoint, metadata, {})
        finally:
            h.close()
        assert (tmp_path / "checkpoints.db").exists(), "checkpoint not written to tmp"
        assert tmp_path.as_posix() in h._config.checkpoint_path


# ===========================================================================
# REQ-CS-006 — async AsyncSqliteSaver.aput()+aget_tuple() round-trips
#
# The async path previously needed the (now-removed) is_alive + dumps/loads
# shims. 3.x fixed both; astart() constructs the real AsyncSqliteSaver.
# ===========================================================================


class TestAsyncCheckpointSerde:
    """Drive the real AsyncSqliteSaver directly. We deliberately do NOT route
    through ``harness.astart()`` here: astart() unconditionally rebuilds the full
    graph (which needs skills registered to compile). The serde bug lives in
    ``AsyncSqliteSaver.aput()``/``aget_tuple()`` — the same saver astart()
    constructs — so a direct put/aget round-trip is the precise, hermetic guard
    for REQ-CS-006. The full async path is still covered by the Ollama-gated
    end-to-end test below."""

    def test_async_saver_aput_aget_without_attribute_error(self, tmp_path):
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        ckpt = str(tmp_path / "checkpoints.db")

        async def _run():
            conn = await aiosqlite.connect(ckpt)
            try:
                saver = AsyncSqliteSaver(conn)
                config, checkpoint, metadata = _sample_checkpoint("serde-async")
                try:
                    await saver.aput(config, checkpoint, metadata, [])
                except AttributeError as e:
                    pytest.fail(f"AsyncSqliteSaver.aput() raised serde AttributeError: {e}")
                got = await saver.aget_tuple({"configurable": {"thread_id": "serde-async"}})
                assert got is not None, "async checkpoint written but not readable back"
            finally:
                await conn.close()

        asyncio.run(_run())

    def test_async_checkpoint_file_lands_in_tmp(self, tmp_path):
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        ckpt = str(tmp_path / "checkpoints.db")

        async def _run():
            conn = await aiosqlite.connect(ckpt)
            try:
                saver = AsyncSqliteSaver(conn)
                config, checkpoint, metadata = _sample_checkpoint("sealed-async")
                await saver.aput(config, checkpoint, metadata, [])
            finally:
                await conn.close()

        asyncio.run(_run())
        assert (tmp_path / "checkpoints.db").exists()


# ===========================================================================
# REQ-CS-005/006 — real compiled-graph checkpoint path (NO Ollama gate)
#
# The saver.put/get tests above exercise the serde API directly, but the bug
# actually surfaced when *LangGraph* calls saver.put() per node during a
# compiled-graph invoke. A fake graph bypasses the checkpointer entirely, and
# the full-harness path needs Ollama. This closes the gap: a minimal compiled
# StateGraph (single int node, no LLM/Milvus) wired to the real harness-built
# SqliteSaver, so the exact graph→checkpointer→serde integration runs in CI.
# (Addresses critic F-CS-03: regression must guard the real graph path, not
# just the saver API.)
# ===========================================================================


class TestRealCompiledGraphCheckpoint:
    def test_compiled_graph_writes_and_reads_checkpoint(self, tmp_path):
        """A compiled StateGraph driving the harness-built SqliteSaver must
        write a checkpoint on invoke() and read it back — the exact integration
        that AttributeError'd before the 3.x alignment. No Ollama/Milvus."""
        from typing import TypedDict

        from langgraph.graph import END, START, StateGraph

        from agent.harness.orchestrator import AgentHarness

        class _S(TypedDict):
            count: int

        h = AgentHarness(config=HarnessConfig(checkpoint_path=str(tmp_path / "graph.db")))
        h._setup_checkpointing()
        try:
            assert h._memory is not None, "SqliteSaver not constructed"
            builder = StateGraph(_S)
            builder.add_node("inc", lambda s: {"count": s["count"] + 1})
            builder.add_edge(START, "inc")
            builder.add_edge("inc", END)
            graph = builder.compile(checkpointer=h._memory)

            result = graph.invoke(
                {"count": 1},
                {"configurable": {"thread_id": "graph-serde", "checkpoint_ns": ""}},
            )
            assert result == {"count": 2}

            # The checkpoint was written by the graph's checkpointer (put per node).
            got = h._memory.get_tuple({"configurable": {"thread_id": "graph-serde"}})
            assert got is not None, "graph did not persist a checkpoint"
        finally:
            h.close()


# ===========================================================================
# F-CS-06 — strict msgpack deserialization (CVE-2025-64439 hardening)
#
# CVE-2025-64439 (json-mode deserialisation RCE) is fixed in checkpoint >= 3.0
# via a json allow-list + removal of unsafe json mode. Separately, the msgpack
# path defaults to PERMISSIVE (any type instantiated) unless
# LANGGRAPH_STRICT_MSGPACK=true. orchestrator._enable_strict_msgpack forces
# strict; these tests pin both that the flag is on AND that strict mode keeps
# normal checkpoints working (SAFE types unaffected).
# ===========================================================================


class TestStrictMsgpack:
    def test_strict_msgpack_enabled_by_orchestrator_import(self):
        """Importing the orchestrator MUST force strict msgpack (closes the
        permissive-deserialisation RCE surface, critic F-CS-06)."""
        from langgraph.checkpoint.serde import jsonplus as jp

        lg = jp._lg_msgpack
        assert getattr(lg, "STRICT_MSGPACK_ENABLED", False) is True, (
            "STRICT_MSGPACK_ENABLED is False — orchestrator's "
            "_enable_strict_msgpack_deserialization did not run; the msgpack "
            "deserialiser is permissive (RCE surface open)"
        )

    def test_default_serializer_is_strict_after_orchestrator(self):
        """A default JsonPlusSerializer() constructed after orchestrator import
        must be strict (allowed_msgpack_modules != True)."""
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

        s = JsonPlusSerializer()
        assert s._allowed_msgpack_modules is not True, (
            f"JsonPlusSerializer is permissive (_allowed_msgpack_modules="
            f"{s._allowed_msgpack_modules!r}); strict msgpack not in effect"
        )

    def test_strict_msgpack_allows_normal_checkpoint_round_trip(self, tmp_path):
        """Strict mode must NOT break normal checkpoint round-trips — graph state
        (dicts/scalars/messages) is SAFE_MSGPACK_TYPES and serialises fine.
        Verifies the security hardening has no functional cost."""
        from langgraph.checkpoint.sqlite import SqliteSaver

        conn = __import__("sqlite3").connect(str(tmp_path / "strict.db"), check_same_thread=False)
        saver = SqliteSaver(conn)
        try:
            config, checkpoint, metadata = _sample_checkpoint("strict-normal")
            saver.put(config, checkpoint, metadata, {})
            got = saver.get_tuple({"configurable": {"thread_id": "strict-normal"}})
            assert got is not None
            # Data integrity preserved under strict mode.
            assert got.checkpoint["channel_values"] == {"messages": []}
        finally:
            conn.close()

    def test_structured_evidence_round_trips_in_sync_saver(self, tmp_path):
        from langgraph.checkpoint.sqlite import SqliteSaver

        conn = __import__("sqlite3").connect(
            str(tmp_path / "strict-evidence.db"), check_same_thread=False
        )
        saver = SqliteSaver(conn)
        try:
            config, checkpoint, metadata = _sample_checkpoint("strict-evidence-sync")
            evidence = [
                {
                    "content": "证据",
                    "source": "manual.md",
                    "title": "章节",
                    "score": 0.8,
                    "metadata": {"page": 1, "tags": ["a", "b"]},
                }
            ]
            checkpoint["channel_values"]["shared_state"] = {
                "retrieval_evidence": evidence,
                "generation_evidence": evidence,
            }
            saver.put(config, checkpoint, metadata, {})
            got = saver.get_tuple({"configurable": {"thread_id": "strict-evidence-sync"}})
            assert got.checkpoint["channel_values"]["shared_state"] == {
                "retrieval_evidence": evidence,
                "generation_evidence": evidence,
            }
        finally:
            conn.close()

    def test_structured_evidence_round_trips_in_async_saver(self, tmp_path):
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        async def _run():
            conn = await aiosqlite.connect(str(tmp_path / "strict-evidence-async.db"))
            try:
                saver = AsyncSqliteSaver(conn)
                config, checkpoint, metadata = _sample_checkpoint("strict-evidence-async")
                evidence = [
                    {
                        "content": "证据",
                        "source": "manual.md",
                        "title": "章节",
                        "score": None,
                        "metadata": {"nested": {"ok": True}},
                    }
                ]
                checkpoint["channel_values"]["shared_state"] = {
                    "retrieval_evidence": evidence,
                    "generation_evidence": evidence,
                }
                await saver.aput(config, checkpoint, metadata, [])
                got = await saver.aget_tuple(
                    {"configurable": {"thread_id": "strict-evidence-async"}}
                )
                assert got.checkpoint["channel_values"]["shared_state"] == {
                    "retrieval_evidence": evidence,
                    "generation_evidence": evidence,
                }
            finally:
                await conn.close()

        asyncio.run(_run())


# ===========================================================================
# F-CS-04 — sqlite-vec transitive dependency (offline/air-gap)
#
# langgraph-checkpoint-sqlite 3.x pulls in sqlite-vec (a native C extension).
# For air-gapped/offline deployments this MUST be installable offline. This test
# guards that it is importable + the native lib loads in the current env.
# ===========================================================================


class TestSqliteVecAirGap:
    def test_sqlite_vec_importable_and_native_loadable(self):
        """sqlite-vec (3.x transitive dep, native ext) must be importable and its
        loadable native library resolvable — an air-gap deployment that failed to
        bundle this wheel would break checkpointing at runtime (critic F-CS-04)."""
        import sqlite_vec

        assert sqlite_vec.loadable_path(), (
            "sqlite_vec.loadable_path() is empty — native extension not bundled; "
            "air-gapped/offline checkpointing would fail"
        )


# ===========================================================================
# REQ-CS-005 full path — real harness.invoke() end-to-end (needs Ollama)
#
# This is the strongest guard: it runs the *entire* thinking-mode graph through
# the real checkpointer (graph.invoke writes a checkpoint per node). Skipped
# when Ollama is unavailable; run locally / in self-hosted CI to catch a serde
# regression that only surfaces under the full graph.
# ===========================================================================


def _ollama_available() -> bool:
    import urllib.error
    import urllib.request

    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2).close()
        return True
    except (urllib.error.URLError, OSError):
        return False


@pytest.mark.requires_ollama
@pytest.mark.skipif(not _ollama_available(), reason="Ollama not reachable")
class TestEndToEndInvoke:
    def test_real_invoke_returns_without_serde_error(self, tmp_path):
        from agent.harness import get_agent_harness

        h = get_agent_harness(config=HarnessConfig(checkpoint_path=str(tmp_path / "e2e.db")))
        try:
            result = h.invoke("服务启动失败的可能原因", thread_id="e2e-serde")
            assert isinstance(result, dict)
            assert "messages" in result
        except AttributeError as e:
            pytest.fail(f"end-to-end invoke() raised serde AttributeError: {e}")
        finally:
            h.close()

    def test_real_ainvoke_returns_without_serde_error(self, tmp_path):
        """Async full-path guard: astart() + ainvoke() drive AsyncSqliteSaver.aput()
        on every node. Before the 3.x alignment this hit both the is_alive and the
        dumps/loads AttributeError sites in the async saver."""
        from agent.harness import get_agent_harness

        h = get_agent_harness(config=HarnessConfig(checkpoint_path=str(tmp_path / "e2e.db")))

        async def _run():
            await h.astart()
            return await h.ainvoke("缓存命中率下降的可能原因", thread_id="e2e-async")

        try:
            result = asyncio.run(_run())
            assert isinstance(result, dict)
            assert "messages" in result
        except AttributeError as e:
            pytest.fail(f"end-to-end ainvoke() raised serde AttributeError: {e}")
        finally:
            asyncio.run(h.aclose())


# ===========================================================================
# REQ-CS-007 — no residual monkeypatch on JsonPlusSerializer / orchestrator
# ===========================================================================


class TestNoResidualShim:
    def test_jsonplus_serializer_has_no_dumps_shim(self):
        """The obsolete ``_patch_jsonplus_serde_compat`` (import-time) and the
        ``astart()`` ``_dumps_shim`` MUST be gone after the 3.x alignment.
        3.x's JsonPlusSerializer exposes only dumps_typed/loads_typed; a leftover
        ``dumps``/``loads`` injection would indicate an un-removed shim."""
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

        assert not hasattr(JsonPlusSerializer, "dumps"), (
            "JsonPlusSerializer.dumps is injected — the import-time serde shim "
            "(_patch_jsonplus_serde_compat) was not removed"
        )
        assert not hasattr(JsonPlusSerializer, "loads"), (
            "JsonPlusSerializer.loads is injected — a residual shim remains"
        )
        assert hasattr(JsonPlusSerializer, "dumps_typed")
        assert hasattr(JsonPlusSerializer, "loads_typed")

    def test_orchestrator_no_longer_imports_compat_patch(self):
        """The ``_patch_jsonplus_serde_compat`` function MUST be removed."""
        from agent.harness import orchestrator

        assert not hasattr(orchestrator, "_patch_jsonplus_serde_compat"), (
            "_patch_jsonplus_serde_compat still present in orchestrator — "
            "remove the obsolete import-time monkeypatch"
        )

    def test_dependency_pinned_to_sqlite_saver_3x(self):
        """The installed sqlite-saver is 3.x (the version that fixed the
        dumps/loads API mismatch)."""
        import importlib.metadata as md

        v = md.version("langgraph-checkpoint-sqlite")
        major = int(v.split(".")[0])
        assert major >= 3, (
            f"langgraph-checkpoint-sqlite is {v}, expected >=3.0 "
            "(2.x calls the removed .dumps()/.loads() API)"
        )

    def test_langgraph_checkpoint_at_least_4_1(self):
        """CVE-2025-64439 (json-mode RCE) is fixed in checkpoint >= 3.0; the
        sqlite-saver 3.1.0 pin requires checkpoint >= 4.1.0. Confirm the
        resolved version satisfies the security fix floor."""
        import importlib.metadata as md

        v = md.version("langgraph-checkpoint")
        major = int(v.split(".")[0])
        assert (major, *([int(x) for x in v.split(".")[1:2]])) >= (4, 1), (
            f"langgraph-checkpoint is {v}, expected >=4.1 (sqlite-saver 3.1.0 + CVE fix)"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
