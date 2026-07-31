"""Bias mitigation for LLM Judge.

Includes:
- Position randomization for pairwise comparison
- Length bias detection (Pearson correlation)
- Same-family model detection
"""

from __future__ import annotations

import math
import random


def randomize_pairwise_order(
    candidate_a: str,
    candidate_b: str,
    seed: int | None = None,
) -> tuple[str, str, bool, dict[str, str]]:
    """随机交换 Pairwise 比较中 A/B 的位置。

    Returns:
        (first_text, second_text, a_was_first, mapping)
        mapping: {"A": "first"/"second", "B": "first"/"second"} 用于还原
    """
    rng = random.Random(seed)
    a_first = rng.random() < 0.5
    if a_first:
        return candidate_a, candidate_b, True, {"A": "first", "B": "second"}
    else:
        return candidate_b, candidate_a, False, {"A": "second", "B": "first"}


def map_pairwise_winner(raw_winner: str, a_was_first: bool) -> str:
    """将 Judge 的 A/B 选择映射回原始候选。

    Args:
        raw_winner: Judge 返回的 "A"/"B"/"tie"（A=first, B=second in prompt）
        a_was_first: 原始 A 是否在 prompt 中先出现

    Returns:
        "A"（原始 A 胜出）/"B"（原始 B 胜出）/"tie"
    """
    if raw_winner == "tie":
        return "tie"
    if a_was_first:
        return raw_winner  # A=first=A, B=second=B
    else:
        # A=second, B=first
        return "B" if raw_winner == "A" else "A"


def pearson_correlation(x: list[float], y: list[float]) -> float:
    """计算 Pearson 相关系数。"""
    n = min(len(x), len(y))
    if n < 2:
        return 0.0
    x = x[:n]
    y = y[:n]
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    std_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
    std_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))
    if std_x == 0 or std_y == 0:
        return 0.0
    return cov / (std_x * std_y)


def detect_length_bias(
    scores: list[float],
    artifact_lengths: list[int],
) -> tuple[float, bool]:
    """检测长度偏置：分数是否与产出长度正相关。

    Returns:
        (pearson_r, has_bias): r > 0.7 认为存在长度偏置
    """
    if len(scores) < 5:
        return 0.0, False
    r = pearson_correlation(scores, [float(l) for l in artifact_lengths])
    return r, r > 0.7


# 模型家族映射
MODEL_FAMILIES: dict[str, list[str]] = {
    "doubao": ["doubao", "Doubao", "doubao-seed", "ep-"],
    "deepseek": ["deepseek", "DeepSeek"],
    "qwen": ["qwen", "Qwen"],
    "openai": ["gpt-", "o1-", "o3-"],
    "anthropic": ["claude"],
    "google": ["gemini"],
    "zhipu": ["glm", "GLM"],
    "baichuan": ["baichuan"],
    "moonshot": ["moonshot", "kimi"],
    "minimax": ["minimax", "abab"],
    "llama": ["llama", "Llama"],
    "mistral": ["mistral", "Mixtral"],
}


def get_model_family(model_id: str) -> str:
    """获取模型家族名称。"""
    model_lower = model_id.lower()
    for family, patterns in MODEL_FAMILIES.items():
        for p in patterns:
            if p.lower() in model_lower:
                return family
    return "unknown"


def is_same_family(model_a: str, model_b: str) -> bool:
    """检测两个模型是否同家族。"""
    return get_model_family(model_a) == get_model_family(model_b) and get_model_family(model_a) != "unknown"
