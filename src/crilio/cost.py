from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    estimated: bool = False


# USD per one million tokens. Unknown models are tracked with zero cost.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "claude-3-5-sonnet-latest": (3.00, 15.00),
    "claude-3-5-haiku-latest": (0.80, 4.00),
}


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def cost_usd(model: str, usage: Usage) -> float:
    input_price, output_price = MODEL_PRICES.get(model, (0.0, 0.0))
    return (
        usage.input_tokens * input_price + usage.output_tokens * output_price
    ) / 1_000_000
