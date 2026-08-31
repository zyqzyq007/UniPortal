"""
Chat Router for Enterprise RAG Platform

Handles conversation/chat endpoints.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from core.prompts.profile_prompts import (
    GENERAL_CHAT_SYSTEM_PROMPT,
    GENERATE_SYSTEM_PROMPT,
    INTENT_CLASSIFICATION_PROMPT,
    PER_DOC_GRADE_HUMAN_PROMPT,
    PER_DOC_GRADE_SYSTEM_PROMPT,
)
from utils.log_utils import log
from utils.think_tag_utils import strip_think_tags

router = APIRouter()


def _profile():
    """Active domain profile accessor (cached in domain_profile module).

    Used to derive the prompt_profile label strings (``<label>_<suffix>`` etc.)
    and identity/section behaviour from the configured domain instead of
    hardcoding domain-specific labels.
    """
    from core.prompts.domain_profile import get_active_profile

    return get_active_profile()


# =============================================================================
# Request/Response Models
# =============================================================================


class ChatMessage(BaseModel):
    """Single chat message."""

    role: str = Field(..., description="Message role: user, assistant, or system")
    content: str = Field(..., description="Message content")
    timestamp: float | None = Field(None, description="Unix timestamp when message was saved")


class ChatRequest(BaseModel):
    """Chat request model."""

    message: str = Field(..., description="User message", min_length=1)
    session_id: str | None = Field(None, description="Session ID for conversation continuity")
    stream: bool = Field(False, description="Enable streaming response")
    include_sources: bool = Field(True, description="Include source documents in response")
    mode: Literal["thinking", "fast"] = Field(
        "thinking",
        description="Response mode: 'thinking' uses full graph pipeline, 'fast' uses direct retrieval + generation",
    )


class SourceDocument(BaseModel):
    """Source document in response."""

    content: str
    source: str | None = None
    title: str | None = None
    score: float | None = None
    retrieval_score: float | None = None
    rerank_score: float | None = None
    rerank_applied: bool = False


class ChatResponse(BaseModel):
    """Chat response model."""

    response: str = Field(..., description="Assistant response")
    session_id: str = Field(..., description="Session ID")
    intent: str = Field(..., description="Detected intent")
    sources: list[SourceDocument] = Field(default_factory=list, description="Source documents")
    processing_time_ms: float = Field(..., description="Processing time in milliseconds")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")


class StructuredAnswer(BaseModel):
    """Structured answer extracted from a model response.

    Fields are domain-neutral positional slots. The active domain profile's
    ``section_template`` labels fill them positionally (summary, details, steps,
    notes, sources, gaps); the matching labels are returned alongside as
    ``section_labels`` so the UI can render the profile-specific captions
    (e.g. an aviation profile shows "风险与安全提示" for ``notes``) instead of
    hardcoding generic labels. Profiles without a section template yield
    free-form answers (caller gets None from ``_extract_structured_answer``).
    """

    summary: str = ""
    details: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    notes: str = ""
    sources: list[str] = Field(default_factory=list)
    gaps: str = ""


class ChatHistoryResponse(BaseModel):
    """Chat history response."""

    session_id: str
    messages: list[ChatMessage]
    total_messages: int


# =============================================================================
# Helpers
# =============================================================================


def _confidence_level(confidence: float | None) -> str:
    """Map a numeric confidence to a coarse level for the UI."""
    if confidence is None:
        return "unknown"
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.5:
        return "medium"
    return "low"


def _capture(
    http_request: Request,
    request_message: str,
    answer: str,
    sources: list,
    reasoning: str,
    route: str,
    prompt_profile: str,
    intent: str,
    metadata: dict,
    latency_ms: float,
    trace_id: str,
    session_id: str,
) -> None:
    """
    Capture this inference for the evaluation flywheel (sampled).

    Never raises — capture failures are logged but never break the chat
    response. The sampled trace_id / message_id are written back into
    ``metadata`` so the client can reference them when submitting feedback.
    """
    try:
        from agent.eval.capture import maybe_capture_inference

        maybe_capture_inference(
            request_message=request_message,
            answer=answer,
            sources=sources,
            reasoning=reasoning,
            route=route,
            prompt_profile=prompt_profile,
            intent=intent,
            metadata=metadata,
            latency_ms=latency_ms,
            trace_id=trace_id,
            session_id=session_id,
        )
    except Exception as exc:  # noqa: BLE001 - capture must not break chat
        log.debug(f"inference capture skipped: {exc}")


def _extract_sources(messages: list) -> list[SourceDocument]:
    """Extract source documents from graph result messages."""
    from core.retrieval.scoring import finite_real

    sources = []
    seen = set()
    for msg in messages:
        if isinstance(msg, ToolMessage):
            content = msg.content
            if isinstance(content, list):
                content = " ".join(
                    item.get("text", "") if isinstance(item, dict) else str(item)
                    for item in content
                )
            if content and content not in seen:
                seen.add(content)
                # ToolMessage may not have metadata attribute or it may be None
                meta = getattr(msg, "metadata", None) or {}
                if isinstance(meta, dict):
                    source = meta.get("source")
                    title = meta.get("title")
                    score = finite_real(meta.get("score"))
                else:
                    source, title, score = None, None, None
                if not source:
                    source = _extract_line_value(content, "Source")
                if not title:
                    title = _extract_line_value(content, "Title")
                parsed_score = _extract_line_value(content, "Score")
                if parsed_score:
                    parsed_value = finite_real(parsed_score)
                    if parsed_value is not None:
                        score = parsed_value
                sources.append(
                    SourceDocument(
                        content=content[:500],
                        source=source,
                        title=title,
                        score=score,
                    )
                )
    return sources


def _extract_sources_from_evidence(evidence: list[dict]) -> list[SourceDocument]:
    from core.retrieval.scoring import probability

    sources = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        score = probability(item.get("score"))
        sources.append(
            SourceDocument(
                content=str(item.get("content") or "")[:500],
                source=item.get("source") or metadata.get("source"),
                title=item.get("title") or metadata.get("title"),
                score=score,
                retrieval_score=metadata.get("retrieval_score"),
                rerank_score=metadata.get("rerank_score"),
                rerank_applied=bool(metadata.get("rerank_applied", False)),
            )
        )
    return sources


def _extract_line_value(text: str, key: str) -> str | None:
    """Extract a value from a line like `Key: value`."""
    pattern = rf"(?im)^\s*{re.escape(key)}\s*:\s*(.+?)\s*$"
    match = re.search(pattern, text)
    if match:
        value = match.group(1).strip()
        return value if value else None
    return None


def _extract_section(text: str, title: str, next_titles: list[str]) -> str:
    """Extract section content from a structured answer (【title】...)."""
    marker = f"【{title}】"
    start = text.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    end = len(text)
    for next_title in next_titles:
        next_marker = f"【{next_title}】"
        idx = text.find(next_marker, start)
        if idx >= 0:
            end = min(end, idx)
    return text[start:end].strip()


def _extract_numbered_items(text: str) -> list[str]:
    """Parse numbered items from a section."""
    if not text:
        return []
    items = re.findall(r"(?:^|\n)\s*\d+[.)、]\s*(.+)", text)
    if items:
        return [item.strip() for item in items if item.strip()]
    # Fallback: split by lines when numbering is absent
    return [line.strip("- ").strip() for line in text.splitlines() if line.strip()]


def _active_sections() -> list[str]:
    """Section template from the active domain profile (empty for general)."""
    from core.prompts.domain_profile import get_active_profile

    return list(get_active_profile().section_template)


def _extract_structured_answer(answer: str) -> StructuredAnswer | None:
    """
    Extract structured answer blocks from a generated response.

    The section order is sourced from the active domain profile's
    ``section_template``. When the profile defines no sections (e.g. the
    general profile), this returns None — the answer is treated as free-form.
    """
    section_order = _active_sections()
    if not section_order:
        return None

    extracted: dict[str, str] = {}
    for idx, section in enumerate(section_order):
        extracted[section] = _extract_section(answer, section, section_order[idx + 1 :])

    if not any(extracted.values()):
        return None

    # Map extracted sections into the StructuredAnswer schema. Fields are
    # domain-neutral positional slots; the active profile's section labels fill
    # them positionally (summary, details, steps, notes, sources, gaps). The
    # UI renders the profile's own captions via ``section_labels`` (F-C1), so
    # these field names carry no domain semantics. Profiles with fewer
    # sections simply leave later fields empty.
    vals = list(extracted.values())

    def _at(i: int) -> str:
        return vals[i] if i < len(vals) else ""

    return StructuredAnswer(
        summary=_at(0),
        details=_extract_numbered_items(_at(1)),
        steps=_extract_numbered_items(_at(2)),
        notes=_at(3),
        sources=_extract_numbered_items(_at(4)),
        gaps=_at(5),
    )


def _looks_like_domain_query(message: str) -> bool:
    """
    Heuristic domain-query detection to prevent misrouting.

    Keywords and regex patterns are sourced from the active domain profile,
    so this fast-path matches the configured domain (general by default;
    aviation when ``DOMAIN_PROFILE=aviation_phm``). The general profile has no
    domain keywords/patterns, so this returns False and lets the intent
    classifier decide.
    """
    from core.prompts.domain_profile import get_active_profile

    text = (message or "").lower()
    if not text:
        return False

    profile = get_active_profile()
    # Use domain-specific vocabulary (not the classifier's rag_keywords, which
    # include generic question words like 如何/什么 that would route nearly
    # every query to RAG).
    domain_kws = profile.domain_keywords or profile.rag_keywords
    keywords = [kw.lower() for kw in domain_kws]
    if any(k in text for k in keywords):
        return True

    # Domain-specific query patterns (e.g. chapter codes for a domain that uses them).
    for pattern in profile.query_patterns:
        try:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return True
        except re.error:
            continue

    return False


def _is_identity_capability_query(message: str) -> bool:
    """Detect 'who are you / what can you do' style questions.

    Bug2 Layer ①: detection is driven by the active domain profile's
    ``capability_keywords`` (substring fast-path) and ``capability_patterns``
    (regex fuzzy fallback), NOT a hardcoded regex list. This satisfies the
    "no domain literals in source" invariant (core/prompts/domain_profile.py)
    and lets each domain tune which self-referential questions get the canned
    ``identity_response``. The regex layer is the fuzzy backstop so the
    keyword list need not be exhaustive — Layer ② confidence gate catches
    anything missed here.
    """
    from core.prompts.domain_profile import get_active_profile

    text = (message or "").strip().lower()
    if not text:
        return False
    profile = get_active_profile()
    # Substring match (lowercased; .lower() only matters for English patterns).
    keywords = [kw.lower() for kw in profile.capability_keywords]
    if any(k in text for k in keywords):
        return True
    # Regex fuzzy fallback (IGNORECASE covers English; Chinese has no case).
    for pattern in profile.capability_patterns:
        try:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return True
        except re.error:
            continue
    return False


async def _load_history_for_rag(session_id: str, session_memory) -> list:
    """Load + compress session history for the multi-turn RAG path (REQ-CR-001).

    Reads history from session_memory, compresses via rolling summary when the
    conversation is long, and returns messages oldest-first. Degrades to []
    (single-turn) on any failure — never blocks the RAG path.
    """
    try:
        history = await session_memory.get_messages(session_id)
        history = list(reversed(history))  # oldest-first
        if not history:
            return []
        if _conversational_rag_enabled():
            from core.memory.summarizer import compress_history

            return await compress_history(history)
        return history
    except Exception:  # noqa: BLE001 — degrade to single-turn
        return []


def _conversational_rag_enabled() -> bool:
    """Whether multi-turn RAG (history injection + condensation) is enabled."""
    import os

    return os.getenv("CONVERSATIONAL_RAG_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


async def _run_general_chat(
    message: str, session_id: str, session_memory
) -> tuple[str, list, float | None, bool, str]:
    """Run the general_chat LLM path (no retrieval).

    Bug2 Layer ⑤: shared by the direct general_chat route (intent=general_chat)
    and the sentinel takeover (generate node shunted a misrouted general
    question). Returns (answer, sources, confidence, refused, reasoning).
    """
    from core.prompts.profile_prompts import GENERAL_CHAT_SYSTEM_PROMPT
    from models.llm_models import get_llm

    llm = get_llm()
    history = await session_memory.get_messages(session_id)
    history = list(reversed(history))  # oldest-first
    history_msgs = [SystemMessage(content=GENERAL_CHAT_SYSTEM_PROMPT)]
    for hm in history:
        history_msgs.append(hm)
    history_msgs.append(HumanMessage(content=message))
    response = await llm.ainvoke(history_msgs)
    answer = strip_think_tags(response.content)
    return answer, [], None, False, ""


def _sse(event: dict) -> str:
    """Format an SSE event."""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _build_metadata(
    *,
    route: str,
    prompt_profile: str,
    message_id: str,
    trace_id: str,
    intent_confidence: float,
    intent_reasoning: str,
    source_count: int,
    structured_answer,
    force_rag: bool = False,
    reasoning: str = "",
    confidence=None,
    confidence_level: str | None = None,
    refused: bool = False,
) -> dict:
    """Build the per-response metadata dict shared by chat() and chat_stream().

    Q7 (F-EG-09): both the non-streaming and SSE paths emitted near-identical
    metadata dicts inline, which drifted whenever one was updated without the
    other. Centralizing the shape here makes the contract explicit — every
    route returns the same key set, so the frontend / eval flywheel can rely
    on it. Characterization tests in test_e2e_chat.py pin trace_id,
    prompt_profile, message_id, route, confidence_level, refused.

    ``structured_answer`` carries the domain-neutral positional slots; the
    accompanying ``section_labels`` are the active profile's section captions
    so the UI renders profile-specific labels (e.g. an aviation profile shows
    "风险与安全提示") rather than hardcoded generic text (domain-generalization
    F-C1).
    """
    meta = {
        "intent_confidence": intent_confidence,
        "intent_reasoning": intent_reasoning,
        "source_count": source_count,
        "structured_answer": structured_answer.model_dump() if structured_answer else None,
        "section_labels": _active_sections(),
        "route": route,
        "prompt_profile": prompt_profile,
        "force_rag": force_rag,
        "message_id": message_id,
        "trace_id": trace_id,
    }
    # Answer-trustworthiness fields. The pre-refactor chat() always included
    # these (confidence_level defaults to "unknown" when confidence is None),
    # even on general_chat where there is no grounding signal — the refuse test
    # and frontend rely on confidence_level being present on every route. Keep
    # the same shape so the refactor is behavior-preserving.
    meta["reasoning"] = reasoning
    meta["confidence"] = confidence
    meta["confidence_level"] = (
        confidence_level if confidence_level is not None else _confidence_level(confidence)
    )
    meta["refused"] = refused
    return meta


def _degraded_metadata(*, message_id: str, trace_id: str, error: str) -> dict:
    """Metadata for the circuit-breaker degraded response path (chat + stream)."""
    return {"error": error, "message_id": message_id, "trace_id": trace_id, "route": "degraded"}


# =============================================================================
# Dependencies
# =============================================================================


async def get_session_memory():
    """Get session memory instance."""
    from core.memory.redis_memory import get_session_memory

    return get_session_memory()


async def get_intent_classifier():
    """Get intent classifier instance."""
    from core.intent.classifier import get_intent_classifier

    return get_intent_classifier()


async def get_rag_graph():
    """Get agent harness instance."""
    from agent.harness import get_agent_harness

    return get_agent_harness()


@router.get("/prompt-status")
async def get_prompt_status():
    """Return current prompt profile and signature for runtime verification."""
    # F-05: aggregate generate + intent prompts so edits to EITHER are
    # detectable via signature drift (REQ-RG-016). Previously only the generate
    # prompt was hashed, leaving intent-prompt edits invisible to ops/audit.
    signature = hashlib.sha1(
        (
            GENERATE_SYSTEM_PROMPT
            + INTENT_CLASSIFICATION_PROMPT
            + PER_DOC_GRADE_SYSTEM_PROMPT
            + PER_DOC_GRADE_HUMAN_PROMPT
        ).encode("utf-8")
    ).hexdigest()[:12]
    return {
        "loaded": True,
        "prompt_profile": _profile().prompt_profile_generate,
        "generate_prompt_signature": signature,
        "generate_prompt_preview": GENERATE_SYSTEM_PROMPT[:120],
    }


# =============================================================================
# Endpoints
# =============================================================================


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
    session_memory=Depends(get_session_memory),
):
    """
    Send a message and get a response.

    This endpoint:
    1. Classifies user intent
    2. Routes to appropriate handler
    3. Returns response with sources
    """
    start_time = time.perf_counter()

    # Generate or use existing session ID
    session_id = request.session_id or str(uuid.uuid4())
    route = "general_chat"
    prompt_profile = "base"
    force_rag = False
    # trace_id propagated by the tracing middleware; message_id minted here so
    # feedback can later point back at this exact answer.
    trace_id = (
        getattr(getattr(http_request, "state", None), "trace_id", "") or str(uuid.uuid4())[:16]
    )
    message_id = str(uuid.uuid4())
    # Answer trustworthiness, populated by the generate skill (RAG route).
    gen_confidence = None
    gen_refused = False
    reasoning_text = ""  # initialised for general_chat / fast branches (RAG fills it)

    log.info(f"Chat request: session={session_id[:8]}... message={request.message[:50]}...")

    try:
        if _is_identity_capability_query(request.message):
            answer = _profile().identity_response
            processing_time = (time.perf_counter() - start_time) * 1000
            background_tasks.add_task(
                session_memory.save_message, session_id, HumanMessage(content=request.message)
            )
            background_tasks.add_task(
                session_memory.save_message, session_id, AIMessage(content=answer)
            )
            identity_meta = _build_metadata(
                route="general_chat",
                prompt_profile=_profile().prompt_profile_identity,
                message_id=message_id,
                trace_id=trace_id,
                intent_confidence=1.0,
                intent_reasoning="Identity/capability shortcut",
                source_count=0,
                structured_answer=None,
            )
            _capture(
                http_request,
                request.message,
                answer,
                [],
                "",
                "general_chat",
                _profile().prompt_profile_identity,
                "general_chat",
                identity_meta,
                processing_time,
                trace_id,
                session_id,
            )
            return ChatResponse(
                response=answer,
                session_id=session_id,
                intent="general_chat",
                sources=[],
                processing_time_ms=processing_time,
                metadata=identity_meta,
            )

        # Fast mode: skip intent classification / agent / grading, directly retrieve + generate
        if request.mode == "fast":
            from core.fast_mode import fast_generate_async

            result = await fast_generate_async(request.message)
            processing_time = (time.perf_counter() - start_time) * 1000

            background_tasks.add_task(
                session_memory.save_message, session_id, HumanMessage(content=request.message)
            )
            background_tasks.add_task(
                session_memory.save_message, session_id, AIMessage(content=result.answer)
            )

            fast_sources = [SourceDocument(**s) for s in result.sources]
            fast_meta = _build_metadata(
                route="fast",
                prompt_profile=_profile().prompt_profile_fast,
                message_id=message_id,
                trace_id=trace_id,
                intent_confidence=1.0,
                intent_reasoning="Fast mode (no classification)",
                source_count=result.retrieval_count,
                structured_answer=None,
            )
            # Fast mode surfaces retrieval/generation timing for the client.
            fast_meta["retrieval_time_ms"] = result.retrieval_time_ms
            fast_meta["generation_time_ms"] = result.generation_time_ms
            _capture(
                http_request,
                request.message,
                result.answer,
                fast_sources,
                "",
                "fast",
                _profile().prompt_profile_fast,
                "rag_query",
                fast_meta,
                processing_time,
                trace_id,
                session_id,
            )
            return ChatResponse(
                response=result.answer,
                session_id=session_id,
                intent="rag_query",
                sources=fast_sources,
                processing_time_ms=processing_time,
                metadata=fast_meta,
            )

        # Step 1: Intent classification
        from core.intent.classifier import get_intent_classifier

        intent_classifier = get_intent_classifier()
        intent_result = await intent_classifier.aclassify(request.message)

        log.info(f"Intent classified: {intent_result.intent.value}")

        # Step 2: Route based on intent + confidence + domain heuristic.
        # Bug2 Layer ②: a low-confidence rag_query falls back to general_chat
        # rather than misrouting ambiguous capability/general questions into
        # retrieval (the original bug: '你能解决什么问题' was tagged rag_query).
        # The domain-query override is a stronger signal and still forces RAG.
        from utils.env_utils import LOW_INTENT_THRESHOLD

        intent_val = intent_result.intent.value
        use_rag = intent_val != "general_chat" and intent_result.confidence >= LOW_INTENT_THRESHOLD
        force_rag = False
        if not use_rag and _looks_like_domain_query(request.message):
            use_rag = True
            force_rag = True
            log.info("Intent override: forcing RAG route for domain-like query")

        if not use_rag:
            # Direct LLM response without retrieval
            answer, sources, _gen_conf, _gen_refused, reasoning_text = await _run_general_chat(
                request.message, session_id, session_memory
            )
            route = "general_chat"
            prompt_profile = _profile().prompt_profile_general

        else:
            # RAG pipeline with retrieval
            from agent.harness import get_agent_harness

            harness = get_agent_harness()

            # REQ-CR-001: load compressed conversation history for multi-turn RAG
            # (coreference resolution in rewrite + context-aware generation).
            rag_history = await _load_history_for_rag(session_id, session_memory)

            # Bug2 Layer ⑤: inject intent_confidence so GenerateSkill's A/B
            # shunt can distinguish a misrouted general question (low conf) from
            # a genuine KB miss (high conf). The merge_shared_state reducer
            # propagates it to the generate node.
            result = await harness.ainvoke(
                request.message,
                thread_id=session_id,
                shared_state={
                    "intent_confidence": intent_result.confidence,
                    "intent": intent_val,
                },
                history=rag_history,
            )

            # Bug2 Layer ⑤ sentinel takeover: if the generate node shunted a
            # misrouted general question, re-run the general_chat LLM path.
            shared_after = result.get("shared_state") or {}
            if shared_after.get("fallback_general_chat"):
                answer, sources, gen_conf, gen_refused, reasoning_text = await _run_general_chat(
                    request.message, session_id, session_memory
                )
                route = "general_chat"
                prompt_profile = _profile().prompt_profile_general
                rag_meta = _build_metadata(
                    route=route,
                    prompt_profile=prompt_profile,
                    message_id=message_id,
                    trace_id=trace_id,
                    intent_confidence=intent_result.confidence,
                    intent_reasoning=intent_result.reasoning or "",
                    source_count=0,
                    structured_answer=None,
                )
                rag_meta["reasoning"] = reasoning_text
                rag_meta["confidence"] = gen_conf
                rag_meta["refused"] = gen_refused
                processing_time = (time.perf_counter() - start_time) * 1000
                background_tasks.add_task(
                    session_memory.save_message,
                    session_id,
                    HumanMessage(content=request.message),
                )
                background_tasks.add_task(
                    session_memory.save_message, session_id, AIMessage(content=answer)
                )
                _capture(
                    http_request,
                    request.message,
                    answer,
                    [],
                    "",
                    route,
                    prompt_profile,
                    "general_chat",
                    rag_meta,
                    processing_time,
                    trace_id,
                    session_id,
                )
                return ChatResponse(
                    response=answer,
                    session_id=session_id,
                    intent="general_chat",
                    sources=[],
                    processing_time_ms=processing_time,
                    metadata=rag_meta,
                )

            # Extract response and sources
            messages = result.get("messages", [])
            reasoning_text = ""
            gen_confidence = None
            gen_refused = False
            if messages:
                last_message = messages[-1]
                raw = (
                    last_message.content if hasattr(last_message, "content") else str(last_message)
                )
                answer = strip_think_tags(raw)
                # Extract Qwen3 reasoning from generate node
                if hasattr(last_message, "additional_kwargs"):
                    reasoning_text = last_message.additional_kwargs.get("reasoning", "") or ""
                    gen_confidence = last_message.additional_kwargs.get("confidence")
                    gen_refused = bool(last_message.additional_kwargs.get("refused", False))
            else:
                answer = "抱歉，无法生成回答。"

            generation_evidence = shared_after.get("generation_evidence")
            sources = (
                _extract_sources_from_evidence(generation_evidence)
                if isinstance(generation_evidence, list)
                else _extract_sources(messages)
            )
            route = "rag"
            prompt_profile = _profile().prompt_profile_generate

        # Calculate processing time
        processing_time = (time.perf_counter() - start_time) * 1000

        # Save to session memory (background task)
        background_tasks.add_task(
            session_memory.save_message, session_id, HumanMessage(content=request.message)
        )
        background_tasks.add_task(
            session_memory.save_message, session_id, AIMessage(content=answer)
        )

        structured_answer = _extract_structured_answer(answer)

        main_meta = _build_metadata(
            route=route,
            prompt_profile=prompt_profile,
            message_id=message_id,
            trace_id=trace_id,
            intent_confidence=intent_result.confidence,
            intent_reasoning=intent_result.reasoning,
            source_count=len(sources),
            structured_answer=structured_answer,
            force_rag=force_rag,
            reasoning=reasoning_text,
            confidence=gen_confidence,
            refused=gen_refused,
        )
        _capture(
            http_request,
            request.message,
            answer,
            sources,
            reasoning_text,
            route,
            prompt_profile,
            intent_result.intent.value,
            main_meta,
            processing_time,
            trace_id,
            session_id,
        )
        return ChatResponse(
            response=answer,
            session_id=session_id,
            intent=intent_result.intent.value,
            sources=sources,
            processing_time_ms=processing_time,
            metadata=main_meta,
        )

    except Exception as e:
        log.error(f"Chat error: {e}")

        # Check if circuit breaker is open
        from core.fallback.circuit_breaker import CircuitBreakerError
        from core.fallback.degradation import get_degradation_handler

        if isinstance(e, CircuitBreakerError):
            handler = get_degradation_handler()
            degraded = handler.generate_degraded_response(request.message, str(e))
            degraded_time = (time.perf_counter() - start_time) * 1000
            degraded_meta = _degraded_metadata(
                message_id=message_id, trace_id=trace_id, error=str(e)
            )
            # Degraded responses are always sampled (importance sampling).
            _capture(
                http_request,
                request.message,
                degraded.content,
                [],
                "",
                "degraded",
                "degraded",
                "degraded",
                degraded_meta,
                degraded_time,
                trace_id,
                session_id,
            )
            return ChatResponse(
                response=degraded.content,
                session_id=session_id,
                intent="degraded",
                sources=[],
                processing_time_ms=degraded_time,
                metadata=degraded_meta,
            )

        raise HTTPException(status_code=500, detail="服务暂时不可用，请稍后重试")


@router.get("/history/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(
    session_id: str,
    limit: int = Query(20, ge=1, le=200),
    session_memory=Depends(get_session_memory),
):
    """Get chat history for a session."""
    try:
        messages = await session_memory.get_messages(session_id, limit=limit)

        # Messages are stored newest-first via lpush; reverse to chronological order
        messages = list(reversed(messages))

        chat_messages = []
        for msg in messages:
            role = "user" if msg.type == "human" else "assistant"
            ts = (msg.additional_kwargs or {}).pop("_timestamp", None)
            chat_messages.append(
                ChatMessage(
                    role=role,
                    content=msg.content,
                    timestamp=ts,
                )
            )

        return ChatHistoryResponse(
            session_id=session_id,
            messages=chat_messages,
            total_messages=len(chat_messages),
        )

    except Exception as e:
        log.error(f"Failed to get chat history: {e}")
        raise HTTPException(status_code=500, detail="服务暂时不可用，请稍后重试")


@router.delete("/session/{session_id}")
async def clear_session(
    session_id: str,
    session_memory=Depends(get_session_memory),
):
    """Clear a chat session."""
    try:
        await session_memory.clear_session(session_id)
        return {"status": "success", "message": f"Session {session_id} cleared"}
    except Exception as e:
        log.error(f"Failed to clear session: {e}")
        raise HTTPException(status_code=500, detail="服务暂时不可用，请稍后重试")


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    session_memory=Depends(get_session_memory),
):
    """
    Streaming chat endpoint using RAGGraph.

    Returns response as SSE stream with progress events:
    - session: Session info
    - intent: Intent classification result
    - status: Processing status updates
    - node: Current graph node being executed
    - token: Streaming token content
    - done: Completion signal
    - error: Error information
    """
    session_id = request.session_id or str(uuid.uuid4())

    async def generate():
        start_time = time.perf_counter()
        # Per-request identifiers, mirrored into every done-payload metadata so
        # the frontend can POST /api/feedback with the trace_id needed to drive
        # the eval flywheel (on_negative_feedback) and the message_id to target
        # the message. The non-stream chat() path sets the same pair.
        message_id = str(uuid.uuid4())
        trace_id = (
            getattr(getattr(request, "state", None), "trace_id", "") or str(uuid.uuid4())[:16]
        )
        try:
            # Send session info
            yield _sse({"type": "session", "session_id": session_id})

            if _is_identity_capability_query(request.message):
                answer = _profile().identity_response
                yield _sse(
                    {
                        "type": "intent",
                        "intent": "general_chat",
                        "confidence": 1.0,
                        "route": "general_chat",
                        "force_rag": False,
                    }
                )
                yield _sse({"type": "status", "message": "正在返回平台能力说明..."})
                yield _sse({"type": "token", "content": answer})
                await session_memory.save_message(session_id, HumanMessage(content=request.message))
                await session_memory.save_message(session_id, AIMessage(content=answer))
                yield _sse(
                    {
                        "type": "done",
                        "full_response": answer,
                        "sources": [],
                        "processing_time_ms": (time.perf_counter() - start_time) * 1000,
                        "metadata": _build_metadata(
                            route="general_chat",
                            prompt_profile=_profile().prompt_profile_identity,
                            message_id=message_id,
                            trace_id=trace_id,
                            intent_confidence=1.0,
                            intent_reasoning="Identity/capability shortcut",
                            source_count=0,
                            structured_answer=None,
                        ),
                    }
                )
                return

            # Fast mode: direct retrieve + stream generate
            if request.mode == "fast":
                from core.fast_mode import fast_generate_stream

                yield _sse(
                    {
                        "type": "intent",
                        "intent": "rag_query",
                        "confidence": 1.0,
                        "route": "fast",
                        "force_rag": False,
                    }
                )
                yield _sse({"type": "status", "message": "正在检索知识库..."})

                full_response = ""
                sources_data = []
                async for event in fast_generate_stream(request.message):
                    if event["type"] == "token":
                        if not full_response:
                            yield _sse({"type": "node", "name": "fast_generate"})
                            yield _sse({"type": "status", "message": "正在生成回答..."})
                        full_response += event["content"]
                        yield _sse({"type": "token", "content": event["content"]})
                    elif event["type"] == "done":
                        sources_data = event.get("sources", [])

                await session_memory.save_message(session_id, HumanMessage(content=request.message))
                await session_memory.save_message(session_id, AIMessage(content=full_response))

                structured_answer = _extract_structured_answer(full_response)
                yield _sse(
                    {
                        "type": "done",
                        "full_response": full_response,
                        "sources": sources_data,
                        "processing_time_ms": (time.perf_counter() - start_time) * 1000,
                        "metadata": _build_metadata(
                            route="fast",
                            prompt_profile=_profile().prompt_profile_fast,
                            message_id=message_id,
                            trace_id=trace_id,
                            intent_confidence=1.0,
                            intent_reasoning="Fast mode (no classification)",
                            source_count=len(sources_data),
                            structured_answer=structured_answer,
                        ),
                    }
                )
                return

            # Step 1: Intent classification
            yield _sse({"type": "status", "message": "正在分析意图..."})

            from core.intent.classifier import get_intent_classifier

            intent_classifier = get_intent_classifier()
            intent_result = await intent_classifier.aclassify(request.message)
            # Bug2 Layer ②: confidence-gated routing (see non-stream comment).
            from utils.env_utils import LOW_INTENT_THRESHOLD

            intent_val = intent_result.intent.value
            use_rag = (
                intent_val != "general_chat" and intent_result.confidence >= LOW_INTENT_THRESHOLD
            )
            force_rag = False
            if not use_rag and _looks_like_domain_query(request.message):
                use_rag = True
                force_rag = True
                yield _sse({"type": "status", "message": "检测为专业问题，已切换知识库检索模式..."})

            yield _sse(
                {
                    "type": "intent",
                    "intent": intent_result.intent.value,
                    "confidence": intent_result.confidence,
                    "route": "rag" if use_rag else "general_chat",
                    "force_rag": force_rag,
                }
            )

            # Step 2: Route based on intent
            if not use_rag:
                # Direct LLM streaming (no RAG)
                yield _sse({"type": "status", "message": "正在生成回答..."})

                from models.llm_models import get_llm

                llm = get_llm()

                # Load conversation history for multi-turn context
                history = await session_memory.get_messages(session_id)
                history = list(reversed(history))  # oldest-first

                history_msgs = [SystemMessage(content=GENERAL_CHAT_SYSTEM_PROMPT)]
                for hm in history:
                    history_msgs.append(hm)
                history_msgs.append(HumanMessage(content=request.message))

                full_response = ""
                async for chunk in llm.astream(history_msgs):
                    if hasattr(chunk, "content") and chunk.content:
                        full_response += chunk.content
                        yield _sse({"type": "token", "content": chunk.content})

                full_response = strip_think_tags(full_response)

                # Save to session
                await session_memory.save_message(session_id, HumanMessage(content=request.message))
                await session_memory.save_message(session_id, AIMessage(content=full_response))

                structured_answer = _extract_structured_answer(full_response)
                done_payload = {
                    "type": "done",
                    "full_response": full_response,
                    "sources": [],
                    "processing_time_ms": (time.perf_counter() - start_time) * 1000,
                    # Inline dict mirrors _build_metadata() for this stream-only
                    # general_chat branch (F-07). Keys renamed to match the
                    # centralized contract; section_labels added for UI parity.
                    "metadata": {
                        "intent_confidence": intent_result.confidence,
                        "intent_reasoning": intent_result.reasoning,
                        "source_count": 0,
                        "structured_answer": (
                            structured_answer.model_dump() if structured_answer else None
                        ),
                        "section_labels": _active_sections(),
                        "route": "general_chat",
                        "prompt_profile": _profile().prompt_profile_general,
                        "force_rag": force_rag,
                        "message_id": message_id,
                        "trace_id": trace_id,
                    },
                }

            else:
                # RAG pipeline via graph streaming
                from agent.harness import get_agent_harness

                harness = get_agent_harness()

                # REQ-CR-001: load compressed history for multi-turn RAG.
                rag_history = await _load_history_for_rag(session_id, session_memory)

                full_response = ""
                collected_messages = []
                # Answer trustworthiness, captured from the generate node's
                # additional_kwargs (parity with the non-streaming path).
                gen_confidence = None
                gen_refused = False
                # Bug2 Layer ⑤: accumulate the fallback sentinel across node
                # outputs (F-09: the loop previously ignored shared_state).
                fallback_general_chat = False
                generation_evidence = []

                async for event in harness.astream(
                    request.message,
                    thread_id=session_id,
                    stream_mode=["updates", "custom"],
                    # Bug2 Layer ⑤: inject intent_confidence for the A/B shunt.
                    shared_state={
                        "intent_confidence": intent_result.confidence,
                        "intent": intent_val,
                    },
                    history=rag_history,
                ):
                    if isinstance(event, tuple) and len(event) == 2 and event[0] == "custom":
                        custom_event = event[1]
                        if custom_event.get("type") == "token":
                            token = custom_event.get("content", "")
                            if not full_response:
                                yield _sse({"type": "node", "name": "generate"})
                                yield _sse({"type": "status", "message": "正在生成回答..."})
                            full_response += token
                            yield _sse({"type": "token", "content": token})
                        continue

                    if isinstance(event, tuple) and len(event) == 2:
                        _, event = event

                    # B2: a combined stream_mode can yield a non-dict payload
                    # for some modes; guard so .items() never raises and
                    # aborts the stream mid-generation.
                    if not isinstance(event, dict):
                        continue

                    for node_name, node_output in event.items():
                        # Bug2 Layer ⑤ sentinel accumulation (F-09).
                        if (node_output.get("shared_state") or {}).get("fallback_general_chat"):
                            fallback_general_chat = True
                        shared_update = node_output.get("shared_state") or {}
                        if "generation_evidence" in shared_update:
                            generation_evidence = shared_update["generation_evidence"]
                        if node_name == "agent":
                            messages = node_output.get("messages", [])
                            if messages:
                                msg = messages[-1]
                                if hasattr(msg, "tool_calls") and msg.tool_calls:
                                    yield _sse({"type": "node", "name": "retrieve"})
                                    yield _sse({"type": "status", "message": "正在检索知识库..."})
                                elif hasattr(msg, "content") and msg.content:
                                    full_response = msg.content
                                    yield _sse({"type": "status", "message": "正在生成回答..."})
                                    yield _sse({"type": "token", "content": full_response})

                        elif node_name == "retrieve":
                            collected_messages.extend(node_output.get("messages", []))
                            yield _sse({"type": "node", "name": "grade"})
                            yield _sse({"type": "status", "message": "正在评估文档相关性..."})

                        elif node_name == "rewrite":
                            yield _sse({"type": "node", "name": "rewrite"})
                            yield _sse({"type": "status", "message": "正在优化查询..."})
                            yield _sse({"type": "node", "name": "agent"})

                        elif node_name == "generate":
                            yield _sse({"type": "node", "name": "generate"})
                            yield _sse({"type": "status", "message": "正在生成回答..."})
                            messages = node_output.get("messages", [])
                            if messages:
                                gen_msg = messages[-1]
                                answer = strip_think_tags(gen_msg.content)
                                # Capture answer trustworthiness (B4).
                                ak = getattr(gen_msg, "additional_kwargs", {}) or {}
                                if ak.get("confidence") is not None:
                                    gen_confidence = ak.get("confidence")
                                if ak.get("refused"):
                                    gen_refused = True
                                if not full_response:
                                    full_response = answer
                                    yield _sse({"type": "token", "content": answer})
                                elif answer.startswith(full_response):
                                    suffix = answer[len(full_response) :]
                                    if suffix:
                                        full_response = answer
                                        yield _sse({"type": "token", "content": suffix})
                                else:
                                    full_response = answer

                # Bug2 Layer ⑤ streaming sentinel takeover (F-07/F-09): the
                # generate node shunted a misrouted general question (empty
                # message + fallback_general_chat sentinel). Re-run the
                # general_chat LLM stream so the user gets a real answer, and
                # emit the done payload with route=general_chat (NOT rag).
                if fallback_general_chat:
                    yield _sse({"type": "status", "message": "正在重新组织回答..."})
                    from models.llm_models import get_llm

                    llm = get_llm()
                    history = await session_memory.get_messages(session_id)
                    history = list(reversed(history))
                    history_msgs = [SystemMessage(content=GENERAL_CHAT_SYSTEM_PROMPT)]
                    history_msgs.extend(history)
                    history_msgs.append(HumanMessage(content=request.message))
                    full_response = ""
                    async for chunk in llm.astream(history_msgs):
                        if hasattr(chunk, "content") and chunk.content:
                            full_response += chunk.content
                            yield _sse({"type": "token", "content": chunk.content})
                    full_response = strip_think_tags(full_response)
                    await session_memory.save_message(
                        session_id, HumanMessage(content=request.message)
                    )
                    await session_memory.save_message(session_id, AIMessage(content=full_response))
                    processing_time_ms = (time.perf_counter() - start_time) * 1000
                    rag_meta = _build_metadata(
                        route="general_chat",
                        prompt_profile=_profile().prompt_profile_general,
                        message_id=message_id,
                        trace_id=trace_id,
                        intent_confidence=intent_result.confidence,
                        intent_reasoning=intent_result.reasoning or "",
                        source_count=0,
                        structured_answer=None,
                        force_rag=force_rag,
                    )
                    yield _sse(
                        {
                            "type": "done",
                            "full_response": full_response,
                            "sources": [],
                            "processing_time_ms": processing_time_ms,
                            "metadata": rag_meta,
                        }
                    )
                    return

                # Save to session
                await session_memory.save_message(session_id, HumanMessage(content=request.message))
                await session_memory.save_message(session_id, AIMessage(content=full_response))

                sources = (
                    _extract_sources_from_evidence(generation_evidence)
                    if isinstance(generation_evidence, list)
                    else _extract_sources(collected_messages)
                )
                structured_answer = _extract_structured_answer(full_response)
                # Capture the streamed RAG inference into the eval flywheel
                # (parity with the non-streaming chat() path). Without this,
                # negative feedback on a streamed answer has no inference to
                # re-judge. Best-effort: never blocks the stream.
                processing_time_ms = (time.perf_counter() - start_time) * 1000
                rag_meta = _build_metadata(
                    route="rag",
                    prompt_profile=_profile().prompt_profile_generate,
                    message_id=message_id,
                    trace_id=trace_id,
                    intent_confidence=intent_result.confidence,
                    intent_reasoning=intent_result.reasoning,
                    source_count=len(sources),
                    structured_answer=structured_answer,
                    force_rag=force_rag,
                    confidence=gen_confidence,
                    refused=gen_refused,
                )
                try:
                    from agent.eval.capture import maybe_capture_inference

                    maybe_capture_inference(
                        request_message=request.message,
                        answer=full_response,
                        sources=[s.model_dump() for s in sources],
                        reasoning="",
                        route="rag",
                        prompt_profile=_profile().prompt_profile_generate,
                        intent="rag_query",
                        metadata=rag_meta,
                        latency_ms=processing_time_ms,
                        trace_id=trace_id,
                        session_id=session_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.debug(f"stream inference capture skipped: {exc}")
                done_payload = {
                    "type": "done",
                    "full_response": full_response,
                    "sources": [s.model_dump() for s in sources],
                    "processing_time_ms": processing_time_ms,
                    "metadata": rag_meta,
                }

            # Send completion signal
            yield _sse(done_payload)

        except Exception as e:
            # Log the full detail server-side, but send the client a generic
            # message — str(e) may contain internal paths, DB URIs, or stack
            # internals (B3 information-disclosure hardening).
            log.error(f"Stream error: {e}", exc_info=True)
            yield _sse({"type": "error", "message": "服务暂时不可用，请稍后重试"})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
