"""
FastAPI Application for Enterprise RAG Platform

Provides REST API and WebSocket endpoints for:
- Chat/conversation
- Document management
- Session management
- System monitoring
"""

import hashlib
import os
import re
import time
from collections.abc import Mapping

# Browser E2E fake injection (gated, production no-op). When RAG_E2E_FAKES=1 is
# set (only by the Playwright webServer command), install deterministic fakes
# into THIS process so tests run without Ollama/Milvus and stay hermetic. See
# web/AGENTS.md §3 and tests/e2e_ui/_fakes.py. Runs before the app is built so
# patched getters are picked up at first use. PYTEST_RUN=1 only skips the F05
# startup guard below — it does NOT inject fakes.
if os.getenv("RAG_E2E_FAKES", "") == "1":
    from tests.e2e_ui._fakes import install as _install_e2e_fakes

    _install_e2e_fakes()
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from api.middleware.error_handler import ErrorHandlerMiddleware
from api.middleware.tracing import TracingMiddleware
from api.routers import admin, chat, documents, feedback, retrieval, sessions
from core.prompts.profile_prompts import (
    GENERATE_SYSTEM_PROMPT,
    INTENT_CLASSIFICATION_PROMPT,
    PER_DOC_GRADE_HUMAN_PROMPT,
    PER_DOC_GRADE_SYSTEM_PROMPT,
)
from utils.log_utils import log

_DEFAULT_CORS = "http://localhost:5173,http://127.0.0.1:5173"
_DEPLOYMENT_ENVS = frozenset({"development", "production"})
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_LOCAL_ONLY_HOSTS = ["localhost", "127.0.0.1", "[::1]"]


def _parse_allowed_origins(raw: str) -> list[str]:
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    if not origins:
        raise RuntimeError("ALLOWED_ORIGINS must contain at least one origin")
    if "*" in origins:
        raise RuntimeError("ALLOWED_ORIGINS cannot contain '*' when credentials are enabled")
    for origin in origins:
        parsed = urlsplit(origin)
        try:
            _ = parsed.port
        except ValueError as exc:
            raise RuntimeError("ALLOWED_ORIGINS contains an invalid HTTP(S) origin") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError("ALLOWED_ORIGINS contains an invalid HTTP(S) origin")
    return origins


def _is_loopback_origin(origin: str) -> bool:
    import ipaddress

    host = urlsplit(origin).hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _parse_boolean(environment: Mapping[str, str], name: str, *, default: bool) -> bool:
    raw = environment.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise RuntimeError(f"{name} must be an explicit boolean value")


def _validate_production_profile(environment: Mapping[str, str]) -> None:
    profile_name = (environment.get("DOMAIN_PROFILE") or "general").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", profile_name):
        raise RuntimeError("DOMAIN_PROFILE must be a simple profile name")
    profiles_dir = Path(
        environment.get("DOMAIN_PROFILES_DIR")
        or Path(__file__).resolve().parents[1] / "data" / "profiles"
    ).resolve()
    profile_path = (profiles_dir / f"{profile_name}.yaml").resolve()
    if not profile_path.is_relative_to(profiles_dir):
        raise RuntimeError("DOMAIN_PROFILE resolves outside the profile directory")
    if not profile_path.is_file():
        raise RuntimeError("DOMAIN_PROFILE does not resolve to an existing profile")
    try:
        import yaml

        payload = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise RuntimeError("DOMAIN_PROFILE could not be parsed") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("DOMAIN_PROFILE must contain a YAML mapping")
    loaded_name = str(payload.get("name") or "").strip()
    if loaded_name != profile_name:
        raise RuntimeError("DOMAIN_PROFILE requested name does not match the loaded profile")


def validate_deployment_config(environment: Mapping[str, str] | None = None) -> str:
    """Validate deployment-only security invariants without logging secret values."""
    selected = os.environ if environment is None else environment
    deployment_env = (selected.get("DEPLOYMENT_ENV") or "").strip().lower()
    if selected.get("PYTEST_RUN", "") == "1" and deployment_env in {"", "development"}:
        return "test"

    if deployment_env not in _DEPLOYMENT_ENVS:
        raise RuntimeError("DEPLOYMENT_ENV must be explicitly set to development or production")

    local_only = _parse_boolean(selected, "LOCAL_ONLY_DEPLOYMENT", default=False)
    origins_raw = selected.get("ALLOWED_ORIGINS", _DEFAULT_CORS)
    origins = _parse_allowed_origins(origins_raw)
    if deployment_env == "development":
        if not all(_is_loopback_origin(origin) for origin in origins):
            raise RuntimeError("ALLOWED_ORIGINS must remain loopback-only in development")
        return deployment_env

    if not (selected.get("ADMIN_API_KEY") or "").strip():
        raise RuntimeError("ADMIN_API_KEY must be set in production")
    all_loopback = all(_is_loopback_origin(origin) for origin in origins)
    if local_only and not all_loopback:
        raise RuntimeError("ALLOWED_ORIGINS must remain loopback-only in local production")
    if not local_only and all_loopback:
        raise RuntimeError("ALLOWED_ORIGINS must name a non-loopback production origin")
    _validate_production_profile(selected)
    return deployment_env


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown events.
    """
    # Startup
    log.info("=" * 50)
    log.info("Enterprise RAG Platform Starting...")
    log.info("=" * 50)

    deployment_env = validate_deployment_config()
    log.info(f"Deployment environment: {deployment_env}")

    # Initialize core components (lazy)
    from core.fallback.circuit_breaker import get_llm_circuit, get_retriever_circuit
    from core.memory.redis_memory import get_session_memory

    # Pre-initialize session memory
    _ = get_session_memory()

    # Log circuit breaker status
    llm_circuit = get_llm_circuit()
    retriever_circuit = get_retriever_circuit()

    log.info(f"LLM Circuit: {llm_circuit.state.value}")
    log.info(f"Retriever Circuit: {retriever_circuit.state.value}")
    # F-05: aggregate generate + intent prompts so edits to EITHER are
    # detectable via signature drift (REQ-RG-016).
    prompt_sig = hashlib.sha1(
        (
            GENERATE_SYSTEM_PROMPT
            + INTENT_CLASSIFICATION_PROMPT
            + PER_DOC_GRADE_SYSTEM_PROMPT
            + PER_DOC_GRADE_HUMAN_PROMPT
        ).encode("utf-8")
    ).hexdigest()[:12]
    from core.prompts.domain_profile import get_active_profile

    active_profile = get_active_profile()
    log.info(
        f"Domain Profile: {active_profile.name} "
        f"(label={active_profile.prompt_profile_generate}, sig={prompt_sig})"
    )
    from utils.env_utils import runtime_config_fingerprint

    log.info(f"Runtime Config: {runtime_config_fingerprint()['fingerprint']}")

    from agent.harness import get_agent_harness

    await get_agent_harness().astart()

    from utils.env_utils import RERANKER_ENABLED, RERANKER_WARMUP

    if RERANKER_ENABLED and RERANKER_WARMUP:
        from core.retrieval.reranker import get_reranker

        loaded = await get_reranker().aload()
        log.info(f"Reranker warmup: {'ready' if loaded else 'degraded'}")

    log.info("Startup complete!")

    yield

    # Shutdown
    log.info("Shutting down...")

    # Close connections
    from core.memory.redis_memory import get_session_memory

    memory = get_session_memory()
    await memory.close()

    from agent.harness import get_agent_harness

    await get_agent_harness().aclose()

    try:
        from core.retrieval.workflow import reset_retrieval_workflow

        reset_retrieval_workflow()
    except Exception as e:
        log.debug(f"Retrieval workflow close skipped: {e}")

    # Release the hybrid retriever's parallel-retrieval thread pool (F11 —
    # previously a class-level executor with no closer, leaking for the process
    # lifetime; it is now instance-scoped and shut down here).
    try:
        from core.retrieval.hybrid_retriever import get_hybrid_retriever

        get_hybrid_retriever().close()
    except Exception as e:  # noqa: BLE001
        log.debug(f"Hybrid retriever close skipped: {e}")

    # Close the LLMJudge singleton's SQLite verdict-cache connection. The judge
    # is lazily instantiated by the grounding guardrail / PII guardrail / eval
    # flywheel; without this close the connection leaks on every shutdown
    # (surfaced as ResourceWarning: unclosed database).
    try:
        from agent.eval.judge import reset_judge

        reset_judge()
    except Exception as e:  # noqa: BLE001
        log.debug(f"Judge close skipped: {e}")

    # Close the agent-memory / feedback SQLite singletons. They share
    # agent_memory.db; without these closes their connections leak on shutdown.
    try:
        from agent.memory.store import reset_memory_store

        reset_memory_store()
    except Exception as e:  # noqa: BLE001
        log.debug(f"Memory store close skipped: {e}")
    try:
        from agent.feedback.collector import reset_feedback_collector

        reset_feedback_collector()
    except Exception as e:  # noqa: BLE001
        log.debug(f"Feedback collector close skipped: {e}")
    try:
        from agent.feedback.escalation import reset_escalation_manager

        reset_escalation_manager()
    except Exception as e:  # noqa: BLE001
        log.debug(f"Escalation manager close skipped: {e}")
    try:
        from documents.parent_store import reset_parent_store

        reset_parent_store()
    except Exception as e:  # noqa: BLE001
        log.debug(f"Parent store close skipped: {e}")
    try:
        from documents.document_registry import reset_document_registry

        reset_document_registry()
    except Exception as e:  # noqa: BLE001
        log.debug(f"Document registry close skipped: {e}")
    try:
        from documents.embedding_registry import reset_embedding_registry

        reset_embedding_registry()
    except Exception as e:  # noqa: BLE001
        log.debug(f"Embedding registry close skipped: {e}")
    try:
        from core.retrieval.raptor_store import reset_raptor_store

        reset_raptor_store()
    except Exception as e:
        log.debug(f"RAPTOR store close skipped: {e}")
    try:
        from core.retrieval.visual_retriever import reset_visual_retriever

        reset_visual_retriever()
    except Exception as e:
        log.debug(f"Visual retriever close skipped: {e}")

    log.info("Shutdown complete")


def create_app() -> FastAPI:
    """
    Build the FastAPI application (F16 — app factory).

    Centralises ALL app construction — CORS, middleware, routers, OTEL
    instrumentation, health/info routes, and the static frontend mount/SPA
    catch-all — so tests can build the app in-process and (in a follow-up) inject
    singletons via ``app.dependency_overrides`` instead of monkeypatching source
    modules. The module-level ``app = create_app()`` below preserves the
    ``uvicorn api.main:app`` entrypoint.
    """
    configured_root_path = os.getenv("APP_ROOT_PATH", "")
    application = FastAPI(
        title="Enterprise RAG Platform",
        description="企业级RAG智能平台API",
        version="1.0.0",
        lifespan=lifespan,
        root_path=configured_root_path,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware.
    #
    # ``allow_origins=["*"]`` combined with ``allow_credentials=True`` is an
    # invalid and insecure combination per the CORS spec (browsers reject it,
    # and it signals a credential leak if any auth is ever added). Origins are
    # driven by the ``ALLOWED_ORIGINS`` env var (comma-separated). When unset, a
    # safe local-dev default is used; production deployments MUST set it
    # explicitly.
    _allowed_origins = _parse_allowed_origins(os.getenv("ALLOWED_ORIGINS", _DEFAULT_CORS))
    # ``allow_credentials`` is only meaningful with a concrete origin list
    # (never with "*"); keep it on so cookies/auth headers work in production.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if _parse_boolean(os.environ, "LOCAL_ONLY_DEPLOYMENT", default=False):
        application.add_middleware(TrustedHostMiddleware, allowed_hosts=_LOCAL_ONLY_HOSTS)

    # Custom middleware
    application.add_middleware(TracingMiddleware)
    application.add_middleware(ErrorHandlerMiddleware)

    # Include routers
    application.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
    application.include_router(documents.router, prefix="/api/documents", tags=["Documents"])
    application.include_router(sessions.router, prefix="/api/sessions", tags=["Sessions"])
    application.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
    application.include_router(feedback.router, prefix="/api/feedback", tags=["Feedback"])
    application.include_router(retrieval.router, prefix="/api/retrieval", tags=["Retrieval"])

    from core.tracing import instrument_fastapi

    instrument_fastapi(application)

    @application.get("/live", tags=["Health"])
    async def liveness_check():
        """Process liveness; readiness and degradation are reported by /health."""
        return {"status": "alive", "timestamp": time.time()}

    # Health check endpoint
    @application.get("/health", tags=["Health"])
    async def health_check():
        """Health check endpoint."""
        from core.fallback.circuit_breaker import get_llm_circuit, get_retriever_circuit

        llm_circuit = get_llm_circuit()
        retriever_circuit = get_retriever_circuit()
        embedding_compatible = None
        manager = None
        try:
            from documents.milvus_db import get_milvus_manager

            manager = get_milvus_manager()
            milvus_health = manager.health_check()
            embedding_compatible = milvus_health.get("embedding_compatible")
            vector_healthy = bool(milvus_health.get("connected")) and (
                embedding_compatible is not False
            )
        except Exception as exc:  # noqa: BLE001 - health reports degraded, never raises
            log.debug(f"Public health vector check degraded: {exc}")
            vector_healthy = False
        finally:
            if manager is not None:
                try:
                    manager.close()
                except Exception:
                    pass

        from utils.env_utils import runtime_config_fingerprint

        return {
            "status": "healthy" if vector_healthy else "degraded",
            "timestamp": time.time(),
            "circuits": {
                "llm": llm_circuit.state.value,
                "retriever": retriever_circuit.state.value,
            },
            "embedding_compatible": embedding_compatible,
            "runtime_config": runtime_config_fingerprint(),
        }

    # API information endpoint
    @application.get("/api", tags=["Root"])
    async def api_info():
        """Return API information."""
        return {
            "name": "Enterprise RAG Platform",
            "version": "1.0.0",
            "docs": "/docs",
            "health": "/health",
        }

    # Serve the production frontend when `npm run build` has created web/dist.
    web_dist_dir = Path(
        os.getenv("WEB_DIST_DIR", Path(__file__).resolve().parents[1] / "web" / "dist")
    ).resolve()
    web_index = web_dist_dir / "index.html"

    if web_index.is_file():
        assets_dir = web_dist_dir / "assets"
        # A stripping proxy sends /assets/* while ASGI root_path still records
        # the public prefix. Starlette's nested StaticFiles mount otherwise
        # composes root_path twice and returns 404, so the SPA catch-all below
        # serves real asset files for prefixed deployments.
        if assets_dir.is_dir() and not configured_root_path:
            application.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

        @application.get("/{full_path:path}", include_in_schema=False)
        async def frontend(full_path: str):
            """Serve static files and fall back to the Vue SPA entry point."""
            if full_path == "api" or full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="API endpoint not found")
            requested = (web_dist_dir / full_path).resolve()
            if requested.is_relative_to(web_dist_dir) and requested.is_file():
                return FileResponse(requested)
            return FileResponse(web_index)
    else:

        @application.get("/", tags=["Root"])
        async def root():
            """Return API information when the frontend has not been built."""
            return await api_info()

    return application


# Module-level app for `uvicorn api.main:app`. Built via the factory so the
# in-process test client and uvicorn share one construction path.
app = create_app()

# Browser E2E: wire session-memory dependency overrides now that `app` exists.
# No-op unless RAG_E2E_FAKES=1 (install() ran above); pairs with the import-time
# hook at the top of this module. See tests/e2e_ui/_fakes.py.
if os.getenv("RAG_E2E_FAKES", "") == "1":
    from tests.e2e_ui._fakes import wire_overrides as _wire_e2e_overrides

    _wire_e2e_overrides(app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info",
    )
