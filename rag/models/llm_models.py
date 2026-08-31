"""
LLM Models Configuration

Provides language model instances and tools with lazy initialization
and configurable parameters.

Optimized for low-resource servers with:
- Lazy initialization of model instances
- Configurable model parameters
- Connection pooling and reuse
- Comprehensive error handling

Usage:
    >>> from models.llm_models import get_llm, llm
    >>> response = llm.invoke("Hello")
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from langchain_core.caches import InMemoryCache
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from utils.env_utils import (
    LLM_MAX_RETRIES,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_TIMEOUT,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
)

# LLM response cache — avoids re-calling the API for identical prompts
_llm_cache = InMemoryCache()
from utils.log_utils import log

__all__ = [
    "LLMConfig",
    "get_llm",
    "get_web_search_tool",
]


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class LLMConfig:
    """
    Configuration for language models.

    Optimized for low-resource servers with conservative defaults.
    """

    # Model settings
    model_name: str = field(default_factory=lambda: LLM_MODEL)
    temperature: float = LLM_TEMPERATURE
    max_tokens: int = LLM_MAX_TOKENS
    timeout: float = LLM_TIMEOUT
    max_retries: int = LLM_MAX_RETRIES

    # API settings
    api_key: str | None = None
    base_url: str | None = None

    def __post_init__(self):
        if self.api_key is None:
            self.api_key = OPENAI_API_KEY or "ollama"
        if self.base_url is None:
            self.base_url = OPENAI_BASE_URL or "http://localhost:11434/v1"
        if LLM_MODEL is not None:
            self.model_name = LLM_MODEL


@dataclass
class WebSearchConfig:
    """Configuration for web search tool."""

    max_results: int = 2
    api_key: str | None = None

    def __post_init__(self):
        if self.api_key is None:
            self.api_key = os.environ.get("TAVILY_API_KEY")


# =============================================================================
# Model Factories
# =============================================================================

# Global instances (lazy loaded)
_llm_instance: BaseChatModel | None = None
_web_search_instance = None


def get_llm(config: LLMConfig | None = None) -> BaseChatModel:
    """
    Get or create the LLM instance.

    Uses singleton pattern for efficiency - same instance is reused.

    Args:
        config: Optional configuration (uses defaults if not provided)

    Returns:
        ChatOpenAI instance

    Example:
        >>> llm = get_llm()
        >>> response = llm.invoke("Hello")
    """
    global _llm_instance

    if _llm_instance is None or config is not None:
        cfg = config or LLMConfig()

        log.info(f"Creating LLM instance: model={cfg.model_name}")

        _llm_instance = ChatOpenAI(
            model=cfg.model_name,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            timeout=cfg.timeout,
            max_retries=cfg.max_retries,
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            cache=_llm_cache,
        )

        log.debug("LLM instance created successfully")

    return _llm_instance


def get_web_search_tool(config: WebSearchConfig | None = None):
    """
    Get or create the web search tool instance.

    Args:
        config: Optional configuration (uses defaults if not provided)

    Returns:
        TavilySearch instance
    """
    global _web_search_instance

    if _web_search_instance is None or config is not None:
        try:
            from langchain_tavily import TavilySearch

            cfg = config or WebSearchConfig()

            log.info(f"Creating web search tool: max_results={cfg.max_results}")

            _web_search_instance = TavilySearch(
                max_results=cfg.max_results,
                tavily_api_key=cfg.api_key,
            )

            log.debug("Web search tool created successfully")

        except ImportError:
            log.warning("langchain_tavily not installed, web search unavailable")
            return None

    return _web_search_instance


def reset_llm():
    """Reset the LLM instance (useful for testing or reconfiguration)."""
    global _llm_instance
    _llm_instance = None
    log.debug("LLM instance reset")


def reset_web_search():
    """Reset the web search instance."""
    global _web_search_instance
    _web_search_instance = None
    log.debug("Web search instance reset")


# =============================================================================
# Convenience functions
# =============================================================================


def create_custom_llm(
    model_name: str = LLM_MODEL, temperature: float = LLM_TEMPERATURE, **kwargs
) -> BaseChatModel:
    """
    Create a custom LLM instance with specified parameters.

    This always creates a new instance, unlike get_llm which reuses.

    Args:
        model_name: Model to use
        temperature: Sampling temperature
        **kwargs: Additional ChatOpenAI parameters

    Returns:
        New ChatOpenAI instance
    """
    config = LLMConfig(model_name=model_name, temperature=temperature, **kwargs)

    return ChatOpenAI(
        model=config.model_name,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        timeout=config.timeout,
        max_retries=config.max_retries,
        api_key=config.api_key,
        base_url=config.base_url,
    )


# =============================================================================
# CLI for testing
# =============================================================================

if __name__ == "__main__":
    print("Testing LLM connection...")

    try:
        # Test basic invocation
        response = get_llm().invoke("Say 'Hello' in one word.")
        print(f"Response: {response.content}")
        print("\nLLM connection successful!")

    except Exception as e:
        print(f"LLM connection failed: {e}")
