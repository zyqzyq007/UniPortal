"""
Browser E2E fake installer — injects deterministic fakes into a uvicorn
subprocess so Playwright tests run without Ollama / Milvus and stay hermetic.

WHY THIS EXISTS
---------------
`tests/conftest.py` installs the same fakes, but only as *in-process* pytest
monkeypatches (they mutate the pytest process and drive a `TestClient`).
Playwright's `webServer` spawns a SEPARATE uvicorn process that never imports
conftest, so the real harness / LLM / retriever ran instead and tests only
"passed" by matching degraded response text. See `web/AGENTS.md` §3.

This module is the single source of truth for subprocess fakes. It is loaded
only when `RAG_E2E_FAKES=1` is set, gated by a 3-line hook at the top of
`api/main.py` (production paths skip it entirely). It must run BEFORE the app
is constructed so the patched getters are picked up at first use.

HERMETIC GUARANTEES
-------------------
Every on-disk path (inferences / eval / judge_cache / agent_memory /
parent_store / documents / checkpoints / sessions / milvus) is redirected to a
process-level temp dir under `tmp/e2e_ui_data/`, removed at interpreter exit.
The real `./data/` and `./milvus_data.db` are never touched.

STREAMING CONTRACT
------------------
`_FakeHarness.astream` yields real LangGraph `(mode, data)` tuples — a sequence
of `("custom", {type: status/node/token})` events followed by an
`{"generate": {"messages": [AIMessage]}}` update — so `POST /api/chat/stream`'s
RAG branch assembles a non-empty `full_response`. (The in-process conftest fake
yielded bare dicts, which is why `test_e2e_coverage.py` had an xfail there.)
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile

# ---------------------------------------------------------------------------
# Deterministic fakes (mirror tests/conftest.py, kept self-contained so the
# subprocess does not depend on the pytest fixture machinery).
# ---------------------------------------------------------------------------


class _FakeAIMessage:
    """Minimal stand-in for langchain AIMessage."""

    def __init__(self, content: str):
        self.content = content
        self.type = "ai"
        self.additional_kwargs: dict = {}
        self.tool_calls: list = []


class _FakeLLM:
    """Deterministic chat model. Returns a canned answer for any call."""

    def __init__(self, answer: str = "这是测试回答。仅供参考。"):
        self._answer = answer

    def invoke(self, messages, **kwargs):
        return _FakeAIMessage(self._answer)

    async def ainvoke(self, messages, **kwargs):
        return _FakeAIMessage(self._answer)

    def with_structured_output(self, schema, **kwargs):
        outer = self

        class _Structured:
            def invoke(self_, messages, **kw):
                return outer._structured_result()

            async def ainvoke(self_, messages, **kw):
                return outer._structured_result()

        return _Structured()

    def _structured_result(self):
        try:
            from core.intent.classifier import IntentResult, IntentType

            return IntentResult(
                intent=IntentType.RAG_QUERY,
                confidence=0.9,
                reasoning="fake classifier",
            )
        except Exception:
            return None


class _FakeEmbeddings:
    """Deterministic embedding stand-in for the document-upload path.

    The Playwright upload route (POST /api/documents) indexes into Milvus via
    the REAL MilvusManager.add_documents, which calls get_embeddings(). Without
    this fake, HuggingFaceEmbeddings loads torch + the BGE weights on every
    upload — a multi-second cost that made the documents tests timing-sensitive
    and flaky (and ran real model inference inside a 'hermetic' test). This
    returns tiny deterministic vectors so the upload path is fast and isolated.
    """

    def __init__(self, dim: int = 8):
        self._dim = dim

    def embed_query(self, text: str) -> list[float]:
        # Deterministic, content-derived vector; stable across runs.
        base = [float((hash(text) + i) % 97) / 97.0 for i in range(self._dim)]
        return base

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(t) for t in texts]


class _FakeMilvusManager:
    """In-memory vector-store boundary for upload/delete/health browser flows."""

    def add_documents(self, documents, **kwargs):
        total = len(documents)
        return {"inserted": total, "failed": 0, "total": total, "success_rate": 1.0}

    def delete_by_filter(self, filter_expr):
        return {"deleted_count": 1}

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
        pass


class _FakeRetriever:
    """Returns two canned domain-neutral docs with scores."""

    def retrieve(self, query, top_k=None, filter_expr=None):
        from langchain_core.documents import Document

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


class _FakeHarness:
    """
    Minimal agent harness returning a canned answer + sources.

    `astream` emits LangGraph-shaped `(mode, data)` tuples so the streaming
    endpoint's RAG branch assembles a full response (see module docstring).
    """

    def __init__(self, llm: _FakeLLM, retriever: _FakeRetriever):
        self._llm = llm
        self._retriever = retriever

    async def astart(self):
        return self

    async def aclose(self):
        pass

    def _result(self):
        from langchain_core.messages import AIMessage, ToolMessage

        canned = "Git 合并冲突需要手动编辑冲突标记后提交，仅供参考。"
        return {
            "messages": [
                ToolMessage(
                    content="Git 合并冲突通常由同一文件的多分支改动引起，需手动编辑冲突标记后提交。",
                    tool_call_id="c1",
                ),
                AIMessage(
                    content=canned,
                    additional_kwargs={"reasoning": "fake reasoning", "confidence": 0.85},
                ),
            ],
            "_sources": [
                {
                    "source": "git_guide",
                    "title": "合并冲突排查",
                    "content": "Git 合并冲突通常由同一文件的多分支改动引起",
                    "score": 0.92,
                },
                {
                    "source": "zero_score_fixture",
                    "title": "零分边界",
                    "content": "该测试来源具有真实零分。",
                    "score": 0.0,
                },
                {
                    "source": "full_score_fixture",
                    "title": "满分边界",
                    "content": "该测试来源具有真实满分。",
                    "score": 1.0,
                },
                {
                    "source": "unavailable_score_fixture",
                    "title": "不可用分数边界",
                    "content": "该测试来源没有可用分数。",
                    "score": None,
                },
            ],
            "shared_state": {
                "generation_evidence": [
                    {
                        "content": "Git 合并冲突通常由同一文件的多分支改动引起",
                        "source": "git_guide",
                        "title": "合并冲突排查",
                        "score": 0.92,
                        "metadata": {"score": 0.92},
                    },
                    {
                        "content": "该测试来源具有真实零分。",
                        "source": "zero_score_fixture",
                        "title": "零分边界",
                        "score": 0.0,
                        "metadata": {"score": 0.0},
                    },
                    {
                        "content": "该测试来源具有真实满分。",
                        "source": "full_score_fixture",
                        "title": "满分边界",
                        "score": 1.0,
                        "metadata": {"score": 1.0},
                    },
                    {
                        "content": "该测试来源没有可用分数。",
                        "source": "unavailable_score_fixture",
                        "title": "不可用分数边界",
                        "score": None,
                        "metadata": {},
                    },
                ]
            },
        }

    def invoke(self, query, thread_id=None, **kwargs):
        return self._result()

    async def ainvoke(self, query, thread_id=None, **kwargs):
        return self._result()

    async def astream(self, query, thread_id=None, **kwargs):
        # Mimic the real LangGraph update stream: a retrieve update, then a
        # generate update. The streaming endpoint keys off node names.
        from langchain_core.messages import AIMessage

        canned = "Git 合并冲突需要手动编辑冲突标记后提交，仅供参考。"

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
        yield (
            "custom",
            {"type": "token", "content": canned},
        )
        yield (
            "updates",
            {
                "generate": {
                    "messages": [
                        AIMessage(
                            content=canned,
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
                            },
                            {
                                "content": "该测试来源具有真实零分。",
                                "source": "zero_score_fixture",
                                "title": "零分边界",
                                "score": 0.0,
                                "metadata": {"score": 0.0},
                            },
                            {
                                "content": "该测试来源具有真实满分。",
                                "source": "full_score_fixture",
                                "title": "满分边界",
                                "score": 1.0,
                                "metadata": {"score": 1.0},
                            },
                            {
                                "content": "该测试来源没有可用分数。",
                                "source": "unavailable_score_fixture",
                                "title": "不可用分数边界",
                                "score": None,
                                "metadata": {},
                            },
                        ]
                    },
                }
            },
        )


class _FakeIntentClassifier:
    """Keyword fast-path, falls back to a fake default general_chat."""

    _RAG_KEYWORDS = frozenset(
        [
            # Domain-neutral technical keywords so generic queries route to RAG.
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
        from core.intent.classifier import IntentResult, IntentType

        text = query.lower()
        if any(kw in text for kw in self._RAG_KEYWORDS):
            return IntentResult(intent=IntentType.RAG_QUERY, confidence=0.9, reasoning="keyword")
        if any(kw in text for kw in self._CHAT_KEYWORDS):
            return IntentResult(intent=IntentType.GENERAL_CHAT, confidence=0.9, reasoning="keyword")
        return None

    async def aclassify(self, query):
        from core.intent.classifier import IntentResult, IntentType

        res = self._keyword(query)
        return res or IntentResult(
            intent=IntentType.GENERAL_CHAT, confidence=0.7, reasoning="fake default"
        )

    def classify(self, query):
        from core.intent.classifier import IntentResult, IntentType

        res = self._keyword(query)
        return res or IntentResult(
            intent=IntentType.GENERAL_CHAT, confidence=0.7, reasoning="fake default"
        )


class _FakeSessionMemory:
    """In-memory session store so chat/sessions endpoints work offline."""

    def __init__(self):
        import time

        self._time = time
        self._store: dict = {}

    async def save_message(self, session_id, message):
        self._store.setdefault(session_id, []).append(message)

    async def get_messages(self, session_id, limit=50):
        from langchain_core.messages import AIMessage, HumanMessage

        msgs = self._store.get(session_id, [])
        out = []
        for m in reversed(msgs[-limit:]):
            content = getattr(m, "content", str(m))
            cls = HumanMessage if type(m).__name__ == "HumanMessage" else AIMessage
            out.append(cls(content=content, additional_kwargs={"_timestamp": self._time.time()}))
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
        return session_id in self._store

    async def register_session(self, session_id, title=""):
        self._store.setdefault(session_id, [])

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Hermetic data-dir redirection
# ---------------------------------------------------------------------------

_DATA_ROOT: str | None = None


def _make_data_root() -> str:
    global _DATA_ROOT
    if _DATA_ROOT is None:
        _DATA_ROOT = tempfile.mkdtemp(prefix="e2e_ui_data_")
        os.makedirs(os.path.join(_DATA_ROOT, "eval", "runs"), exist_ok=True)
        os.makedirs(os.path.join(_DATA_ROOT, "eval", "candidates"), exist_ok=True)
        os.makedirs(os.path.join(_DATA_ROOT, "uploads"), exist_ok=True)
        atexit.register(_cleanup)
    return _DATA_ROOT


def _cleanup():
    global _DATA_ROOT
    if _DATA_ROOT and os.path.isdir(_DATA_ROOT):
        shutil.rmtree(_DATA_ROOT, ignore_errors=True)
        _DATA_ROOT = None


def _redirect_paths(root: str):
    """Redirect every on-disk path to the process temp dir (parity with conftest)."""
    from pathlib import Path

    def _set(modpath, attr, value):
        import importlib

        mod = importlib.import_module(modpath)
        setattr(mod, attr, value)

    _set("agent.eval.inference_store", "DEFAULT_DB_PATH", os.path.join(root, "inferences.db"))
    _set("agent.eval.history", "RUNS_DIR", Path(os.path.join(root, "eval", "runs")))
    _set(
        "agent.eval.history",
        "HISTORY_PATH",
        Path(os.path.join(root, "eval", "runs", "history.jsonl")),
    )
    _set("agent.eval.candidates", "CANDIDATES_DIR", Path(os.path.join(root, "eval", "candidates")))
    _set("agent.eval.flywheel", "RETRIEVAL_MISSES_DB", os.path.join(root, "retrieval_misses.db"))
    _set(
        "agent.eval.judge", "DEFAULT_JUDGE_CACHE_PATH", os.path.join(root, "eval", "judge_cache.db")
    )
    _set("agent.memory.store", "DEFAULT_DB_PATH", os.path.join(root, "agent_memory.db"))
    _set("agent.feedback.collector", "DEFAULT_DB_PATH", os.path.join(root, "agent_memory.db"))
    _set("agent.feedback.escalation", "DEFAULT_DB_PATH", os.path.join(root, "agent_memory.db"))
    _set("documents.parent_store", "DEFAULT_DB_PATH", os.path.join(root, "parent_store.db"))
    _set("documents.graph_store", "DEFAULT_DB_PATH", os.path.join(root, "graph_store.db"))
    _set(
        "documents.graph_store",
        "DEFAULT_V1_BACKUP_PATH",
        os.path.join(root, "graph_store_v1_backup.db"),
    )
    _set("documents.document_registry", "DEFAULT_DB_PATH", os.path.join(root, "documents.db"))
    _set(
        "documents.embedding_registry",
        "DEFAULT_DB_PATH",
        os.path.join(root, "embedding_registry.db"),
    )
    _set(
        "agent.harness.orchestrator",
        "DEFAULT_CHECKPOINT_PATH",
        os.path.join(root, "checkpoints.db"),
    )
    _set("api.routers.documents", "UPLOAD_TMP_DIR", os.path.join(root, "uploads"))

    # Session-memory SQLite fallback path (core/memory/redis_memory.py). Redirect
    # it for defense-in-depth even though the session-memory dependency is also
    # overridden below with an in-memory fake (so the real _SQLiteStore is not
    # constructed on this path).
    _set("core.memory.redis_memory", "DEFAULT_SESSION_DB_PATH", os.path.join(root, "sessions.db"))

    # Milvus Lite URI. env_utils reads it once at import; set env + the constant.
    milvus_path = os.path.join(root, "milvus_data.db")
    os.environ["MILVUS_DB_URI"] = milvus_path
    try:
        import utils.env_utils as env_mod

        env_mod.MILVUS_URI = milvus_path
    except Exception:
        pass

    # Reset singletons so subsequent getters pick up the new paths.
    _reset_singletons()


def _reset_singletons():
    """Clear process-wide singletons so they re-create against redirected paths."""
    _reset("agent.harness", "_harness", close="close")
    _reset("agent.memory.store", "_memory_store", close="close")
    _reset("agent.feedback.collector", "_feedback_collector", close="close")
    _reset("agent.feedback.escalation", "_escalation_manager", close="close")
    _reset("documents.parent_store", "_store", close="close")
    _reset("documents.document_registry", "_registry", close="close")
    _reset("documents.embedding_registry", "_registry", close="close")
    _reset("agent.eval.inference_store", "_store", close="close")
    _reset("agent.eval.judge", "_judge", close="close")
    _reset("core.memory.redis_memory", "_memory_instance", close=None)


def _reset(modpath, attr, close=None):
    import importlib

    try:
        mod = importlib.import_module(modpath)
        obj = getattr(mod, attr, None)
        if obj is not None:
            if close and hasattr(obj, close):
                try:
                    getattr(obj, close)()
                except Exception:
                    pass
            setattr(mod, attr, None)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_installed = False


def install():
    """
    Install all subprocess fakes. Idempotent.

    Must run before the FastAPI app is built (the patched getters are picked up
    at first use). Triggered by `RAG_E2E_FAKES=1` from `api/main.py`.
    """
    global _installed
    if _installed:
        return
    _installed = True

    root = _make_data_root()
    _redirect_paths(root)

    llm = _FakeLLM()
    retriever = _FakeRetriever()
    harness = _FakeHarness(llm, retriever)
    memory = _FakeSessionMemory()

    import agent.harness as harness_mod

    harness_mod.get_agent_harness = lambda *a, **k: harness

    import core.intent.classifier as intent_mod

    intent_mod.get_intent_classifier = lambda *a, **k: _FakeIntentClassifier(llm)

    import core.retrieval.hybrid_retriever as hr_mod

    hr_mod.get_hybrid_retriever = lambda *a, **k: retriever

    import models.llm_models as llm_mod

    llm_mod.get_llm = lambda *a, **k: llm
    llm_mod.create_custom_llm = lambda *a, **k: llm

    # Fake the embedding singleton so the document-upload path (MilvusManager
    # .add_documents + MarkdownParser semantic splitter) does NOT load torch /
    # BGE weights inside the Playwright subprocess. Keeps uploads fast and
    # hermetic. EMBEDDING_DIMENSION is read by MilvusConfig.dense_dim at
    # collection creation; the fake vector length must match it.
    fake_embeddings = _FakeEmbeddings()
    try:
        import utils.env_utils as env_mod

        fake_embeddings = _FakeEmbeddings(dim=env_mod.EMBEDDING_DIMENSION)
    except Exception:
        pass
    import models.embedding_models as emb_mod

    emb_mod.get_embeddings = lambda *a, **k: fake_embeddings
    emb_mod.get_local_embeddings = lambda *a, **k: fake_embeddings
    emb_mod._instance = fake_embeddings

    import documents.milvus_db as milvus_mod

    fake_milvus = _FakeMilvusManager()
    milvus_mod.get_milvus_manager = lambda *a, **k: fake_milvus

    from types import SimpleNamespace

    import core.fast_mode as fast_mod

    async def _fake_fast_generate_async(query, **kwargs):
        docs = retriever.retrieve(query)
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

    fast_mod.fast_generate_async = _fake_fast_generate_async

    # Also stub the streaming + sync fast entry points. The chat router's
    # streaming fast branch (chat.py) calls fast_generate_stream directly, which
    # otherwise runs the real `_get_chain(get_llm())` -> `prompt | llm` and
    # crashes because _FakeLLM is not a LangChain Runnable. Emit the same
    # SSE-shaped events the real generator yields so the endpoint assembles a
    # non-empty full_response + sources.
    _FAST_CANNED = "快速模式检索结果。Git 合并冲突需手动编辑冲突标记。仅供参考。"

    async def _fake_fast_generate_stream(query, top_k=3, **kwargs):
        docs = retriever.retrieve(query, top_k=top_k)
        sources = [
            {
                "source": d.metadata["source"],
                "title": d.metadata["title"],
                "content": d.page_content,
                "score": d.metadata["score"],
            }
            for d in docs
        ]
        yield {"type": "token", "content": _FAST_CANNED}
        yield {
            "type": "done",
            "full_response": _FAST_CANNED,
            "sources": sources,
            "processing_time_ms": 30.0,
        }

    def _fake_fast_generate(query, top_k=3, **kwargs):
        docs = retriever.retrieve(query, top_k=top_k)
        return SimpleNamespace(
            answer=_FAST_CANNED,
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

    fast_mod.fast_generate_stream = _fake_fast_generate_stream
    fast_mod.fast_generate = _fake_fast_generate

    # Force inference sampling on so the flywheel capture path is exercised.
    import agent.eval.sampler as sampler_mod

    sampler_mod.should_sample = lambda *a, **k: True
    import agent.eval.capture as capture_mod

    capture_mod.should_sample = lambda *a, **k: True

    # Skip reranker warmup to keep startup deterministic and fast.
    try:
        import utils.env_utils as env_mod

        env_mod.RERANKER_WARMUP = False
        env_mod.RERANKER_ENABLED = False
    except Exception:
        pass

    # Stash the fake session memory so wire_overrides() (called after app build)
    # can install it as a dependency override. The session-memory dependency is
    # the one true FastAPI Depends seam in the chat + sessions routers; we cannot
    # set app.dependency_overrides here because `app` does not exist yet (install
    # runs at the top of api/main.py, before create_app()).
    _PENDING["session_memory"] = memory

    print(f"[e2e_ui] subprocess fakes installed; data root: {root}", flush=True)


_PENDING: dict = {}


def wire_overrides(app) -> None:
    """
    Install session-memory dependency overrides on the built app.

    Called from api/main.py AFTER `app = create_app()` when RAG_E2E_FAKES=1.
    Idempotent; no-op if install() hasn't populated the pending override.
    """
    memory = _PENDING.get("session_memory")
    if memory is None:
        return
    from api.routers.chat import get_session_memory as chat_dep
    from api.routers.sessions import get_session_memory as sess_dep

    app.dependency_overrides[chat_dep] = lambda: memory
    app.dependency_overrides[sess_dep] = lambda: memory
