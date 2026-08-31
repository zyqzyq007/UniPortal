"""
Shared fixtures and app wiring for end-to-end tests.

These fixtures let the full FastAPI app run in-process WITHOUT a real Ollama
LLM or Milvus, by replacing the module-level singleton getters that the
routers import internally.

Design notes:
  - The app has NO create_app() factory and most routers import singletons
    inline (not via Depends). So we patch the *source* modules'
    ``get_*`` getters via monkeypatch, plus FastAPI's dependency_overrides for
    ``get_session_memory`` (the one true Depends seam).
  - All on-disk artefacts (inference DB, candidates, eval runs, session DB)
    are redirected to a per-test tmp directory so tests are hermetic.
  - A FakeLLM, FakeRetriever, and a lightweight fake harness stand in for the
    expensive real components.
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure project root is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mark the process as running under pytest BEFORE any FastAPI lifespan runs,
# so the F05 production-unsafe-config startup guard in api/main.py skips
# (tests intentionally use the local-dev default config).
os.environ.setdefault("PYTEST_RUN", "1")


def pytest_collection_modifyitems(config, items):
    if os.getenv("OLLAMA_FULL_TESTS", "").strip().lower() in {"1", "true", "yes", "on"}:
        return
    skip_backend = pytest.mark.skip(reason="requires explicit OLLAMA_FULL_TESTS=1 opt-in")
    for item in items:
        if item.get_closest_marker("requires_ollama") or item.get_closest_marker(
            "requires_backend"
        ):
            item.add_marker(skip_backend)


# ---------------------------------------------------------------------------
# Session teardown: close any singleton SQLite connections left open by tests
# that did not request the tmp_data_dir redirect (e.g. tests that touch the
# LLMJudge via a guardrail but build the skill directly). Without this the
# connection survives until interpreter exit and surfaces as
# ResourceWarning: unclosed database.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _close_sqlite_singletons_after_test():
    yield
    # Close any singleton SQLite connections left open by tests that did not
    # request the tmp_data_dir redirect (e.g. tests that build a store/judge
    # directly). Without this the connections survive until interpreter exit
    # and surface as ResourceWarning: unclosed database.
    for _reset in (
        "agent.eval.judge.reset_judge",
        "agent.memory.store.reset_memory_store",
        "agent.feedback.collector.reset_feedback_collector",
        "agent.feedback.escalation.reset_escalation_manager",
        "documents.parent_store.reset_parent_store",
        "documents.document_registry.reset_document_registry",
        "documents.embedding_registry.reset_embedding_registry",
        "documents.graph_store.reset_graph_store",
        "documents.graph_extractor.reset_graph_extractor",
        "core.retrieval.graph_retriever.reset_graph_retriever",
        "core.retrieval.workflow.reset_retrieval_workflow",
        "core.retrieval.raptor_store.reset_raptor_store",
        "core.retrieval.visual_retriever.reset_visual_retriever",
    ):
        try:
            mod_name, fn_name = _reset.rsplit(".", 1)
            import importlib

            getattr(importlib.import_module(mod_name), fn_name)()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Tmp data dir: redirect ALL on-disk state so tests never touch real data/
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Redirect every on-disk path the eval/store subsystem uses."""
    data = tmp_path / "data"
    (data / "eval" / "runs").mkdir(parents=True)
    (data / "eval" / "candidates").mkdir(parents=True)
    root = str(data)

    # Patch paths used by the eval / store modules.
    monkeypatch.setattr(
        "agent.eval.inference_store.DEFAULT_DB_PATH",
        os.path.join(root, "inferences.db"),
    )
    monkeypatch.setattr(
        "agent.eval.history.RUNS_DIR",
        __import__("pathlib").Path(os.path.join(root, "eval", "runs")),
    )
    monkeypatch.setattr(
        "agent.eval.history.HISTORY_PATH",
        __import__("pathlib").Path(os.path.join(root, "eval", "runs", "history.jsonl")),
    )
    monkeypatch.setattr(
        "agent.eval.candidates.CANDIDATES_DIR",
        __import__("pathlib").Path(os.path.join(root, "eval", "candidates")),
    )
    monkeypatch.setattr(
        "agent.eval.flywheel.RETRIEVAL_MISSES_DB",
        os.path.join(root, "eval", "retrieval_misses.db"),
    )
    # Redirect the LLMJudge verdict-cache path to tmp and reset its singleton.
    # Without this, tests that touch the judge (grounding/PII guardrails,
    # flywheel) write to the real ./data/eval/judge_cache.db and leak an
    # unclosed sqlite connection until interpreter exit (ResourceWarning).
    monkeypatch.setattr(
        "agent.eval.judge.DEFAULT_JUDGE_CACHE_PATH",
        os.path.join(root, "eval", "judge_cache.db"),
    )
    import agent.eval.judge as judge_mod

    if judge_mod._judge is not None:
        judge_mod._judge.close()
    judge_mod._judge = None
    # Redirect the agent-memory / feedback shared DB (agent_memory.db) to tmp
    # and reset their singletons (same ResourceWarning class as the judge).
    monkeypatch.setattr(
        "agent.memory.store.DEFAULT_DB_PATH",
        os.path.join(root, "agent_memory.db"),
    )
    monkeypatch.setattr(
        "agent.feedback.collector.DEFAULT_DB_PATH",
        os.path.join(root, "agent_memory.db"),
    )
    monkeypatch.setattr(
        "agent.feedback.escalation.DEFAULT_DB_PATH",
        os.path.join(root, "agent_memory.db"),
    )
    monkeypatch.setattr(
        "documents.parent_store.DEFAULT_DB_PATH",
        os.path.join(root, "parent_store.db"),
    )
    monkeypatch.setattr(
        "documents.graph_store.DEFAULT_DB_PATH",
        os.path.join(root, "graph_store.db"),
    )
    monkeypatch.setattr(
        "documents.graph_store.DEFAULT_V1_BACKUP_PATH",
        os.path.join(root, "graph_store_v1_backup.db"),
    )
    monkeypatch.setattr(
        "documents.document_registry.DEFAULT_DB_PATH",
        os.path.join(root, "documents.db"),
    )
    monkeypatch.setattr(
        "documents.embedding_registry.DEFAULT_DB_PATH",
        os.path.join(root, "embedding_registry.db"),
    )
    monkeypatch.setattr(
        "core.retrieval.raptor_store.RAPTOR_DB_PATH",
        os.path.join(root, "raptor.db"),
    )
    monkeypatch.setattr(
        "core.retrieval.visual_retriever.VISUAL_INDEX_PATH",
        os.path.join(root, "visual_index.db"),
    )
    monkeypatch.setattr(
        "core.retrieval.visual_retriever.PDF_ASSET_DIR",
        os.path.join(root, "visual_assets"),
    )
    # Redirect the session checkpoint DB to tmp and clear the process-wide
    # harness singleton so the next get_agent_harness() picks up the new path.
    # Without this, any test that drives the real LangGraph checkpointer writes
    # to ./data/checkpoints.db (AGENTS.md §10 persistence contract).
    monkeypatch.setattr(
        "agent.harness.orchestrator.DEFAULT_CHECKPOINT_PATH",
        os.path.join(root, "checkpoints.db"),
    )
    import agent.harness as harness_pkg

    if harness_pkg._harness is not None:
        harness_pkg._harness.close()
    harness_pkg._harness = None
    import agent.feedback.collector as fc_mod
    import agent.feedback.escalation as esc_mod
    import agent.memory.store as mem_mod
    import documents.document_registry as dr_mod
    import documents.embedding_registry as er_mod
    import documents.graph_store as gs_mod
    import documents.parent_store as ps_mod

    if mem_mod._memory_store is not None:
        mem_mod._memory_store.close()
    mem_mod._memory_store = None
    if fc_mod._feedback_collector is not None:
        fc_mod._feedback_collector.close()
    fc_mod._feedback_collector = None
    if esc_mod._escalation_manager is not None:
        esc_mod._escalation_manager.close()
    esc_mod._escalation_manager = None
    if ps_mod._store is not None:
        ps_mod._store.close()
    ps_mod._store = None
    if gs_mod._store is not None:
        gs_mod._store.close()
    gs_mod._store = None
    if dr_mod._registry is not None:
        dr_mod._registry.close()
    dr_mod._registry = None
    if er_mod._registry is not None:
        er_mod._registry.close()
    er_mod._registry = None
    # Reset the inference store singleton so it picks up the new path.
    import agent.eval.inference_store as is_mod

    if is_mod._store is not None:
        is_mod._store.close()
    is_mod._store = None

    # Redirect the documents upload temp dir (B6) so uploaded files land in
    # tmp_path instead of the real /tmp, keeping uploads hermetic.
    upload_tmp = os.path.join(root, "uploads")
    os.makedirs(upload_tmp, exist_ok=True)
    import api.routers.documents as docs_mod

    monkeypatch.setattr(docs_mod, "UPLOAD_TMP_DIR", upload_tmp)
    return root


# ---------------------------------------------------------------------------
# Fake LLM
# ---------------------------------------------------------------------------


class FakeAIMessage:
    """Minimal stand-in for langchain AIMessage."""

    def __init__(self, content: str):
        self.content = content
        self.type = "ai"
        self.additional_kwargs = {}
        self.tool_calls = []


class FakeLLM:
    """
    A deterministic fake chat model. Returns a canned answer (optionally
    derived from the prompt). Implements both sync invoke and async ainvoke,
    plus with_structured_output for the intent classifier.
    """

    def __init__(self, answer: str = "这是测试回答。仅供参考。"):
        self._answer = answer

    def invoke(self, messages, **kwargs):
        return FakeAIMessage(self._answer)

    async def ainvoke(self, messages, **kwargs):
        return FakeAIMessage(self._answer)

    def with_structured_output(self, schema, **kwargs):
        # Intent classifier path: return a default rag_query intent result.
        outer = self

        class _Structured:
            def invoke(self_, messages, **kw):
                return outer._structured_result()

            async def ainvoke(self_, messages, **kw):
                return outer._structured_result()

        return _Structured()

    def _structured_result(self):
        # Build an IntentResult-like object.
        try:
            from core.intent.classifier import IntentResult, IntentType

            return IntentResult(
                intent=IntentType.RAG_QUERY,
                confidence=0.9,
                reasoning="fake classifier",
            )
        except Exception:
            return None


@pytest.fixture
def fake_llm():
    return FakeLLM()


# ---------------------------------------------------------------------------
# Fake retriever
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_retriever():
    """A hybrid retriever that returns two canned docs with scores."""
    from langchain_core.documents import Document

    class _FakeRetriever:
        def retrieve(self, query, top_k=None, filter_expr=None):
            return [
                Document(
                    page_content="Git 合并冲突通常由同一文件的多分支改动引起，需手动编辑冲突标记后提交。",
                    metadata={"source": "git_guide", "title": "合并冲突排查", "score": 0.92},
                ),
                Document(
                    page_content="解决冲突后应运行测试确认无回归，再完成合并提交。",
                    metadata={"source": "git_guide", "title": "冲突后验证", "score": 0.80},
                ),
            ][: (top_k or 4)]

        async def aretrieve(self, query, top_k=None, filter_expr=None):
            return self.retrieve(query, top_k=top_k, filter_expr=filter_expr)

    return _FakeRetriever()


# ---------------------------------------------------------------------------
# Fake harness
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_harness(fake_llm, fake_retriever):
    """
    A minimal agent harness that returns a canned answer + sources for any
    ainvoke / invoke / astream call. This stands in for the full LangGraph so
    the RAG chat branch runs without building the real graph.
    """
    from langchain_core.messages import AIMessage, ToolMessage

    canned_answer = "Git 合并冲突需要手动编辑冲突标记后提交，仅供参考。"

    def _build_result():
        return {
            "messages": [
                ToolMessage(
                    content="Git 合并冲突通常由同一文件的多分支改动引起，需手动编辑冲突标记后提交。",
                    tool_call_id="c1",
                ),
                AIMessage(
                    content=canned_answer,
                    additional_kwargs={
                        "reasoning": "fake reasoning",
                        "confidence": 0.85,
                    },
                ),
            ],
            "_sources": [
                {
                    "source": "git_guide",
                    "title": "合并冲突排查",
                    "content": "Git 合并冲突通常由同一文件的多分支改动引起",
                    "score": 0.92,
                }
            ],
            "shared_state": {
                "generation_evidence": [
                    {
                        "content": "Git 合并冲突通常由同一文件的多分支改动引起",
                        "source": "git_guide",
                        "title": "合并冲突排查",
                        "score": 0.92,
                        "metadata": {"score": 0.92},
                    }
                ]
            },
        }

    class _FakeHarness:
        async def astart(self):
            return self

        async def aclose(self):
            pass

        def invoke(self, query, thread_id=None, **kwargs):
            return _build_result()

        async def ainvoke(self, query, thread_id=None, **kwargs):
            return _build_result()

        async def astream(self, query, thread_id=None, **kwargs):
            # Emit LangGraph-shaped (mode, data) tuples so the streaming
            # endpoint's RAG branch assembles a non-empty full_response.
            # Parity with tests/e2e_ui/_fakes.py:_FakeHarness.astream and the
            # real graph update stream. Previously this yielded a bare
            # {'messages': [...]} dict, which no node handler matched.
            yield (
                "updates",
                {
                    "retrieve": {
                        "messages": [
                            {
                                "content": "Git 合并冲突通常由同一文件的多分支改动引起，需手动编辑冲突标记后提交。",
                                "metadata": {"source": "git_guide", "title": "合并冲突排查"},
                            }
                        ]
                    }
                },
            )
            yield ("custom", {"type": "token", "content": canned_answer})
            yield (
                "updates",
                {
                    "generate": {
                        "messages": [
                            AIMessage(
                                content=canned_answer,
                                additional_kwargs={"reasoning": "fake", "confidence": 0.85},
                            )
                        ],
                        "shared_state": {
                            "generation_evidence": [
                                {
                                    "content": "Git 合并冲突通常由同一文件的多分支改动引起",
                                    "source": "git_guide",
                                    "title": "合并冲突排查",
                                    "score": 0.92,
                                    "metadata": {"score": 0.92},
                                }
                            ]
                        },
                    }
                },
            )

    return _FakeHarness()


# ---------------------------------------------------------------------------
# Fake session memory
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_session_memory():
    """An in-memory session store so chat/sessions endpoints work offline."""
    import time

    class _FakeMemory:
        def __init__(self):
            self._store = {}  # session_id -> list of langchain messages

        async def save_message(self, session_id, message):
            self._store.setdefault(session_id, []).append(message)

        async def get_messages(self, session_id, limit=50):
            from langchain_core.messages import AIMessage, HumanMessage

            msgs = self._store.get(session_id, [])
            # Return as langchain messages with a timestamp in additional_kwargs.
            out = []
            for m in reversed(msgs[-limit:]):
                content = getattr(m, "content", str(m))
                cls = HumanMessage if type(m).__name__ == "HumanMessage" else AIMessage
                out.append(
                    cls(
                        content=content,
                        additional_kwargs={"_timestamp": time.time()},
                    )
                )
            return out

        async def get_session_info(self, session_id):
            msgs = self._store.get(session_id, [])
            return {
                "session_id": session_id,
                "message_count": len(msgs),
                "title": "",
                "created_at": None,
                "last_active": None,
                "exists": True,
            }

        async def list_sessions(self, skip=0, limit=20):
            all_sessions = [
                {"session_id": sid, "message_count": len(msgs)} for sid, msgs in self._store.items()
            ]
            return all_sessions[skip : skip + limit], len(all_sessions)

        async def clear_session(self, session_id):
            self._store.pop(session_id, None)

        async def session_exists(self, session_id):
            # Match the real RedisSessionMemory contract: a session "exists"
            # once at least one message has been recorded against it.
            return session_id in self._store

        async def register_session(self, session_id, title=""):
            # The real impl refreshes last-active; for the in-memory fake we
            # only need to ensure the session is present so session_exists()
            # returns True after an extend call on an empty session.
            self._store.setdefault(session_id, [])

        def close(self):
            pass

    return _FakeMemory()


# ---------------------------------------------------------------------------
# App + TestClient with all singletons patched
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_data_dir, fake_llm, fake_retriever, fake_harness, fake_session_memory, monkeypatch):
    """
    Build a TestClient over the real FastAPI app with all expensive
    singletons replaced by fakes. The app's lifespan is bypassed so we never
    build the real LangGraph.
    """
    # Patch source-module getters BEFORE importing the app.
    import agent.harness as harness_mod

    monkeypatch.setattr(harness_mod, "get_agent_harness", lambda *a, **k: fake_harness)

    import core.intent.classifier as intent_mod

    # Make the classifier use the keyword fast-path / our fake LLM.
    monkeypatch.setattr(
        intent_mod, "get_intent_classifier", lambda *a, **k: _FakeIntentClassifier(fake_llm)
    )

    import core.retrieval.hybrid_retriever as hr_mod

    monkeypatch.setattr(hr_mod, "get_hybrid_retriever", lambda *a, **k: fake_retriever)

    import models.llm_models as llm_mod

    monkeypatch.setattr(llm_mod, "get_llm", lambda *a, **k: fake_llm)
    monkeypatch.setattr(llm_mod, "create_custom_llm", lambda *a, **k: fake_llm)

    # Patch fast_mode to use the fake llm/retriever instead of real ones.
    import core.fast_mode as fast_mod

    async def _fake_fast_generate_async(query, **kwargs):
        from types import SimpleNamespace

        docs = fake_retriever.retrieve(query)
        return SimpleNamespace(
            answer="快速模式检索结果。Git 合并冲突需手动编辑冲突标记。仅供参考。",
            sources=[
                {
                    "source": d.metadata["source"],
                    "title": d.metadata["title"],
                    "content": d.page_content,
                    "score": d.metadata["score"],
                }
                for d in docs
            ],
            retrieval_count=len(docs),
            retrieval_time_ms=10.0,
            generation_time_ms=20.0,
        )

    monkeypatch.setattr(fast_mod, "fast_generate_async", _fake_fast_generate_async)

    # Force the inference sampler to capture EVERY request in E2E tests.
    # (DEFAULT_SAMPLE_RATE is read at module load so env override is too late;
    # patching should_sample directly is reliable.)
    import agent.eval.sampler as sampler_mod

    monkeypatch.setattr(sampler_mod, "should_sample", lambda *a, **k: True)
    # capture.py imports should_sample by name, so patch it there too.
    import agent.eval.capture as capture_mod

    monkeypatch.setattr(capture_mod, "should_sample", lambda *a, **k: True)

    # Import app and override the session_memory dependency.
    from api.main import app
    from api.routers.chat import get_session_memory as chat_get_session_memory
    from api.routers.sessions import get_session_memory as sess_get_session_memory

    app.dependency_overrides[chat_get_session_memory] = lambda: fake_session_memory
    app.dependency_overrides[sess_get_session_memory] = lambda: fake_session_memory

    # Use TestClient with a no-op lifespan context so the real harness/LLM
    # startup is skipped.
    from fastapi.testclient import TestClient

    # Patch the lifespan startup path: make get_agent_harness().astart a no-op
    # and avoid reranker warmup by disabling it. Also force RERANKER_ENABLED off
    # so the in-process E2E suite stays deterministic and never touches the real
    # reranker model path (the default flipped to ON in reranker-default-on).
    monkeypatch.setattr("utils.env_utils.RERANKER_WARMUP", False)
    monkeypatch.setattr("utils.env_utils.RERANKER_ENABLED", False)

    # When ADMIN_API_KEY is configured (e.g. loaded from a local .env), admin
    # endpoints gated by require_admin need a matching X-Admin-Key header. Give
    # the test client a default header carrying the configured key so admin
    # tests pass regardless of whether a key is set. (When no key is set,
    # require_admin allows the "testclient" loopback identity, so the header is
    # harmless.)
    _admin_key = os.getenv("ADMIN_API_KEY", "").strip()
    _client_kwargs = {"raise_server_exceptions": True}
    if _admin_key:
        _client_kwargs["headers"] = {"X-Admin-Key": _admin_key}

    with TestClient(app, **_client_kwargs) as c:
        yield c

    app.dependency_overrides.clear()


class _FakeIntentClassifier:
    """Uses keyword fast-path; falls back to a fake LLM structured output."""

    _RAG_KEYWORDS = frozenset(
        [
            # Domain-neutral technical keywords so the routing fast-path fires for
            # generic queries (git, docker, http, deploy, config, ...). The previous
            # list carried domain-specific terms which coupled the default test
            # path to a single domain.
            "git",
            "docker",
            "http",
            "https",
            "部署",
            "配置",
            "合并",
            "冲突",
            "分支",
            "接口",
            "服务",
            "命令",
            "异常",
            "排查",
            "查询",
            "缓存",
        ]
    )
    _CHAT_KEYWORDS = frozenset(["你好", "谢谢", "再见", "你是谁", "你能做什么", "hello", "hi"])

    def __init__(self, fake_llm):
        self._llm = fake_llm

    def _keyword(self, query):
        text = query.lower()
        if any(kw in text for kw in self._RAG_KEYWORDS):
            from core.intent.classifier import IntentResult, IntentType

            return IntentResult(intent=IntentType.RAG_QUERY, confidence=0.9, reasoning="keyword")
        if any(kw in text for kw in self._CHAT_KEYWORDS):
            from core.intent.classifier import IntentResult, IntentType

            return IntentResult(intent=IntentType.GENERAL_CHAT, confidence=0.9, reasoning="keyword")
        return None

    async def aclassify(self, query):
        from core.intent.classifier import IntentResult, IntentType

        res = self._keyword(query)
        if res:
            return res
        return IntentResult(
            intent=IntentType.GENERAL_CHAT, confidence=0.7, reasoning="fake default"
        )

    def classify(self, query):
        res = self._keyword(query)
        if res:
            return res
        from core.intent.classifier import IntentResult, IntentType

        return IntentResult(
            intent=IntentType.GENERAL_CHAT, confidence=0.7, reasoning="fake default"
        )
