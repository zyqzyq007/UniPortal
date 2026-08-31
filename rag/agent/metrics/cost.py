"""
Cost Calculator

Estimates costs based on token usage and a pricing table.
Local models (e.g., qwen3:14b) are free but the table is structured
for future cloud model integration.
"""

from __future__ import annotations

from agent.metrics.types import TokenUsage

# Price per 1M tokens in USD. Local models are free.
PRICING_TABLE: dict[str, dict[str, float]] = {
    "qwen3:14b": {
        "prompt": 0.0,
        "completion": 0.0,
    },
    # Future cloud models can be added here:
    # "gpt-4o": {"prompt": 2.50, "completion": 10.00},
    # "claude-sonnet-4-20250514": {"prompt": 3.00, "completion": 15.00},
}


class CostCalculator:
    """Calculate estimated cost for LLM token usage."""

    def estimate_cost(self, usage: TokenUsage) -> float:
        """
        Estimate the cost for a given token usage.

        Looks up the model in the pricing table and calculates cost
        based on per-million-token rates. Returns 0.0 for unknown models.

        Args:
            usage: TokenUsage with token counts and model name.

        Returns:
            Estimated cost in USD.
        """
        pricing = PRICING_TABLE.get(usage.model_name)
        if pricing is None:
            return 0.0

        prompt_cost = (usage.prompt_tokens / 1_000_000) * pricing["prompt"]
        completion_cost = (usage.completion_tokens / 1_000_000) * pricing["completion"]
        return prompt_cost + completion_cost
