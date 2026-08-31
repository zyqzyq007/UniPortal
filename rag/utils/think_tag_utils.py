"""
Qwen3 Thinking Utilities

Handles Qwen3's dual-mode reasoning:
- Thinking mode: reasoning content in Ollama's `reasoning` field (streaming: delta.reasoning)
- Non-thinking mode: add /no_think suffix to suppress reasoning
- Defensive strip of <think...> tags that may leak through
"""

import re

_THINK_PATTERN = re.compile(r"<think[\s\S]*?</think\s*>", re.DOTALL)

NO_THINK_SUFFIX = " /no_think"


def strip_think_tags(text: str) -> str:
    """Remove Qwen3 <think...</think< tags from text."""
    if not text:
        return text
    return _THINK_PATTERN.sub("", text).strip()


def build_fast_mode_prompt(question: str) -> str:
    """Append /no_think to suppress Qwen3 reasoning in fast mode."""
    return question.rstrip() + NO_THINK_SUFFIX
