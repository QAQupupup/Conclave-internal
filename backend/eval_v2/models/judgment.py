"""LLM Judge judgment result models."""

from __future__ import annotations

from pydantic import BaseModel, Field

from eval_v2.models.enums import ConfidenceLevel


class CoTJudgment(BaseModel):
    """Chain-of-Thought 判断结果。"""

    binary_pass: bool
    """二元判定：该维度是否通过（≥3分视为通过）。"""
    likert_score: int = Field(ge=1, le=5)
    """5级 Likert 评分（1-5）。"""
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    """Judge 置信度。"""
    reasoning: str = ""
    """CoT 推理过程（分析优缺点）。"""
    raw_response: str = ""
    """原始 Judge 响应文本（用于调试）。"""


class PairwiseJudgment(BaseModel):
    """Pairwise 比较判断结果。"""

    winner: str = Field(pattern="^(A|B|tie)$")
    """胜者：A、B 或 tie。"""
    reasoning: str = ""
    """比较推理。"""
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    """置信度。"""
    a_was_first: bool = True
    """A 是否在 prompt 中先出现（用于位置偏置分析）。"""
    raw_response: str = ""
    """原始响应。"""


class KappaResult(BaseModel):
    """Cohen's kappa 校准结果。"""

    kappa: float = 0.0
    """Cohen's kappa 值（-1 到 1，≥0.6 为 substantial agreement）。"""
    agreement_rate: float = 0.0
    """简单一致率。"""
    n_samples: int = 0
    """样本数。"""
    is_reliable: bool = False
    """kappa ≥ 0.6 且 n ≥ 10 时为 True。"""
    judge_a: str = ""
    judge_b: str = ""
