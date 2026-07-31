"""Base class for all scorers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from eval_v2.models.audit import AuditSnapshot
from eval_v2.models.enums import Level
from eval_v2.models.result import CheckResult, FailureRecord, LayerResult


class ScorerResult(BaseModel):
    """评分器输出。"""

    score: float = 0.0
    """归一化分数 0-1。"""
    passed: bool = False
    weight: float = 1.0
    confidence: float = 1.0
    sub_scores: dict[str, float] = Field(default_factory=dict)
    details: list[CheckResult] = Field(default_factory=list)
    failures: list[FailureRecord] = Field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""

    def to_layer_result(self, level: Level) -> LayerResult:
        return LayerResult(
            layer=level,
            score=self.score,
            passed=self.passed,
            weight=self.weight,
            sub_scores=self.sub_scores,
            details=self.details,
            failures=self.failures,
            confidence=self.confidence,
            skipped=self.skipped,
            skip_reason=self.skip_reason,
        )


class ScorerBase(ABC):
    """评分器基类。"""

    level: Level = Level.L0_HEALTH

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    @abstractmethod
    async def score(
        self,
        audit: AuditSnapshot,
        raw_progress: dict[str, Any] | None = None,
        raw_meeting: dict[str, Any] | None = None,
        http_errors: list[dict[str, Any]] | None = None,
    ) -> ScorerResult:
        """执行评分。

        Args:
            audit: 类型化审计快照。
            raw_progress: 轮询得到的 progress 端点原始数据。
            raw_meeting: 会议详情原始数据。
            http_errors: HTTP 调用过程中记录的错误列表。
        """
        ...

    def _make_check(
        self,
        name: str,
        passed: bool,
        weight: float = 1.0,
        score: float | None = None,
        evidence: str = "",
        detail: str = "",
    ) -> CheckResult:
        return CheckResult(
            check_name=name,
            passed=passed,
            weight=weight,
            score=score if score is not None else (1.0 if passed else 0.0),
            evidence=evidence,
            detail=detail,
        )

    def _weighted_score(self, checks: list[CheckResult]) -> float:
        """计算加权平均分数。"""
        if not checks:
            return 0.0
        total_weight = sum(c.weight for c in checks)
        if total_weight == 0:
            return 0.0
        weighted_sum = sum(c.score * c.weight for c in checks)
        return weighted_sum / total_weight
