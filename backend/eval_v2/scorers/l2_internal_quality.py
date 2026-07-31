"""L2 Internal Quality Scorer.

Consumes SUT's own quality_score, degradation_warnings, confidence_flags, and hard_failures.
This is the key improvement over v1: instead of duplicating structural checks,
we trust and consume SUT's internal quality evaluation.
"""

from __future__ import annotations

from typing import Any

from eval_v2.models.audit import AuditSnapshot
from eval_v2.models.enums import FailureClass, Level
from eval_v2.models.result import FailureRecord
from eval_v2.scorers.base import ScorerBase, ScorerResult


class L2InternalQualityScorer(ScorerBase):
    """L2 内部质量评分器（权重 0.20）。

    核心改进：直接消费 SUT 内部分数（quality_score）和退化信号，
    不再平行实现 produce field_check 等结构性检查。
    """

    level = Level.L2_INTERNAL

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        w = config or {}
        self.weights = {
            "internal_quality_score": w.get("internal_quality_score_weight", 0.30),
            "no_high_degradation": w.get("no_high_degradation_weight", 0.20),
            "degradation_count_norm": w.get("degradation_count_norm_weight", 0.10),
            "confidence_stable": w.get("confidence_stable_weight", 0.15),
            "no_hard_failures": w.get("no_hard_failures_weight", 0.15),
            "drift_rate": w.get("drift_rate_weight", 0.10),
        }
        self.degradation_max_count = w.get("degradation_max_count", 5)
        self.quality_pass_threshold = w.get("quality_score_pass_threshold", 60)

    async def score(
        self,
        audit: AuditSnapshot,
        raw_progress: dict[str, Any] | None = None,
        raw_meeting: dict[str, Any] | None = None,
        http_errors: list[dict[str, Any]] | None = None,
    ) -> ScorerResult:
        checks = []
        failures = []
        m = audit.meeting
        deg = audit.degradation

        # 1. internal_quality_score: 直接消费 SUT 内部分
        qs = m.quality_score
        if qs <= 0:
            # quality_score 为 0 可能表示：未评分（流程未到produce）或评分极低
            qs_normalized = 0.0
            qs_passed = False
        else:
            qs_normalized = min(1.0, qs / 100.0)
            qs_passed = qs >= self.quality_pass_threshold
        checks.append(
            self._make_check(
                "internal_quality_score",
                qs_passed,
                self.weights["internal_quality_score"],
                score=qs_normalized,
                evidence=f"quality_score={qs}/100",
                detail=f"SUT internal quality score: {qs}" if not qs_passed else "",
            )
        )
        if not qs_passed and qs > 0:
            failures.append(
                FailureRecord(
                    failure_class=FailureClass.MODEL,
                    check_name="internal_quality_score",
                    detail=f"SUT quality score too low: {qs}/100 (threshold {self.quality_pass_threshold})",
                )
            )

        # 2. no_high_degradation: 无 high severity 退化
        no_high = not deg.has_critical_degradation
        checks.append(
            self._make_check(
                "no_high_degradation",
                no_high,
                self.weights["no_high_degradation"],
                evidence=f"high_severity={deg.high_severity}, medium={deg.medium_severity}, low={deg.low_severity}",
                detail=f"High severity degradations: {deg.high_severity}" if not no_high else "",
            )
        )
        if not no_high:
            failures.append(
                FailureRecord(
                    failure_class=FailureClass.MODEL,
                    check_name="no_high_degradation",
                    detail=f"Critical degradation detected: {deg.warning_types}",
                )
            )

        # 3. degradation_count_norm: 退化告警数量归一化
        deg_count = deg.total_warnings
        if deg_count == 0:
            deg_norm = 1.0
        elif deg_count >= self.degradation_max_count:
            deg_norm = 0.0
        else:
            deg_norm = 1.0 - (deg_count / self.degradation_max_count)
        checks.append(
            self._make_check(
                "degradation_count_norm",
                deg_count < self.degradation_max_count,
                self.weights["degradation_count_norm"],
                score=deg_norm,
                evidence=f"degradation_warnings={deg_count}",
            )
        )

        # 4. confidence_stable: confidence_flags 无 fallback
        fallback_stages = [stage for stage, flag in m.confidence_flags.items() if flag == "fallback"]
        conf_stable = len(fallback_stages) <= 1
        checks.append(
            self._make_check(
                "confidence_stable",
                conf_stable,
                self.weights["confidence_stable"],
                score=max(0.0, 1.0 - len(fallback_stages) * 0.3),
                evidence=f"fallback_stages={fallback_stages}, all_flags={m.confidence_flags}",
                detail=f"Fallback in stages: {fallback_stages}" if not conf_stable else "",
            )
        )

        # 5. no_hard_failures
        no_hf = len(m.hard_failures) == 0
        checks.append(
            self._make_check(
                "no_hard_failures",
                no_hf,
                self.weights["no_hard_failures"],
                evidence=f"hard_failures={m.hard_failures}",
                detail=f"Hard failures: {m.hard_failures[:3]}" if not no_hf else "",
            )
        )
        if not no_hf:
            for hf in m.hard_failures[:5]:
                failures.append(
                    FailureRecord(
                        failure_class=FailureClass.MODEL,
                        check_name="no_hard_failures",
                        detail=str(hf)[:200],
                    )
                )

        # 6. drift_rate
        if m.total_checks > 0:
            drift_rate = m.drift_detected / m.total_checks
            drift_score = max(0.0, 1.0 - drift_rate / 0.5)  # 50%漂移=0分
        else:
            drift_rate = 0.0
            drift_score = 1.0
        drift_ok = drift_rate < 0.3
        checks.append(
            self._make_check(
                "drift_rate",
                drift_ok,
                self.weights["drift_rate"],
                score=drift_score,
                evidence=f"drift={m.drift_detected}/{m.total_checks}={drift_rate:.1%}",
            )
        )

        score = self._weighted_score(checks)
        passed = score >= 0.6 and qs_passed

        return ScorerResult(
            score=score,
            passed=passed,
            weight=self.config.get("weight", 0.20) if self.config else 0.20,
            confidence=1.0,
            sub_scores={c.check_name: c.score for c in checks},
            details=checks,
            failures=failures,
        )
