"""Core result models for Eval V2."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from eval_v2.models.audit import AuditSnapshot
from eval_v2.models.enums import FailureClass, Level


class CheckResult(BaseModel):
    """单条检查结果。"""

    check_name: str
    passed: bool
    weight: float = 1.0
    score: float = 0.0
    """该检查项的归一化分数 0-1。"""
    evidence: str = ""
    """支持结论的证据。"""
    detail: str = ""
    """详细说明。"""


class FailureRecord(BaseModel):
    """失败记录。"""

    failure_class: FailureClass
    stage: str = ""
    check_name: str = ""
    detail: str = ""
    evidence: str = ""


class CostBreakdown(BaseModel):
    """成本明细。"""

    total_cost_usd: float = 0.0
    sut_cost_usd: float = 0.0
    """SUT（被测系统）LLM 调用成本。"""
    judge_cost_usd: float = 0.0
    """Judge LLM 调用成本。"""
    per_stage_cost: dict[str, float] = Field(default_factory=dict)
    per_provider_cost: dict[str, float] = Field(default_factory=dict)
    cost_per_pass: float = 0.0
    """每个通过用例的平均成本。"""


class TokenBreakdown(BaseModel):
    """Token 统计。"""

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    sut_input_tokens: int = 0
    sut_output_tokens: int = 0
    judge_input_tokens: int = 0
    judge_output_tokens: int = 0


class DimensionScore(BaseModel):
    """L3 单维度评分结果。"""

    dimension: str
    weight: float
    likert_median: int = 3
    """3 次 Judge 评分的中位数。"""
    likert_mean: float = 3.0
    likert_std: float = 0.0
    score: float = 0.0
    """归一化分数 (median-1)/4。"""
    binary_pass: bool = False
    self_consistency: float = 1.0
    """1 - cv（变异系数），越高越一致。"""
    reasonings: list[str] = Field(default_factory=list)
    """3 次 Judge 的 reasoning 文本。"""


class LayerResult(BaseModel):
    """单层级评估结果。"""

    layer: Level
    score: float = 0.0
    """该层加权归一化分数 0-1。"""
    passed: bool = False
    weight: float = 0.0
    """该层在最终聚合中的权重。"""
    sub_scores: dict[str, float] = Field(default_factory=dict)
    """子维度分数（如 L3 各语义维度）。"""
    details: list[CheckResult] = Field(default_factory=list)
    """逐条检查结果。"""
    failures: list[FailureRecord] = Field(default_factory=list)
    confidence: float = 1.0
    """该层评分的置信度（0-1）。"""
    dimension_scores: list[DimensionScore] = Field(default_factory=list)
    """L3 专用：各维度详细评分。"""
    skipped: bool = False
    """是否因前置层失败而跳过。"""
    skip_reason: str = ""


class CaseRunResult(BaseModel):
    """单用例单次运行结果。"""

    case_id: str
    run_index: int
    meeting_id: str = ""
    layers: dict[str, LayerResult] = Field(default_factory=dict)
    """L0-L4 各层结果，key 为 Level value。"""
    aggregate_score: float = 0.0
    """加权总分 0-100。"""
    passed: bool = False
    """综合判定（aggregate_score ≥ 60 且无 L0 失败）。"""
    audit: AuditSnapshot | None = None
    cost: CostBreakdown = Field(default_factory=CostBreakdown)
    latency_ms: float = 0.0
    tokens: TokenBreakdown = Field(default_factory=TokenBreakdown)
    failure_class: FailureClass | None = None
    is_stable: bool = True
    """Pass@3 中是否稳定（≥2/3 通过）。"""
    error: str = ""
    """运行时错误信息。"""

    def get_layer(self, level: Level) -> LayerResult | None:
        return self.layers.get(level.value)


class AblationComparison(BaseModel):
    """消融实验对比结果。"""

    multi_agent_score: float = 0.0
    direct_llm_score: float = 0.0
    uplift: float = 0.0
    """多 Agent 相比直接生成的分数提升（百分点）。"""
    pairwise_wins: int = 0
    pairwise_losses: int = 0
    pairwise_ties: int = 0
    pairwise_win_rate: float = 0.0
    """多 Agent 在 Pairwise 盲评中的胜率。"""
    p_value: float = 1.0
    """Fisher 精确检验 p 值。"""
    cohens_h: float = 0.0
    """效应量（Cohen's h）。"""
    is_significant: bool = False
    """p < 0.05。"""
    cost_ratio: float = 1.0
    """多 Agent 成本 / 直接生成成本。"""
    multi_agent_cost: float = 0.0
    direct_llm_cost: float = 0.0


class RegressionSummary(BaseModel):
    """回归对比摘要。"""

    baseline_suite_id: str = ""
    current_suite_id: str = ""
    pass_rate_change: float = 0.0
    """Pass@1 变化（百分点）。"""
    score_change: float = 0.0
    """平均分变化。"""
    p_value_pass_rate: float = 1.0
    is_regression: bool = False
    is_improvement: bool = False
    cohens_h: float = 0.0
    new_failures: list[str] = Field(default_factory=list)
    new_passes: list[str] = Field(default_factory=list)
    regression_cases: list[str] = Field(default_factory=list)


class ModelInfo(BaseModel):
    """被测模型信息。"""

    model: str = ""
    provider: str = ""
    base_url: str = ""
    judge_model: str = ""
    judge_provider: str = ""
    is_same_family: bool = False
    """Judge 和被测模型是否同族。"""


class SuiteResult(BaseModel):
    """整批评估结果。"""

    suite_id: str
    timestamp: str = ""
    """ISO format timestamp of when the suite ran."""
    mode: str = "standard"
    pass_at_1: float = 0.0
    """Pass@1 通过率 0-1。"""
    pass_at_1_ci: tuple[float, float] = (0.0, 0.0)
    """Pass@1 的 95% Wilson 置信区间。"""
    pass_at_3: float = 0.0
    """Pass@3 通过率（至少1次通过）。"""
    pass_at_3_stable: float = 0.0
    """Stable Pass@3：≥2/3 通过的比例。"""
    avg_aggregate_score: float = 0.0
    """平均加权总分。"""
    layer_pass_rates: dict[str, float] = Field(default_factory=dict)
    """各层通过率。"""
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    """各语义维度平均分。"""
    failure_mode_breakdown: dict[str, int] = Field(default_factory=dict)
    """按 FailureClass 分类的失败数。"""
    total_cost_usd: float = 0.0
    cost_per_pass: float = 0.0
    total_tokens: int = 0
    judge_cost_usd: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_avg_ms: float = 0.0
    n_cases: int = 0
    n_runs_per_case: int = 1
    n_infrastructure_failures: int = 0
    n_model_failures: int = 0
    n_test_bugs: int = 0
    per_case_results: list[CaseRunResult] = Field(default_factory=list)
    ablation: AblationComparison | None = None
    kappa: float | None = None
    regression: RegressionSummary | None = None
    model_info: ModelInfo = Field(default_factory=ModelInfo)
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    length_bias_pearson_r: float | None = None
    judge_unreliable_count: int = 0
    """3次评分标准差超阈值的维度数量。"""
    duration_seconds: float = 0.0
