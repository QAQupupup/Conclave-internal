# 评估框架数据模型（dataclass）
from __future__ import annotations

from dataclasses import dataclass, field

from eval.graders.base import GraderResult  # 重新导出，统一返回类型入口

__all__ = ["GraderResult", "CaseResult", "SuiteResult", "RegressionResult"]


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
class RegressionResult:
    """回归判定结果。"""

    is_regression: bool
    reasons: list[str] = field(default_factory=list)
    severity: str = "none"  # none | low | medium | high
