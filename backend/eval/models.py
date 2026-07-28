# 评估框架数据模型（dataclass）
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from eval.graders.base import GraderResult  # 重新导出，统一返回类型入口

__all__ = ["GraderResult", "CaseResult", "SuiteResult", "RegressionResult", "CaseRegression"]


@dataclass
class CaseResult:
    """单用例运行结果。"""

    case_id: str
    tier: int
    passed: bool
    stage_scores: dict[str, float] = field(default_factory=dict)
    total_tokens: int = 0
    latency_ms: float = 0.0
    errors: list[str] = field(default_factory=list)
    run_index: int = 0
    # 关联的会议 ID（用于回溯审计数据）
    meeting_id: str = ""
    # 完整审计数据（来自 GET /meetings/{id}/audit）
    audit_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class SuiteResult:
    """整批用例运行汇总结果。"""

    total_cases: int
    pass1: float
    pass1_ci: tuple[float, float]
    pass3: float
    avg_score: float
    stage_breakdown: dict[str, float] = field(default_factory=dict)
    per_case_results: list[CaseResult] = field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    unstable_cases: list[str] = field(default_factory=list)
    unreliable_judgments: list[str] = field(default_factory=list)


@dataclass
class CaseRegression:
    """单用例回归对比结果。"""

    case_id: str
    is_regression: bool
    reasons: list[str] = field(default_factory=list)
    # 对比维度详情
    passed_changed: bool = False  # passed 状态是否变化
    score_delta: float = 0.0  # 分数变化（新 - 旧）
    token_delta: int = 0  # token 变化
    latency_delta: float = 0.0  # 延迟变化（ms）
    # 审计数据对比
    old_quality_score: float | None = None
    new_quality_score: float | None = None
    old_iteration_count: int = 0
    new_iteration_count: int = 0
    old_provider_switches: int = 0
    new_provider_switches: int = 0
    old_stub_fallbacks: int = 0
    new_stub_fallbacks: int = 0


@dataclass
class RegressionResult:
    """回归判定结果。"""

    is_regression: bool
    reasons: list[str] = field(default_factory=list)
    severity: str = "none"  # none | low | medium | high
    # per-case 详细对比（新增）
    case_regressions: list[CaseRegression] = field(default_factory=list)
