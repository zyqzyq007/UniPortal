"""Conversation history compression for multi-turn RAG (docs/specs/conversational-rag).

When a session's history exceeds a threshold, the oldest messages are compressed
into a rolling summary so the prompt budget stays bounded. Recent messages are
kept verbatim (they carry the immediate context); only older turns are summarised.

Degrades to hard-truncation (keep recent N) on any LLM failure — never blocks.
"""

from __future__ import annotations

import os

from langchain_core.messages import BaseMessage, SystemMessage

from utils.log_utils import log

__all__ = ["compress_history"]

# Default thresholds (overridable by env).
_DEFAULT_THRESHOLD = 10  # compress when more than this many messages
_DEFAULT_RECENT_KEEP = 6  # keep this many recent messages verbatim

_SUMMARY_PROMPT = (
    "请将以下多轮对话压缩成一段简洁的摘要（不超过 300 字），保留关键事实、已确定的结论和未解决的问题。"
    "只输出摘要，不要添加额外说明。\n\n对话内容:\n{dialog}"
)


def _threshold() -> int:
    try:
        return int(os.getenv("CONVERSATION_SUMMARY_THRESHOLD", str(_DEFAULT_THRESHOLD)))
    except (TypeError, ValueError):
        return _DEFAULT_THRESHOLD


def _recent_keep() -> int:
    try:
        return int(os.getenv("CONVERSATION_RECENT_KEEP", str(_DEFAULT_RECENT_KEEP)))
    except (TypeError, ValueError):
        return _DEFAULT_RECENT_KEEP


def _format_dialog(messages: list[BaseMessage]) -> str:
    """Format messages into a readable dialog for the summariser."""
    lines: list[str] = []
    for msg in messages:
        role = "用户" if msg.type == "human" else ("助手" if msg.type == "ai" else msg.type)
        content = str(msg.content)[:200] if msg.content else ""
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


async def compress_history(
    history: list[BaseMessage],
    threshold: int | None = None,
    recent_keep: int | None = None,
) -> list[BaseMessage]:
    """Compress old conversation history into a rolling summary.

    When ``len(history) > threshold``, the oldest messages (everything except the
    most recent ``recent_keep``) are summarised into a single SystemMessage.
    Returns ``[summary_msg, *recent_msgs]``. When at or below threshold, returns
    history unchanged. On summarisation failure, degrades to hard-truncation
    (keep recent only) — never raises.

    Args:
        history: conversation messages (oldest-first).
        threshold: message count above which compression triggers (env default 10).
        recent_keep: number of recent messages kept verbatim (env default 6).

    Returns:
        Compressed message list (may be shorter than input).
    """
    thr = threshold if threshold is not None else _threshold()
    keep = recent_keep if recent_keep is not None else _recent_keep()

    if len(history) <= thr:
        return history

    to_summarize = history[:-keep] if keep > 0 else history
    recent = history[-keep:] if keep > 0 else []

    if not to_summarize:
        return history

    try:
        from models.llm_models import create_custom_llm

        llm = create_custom_llm(temperature=0.0)
        dialog = _format_dialog(to_summarize)
        prompt = _SUMMARY_PROMPT.format(dialog=dialog[:3000])  # bound input
        resp = await llm.ainvoke(prompt)
        summary_text = str(resp.content).strip()
        if not summary_text:
            raise ValueError("empty summary")
        summary_msg = SystemMessage(content=f"[对话摘要] {summary_text}")
        log.debug(
            f"History compressed: {len(to_summarize)} msgs → 1 summary, kept {len(recent)} recent"
        )
        return [summary_msg, *recent]
    except Exception as e:  # noqa: BLE001 — degrade to hard-truncation
        log.warning(f"History compression failed, degrading to truncation: {e}")
        return recent if recent else history[-thr:]
