"""L4 Comparative Evaluation Scorer.

Evaluates:
- Pass@3 stability
- Judge self-consistency
- Ablation uplift (vs Direct LLM baseline)
- Length bias detection
"""

from __future__ import annotations

from typing import Any

from eval_v2.models.audit import AuditSnapshot
from eval_v2.models.enums import Level
from eval_v2.scorers.base import ScorerBase, ScorerResult


class L4ComparativeScorer(ScorerBase):
    """L4 对比评估评分器（权重 0.15）。

    注意：单用例单次运行时，L4 主要评估 Judge 自一致性。
    Pass@3 稳定性和消融对比在 SuiteRunner 层面计算后注入。
    """

    level = Level.L4_COMPARATIVE

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        w = config or {}
        self.weights = {
            "pass3_stability": w.get("pass3_stability_weight", 0.30),
            "judge_self_consistency": w.get("judge_self_consistency_weight", 0.20),
            "ablation_uplift": w.get("ablation_uplift_weight", 0.35),
            "no_length_bias": w.get("no_length_bias_weight", 0.15),
        }
        self.length_bias_threshold = w.get("length_bias_warning_threshold", 0.7)

    async def score(
        self,
        audit: AuditSnapshot,
        raw_progress: dict[str, Any] | None = None,
        raw_meeting: dict[str, Any] | None = None,
        http_errors: list[dict[str, Any]] | None = None,
        # 外部注入的对比数据（由 SuiteRunner 提供）
        pass3_stability_score: float | None = None,
        judge_consistency: float | None = None,
        ablation_uplift_score: float | None = None,
        length_bias_r: float | None = None,
    ) -> ScorerResult:
        checks = []

        # 1. pass3_stability（如果未注入，默认为1.0，单次运行无法评估稳定性）
        stability = pass3_stability_score if pass3_stability_score is not None else 1.0
        checks.append(
            self._make_check(
                "pass3_stability",
                stability >= 0.5,
                self.weights["pass3_stability"],
                score=stability,
                evidence=f"stability={stability:.2f}"
                if pass3_stability_score is not None
                else "single run, defaulting to 1.0",
            )
        )

        # 2. judge_self_consistency
        consistency = judge_consistency if judge_consistency is not None else 1.0
        checks.append(
            self._make_check(
                "judge_self_consistency",
                consistency >= 0.7,
                self.weights["judge_self_consistency"],
                score=consistency,
                evidence=f"consistency={consistency:.2f}" if judge_consistency is not None else "no L3 judge data",
            )
        )

        # 3. ablation_uplift（未注入时跳过，不扣分）
        if ablation_uplift_score is not None:
            checks.append(
                self._make_check(
                    "ablation_uplift",
                    ablation_uplift_score > 0,
                    self.weights["ablation_uplift"],
                    score=max(0.0, min(1.0, 0.5 + ablation_uplift_score)),
                    evidence=f"uplift={ablation_uplift_score:.2f}",
                )
            )
        else:
            checks.append(
                self._make_check(
                    "ablation_uplift",
                    True,
                    self.weights["ablation_uplift"],
                    score=0.5,  # neutral
                    evidence="ablation not run",
                )
            )

        # 4. no_length_bias
        if length_bias_r is not None:
            no_bias = abs(length_bias_r) < self.length_bias_threshold
            checks.append(
                self._make_check(
                    "no_length_bias",
                    no_bias,
                    self.weights["no_length_bias"],
                    score=max(0.0, 1.0 - abs(length_bias_r)),
                    evidence=f"pearson_r={length_bias_r:.3f}",
                    detail="Length bias detected" if not no_bias else "",
                )
            )
        else:
            checks.append(
                self._make_check(
                    "no_length_bias",
                    True,
                    self.weights["no_length_bias"],
                    score=1.0,
                    evidence="single case, cannot compute length bias",
                )
            )

        score = self._weighted_score(checks)
        passed = score >= 0.6

        return ScorerResult(
            score=score,
            passed=passed,
            weight=self.config.get("weight", 0.15) if self.config else 0.15,
            confidence=0.8 if (pass3_stability_score is not None or ablation_uplift_score is not None) else 0.4,
            sub_scores={c.check_name: c.score for c in checks},
            details=checks,
        )
