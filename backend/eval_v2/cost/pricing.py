"""Pricing module - estimates LLM costs when audit data is unavailable.

Reuses pricing logic from app.pricing_fetcher and app.observability.cost_tracker where possible,
with a fallback pricing table for eval-only use.
"""

from __future__ import annotations

# Fallback pricing table (USD per 1M tokens)
# Used when cannot import from app or pricing data is unavailable
_FALLBACK_PRICING: dict[str, tuple[float, float]] = {
    # (input_price_per_mtok, output_price_per_mtok)
    "deepseek-ai/DeepSeek-V3.2": (0.14, 0.28),
    "deepseek-ai/DeepSeek-V4-Flash": (0.07, 0.28),
    "deepseek-ai/DeepSeek-R1": (0.55, 2.19),
    "doubao-seed-code/Doubao-Seed-2.0-Code": (0.10, 0.30),
    "doubao-seed-code/Doubao-Seed-2.0-pro": (0.30, 0.60),
    "Qwen/Qwen3-235B-A22B": (0.50, 2.00),
    "Qwen/Qwen3-32B": (0.15, 0.60),
    "Qwen/Qwen2.5-72B-Instruct": (0.35, 1.40),
    "anthropic/claude-sonnet-4-20250514": (3.00, 15.00),
    "openai/gpt-4o": (2.50, 10.00),
    "openai/gpt-4o-mini": (0.15, 0.60),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """估算 LLM 调用成本（USD）。"""
    # 尝试使用应用的定价数据
    try:
        from app.pricing_fetcher import get_model_pricing

        pricing = get_model_pricing(model)
        if pricing:
            in_price = pricing.get("input_price", 0)
            out_price = pricing.get("output_price", 0)
            cny_to_usd = 7.2
            return (input_tokens / 1_000_000) * (in_price / cny_to_usd) + (output_tokens / 1_000_000) * (
                out_price / cny_to_usd
            )
    except (ImportError, Exception):
        pass

    # 使用 fallback 表
    model_lower = model.lower()
    for key, (in_p, out_p) in _FALLBACK_PRICING.items():
        if key.lower() in model_lower or model_lower in key.lower():
            return (input_tokens / 1_000_000) * in_p + (output_tokens / 1_000_000) * out_p

    # 默认：按中等价位估算
    return (input_tokens / 1_000_000) * 0.30 + (output_tokens / 1_000_000) * 1.00
