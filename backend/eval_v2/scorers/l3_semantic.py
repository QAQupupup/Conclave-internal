"""L3 Semantic Quality Scorer - LLM-as-Judge multi-dimensional evaluation.

This is the core evaluation layer (weight 0.45) that uses a cross-family LLM Judge
to evaluate semantic quality across multiple dimensions with CoT reasoning.
"""

from __future__ import annotations

import logging
from typing import Any

from eval_v2.llm_judge.calibration import (
    aggregate_reasoning,
    median_likert,
    self_consistency,
)
from eval_v2.llm_judge.client import JudgeClient
from eval_v2.llm_judge.prompts import (
    build_cot_rubric_prompt,
    build_judge_system_prompt,
)
from eval_v2.llm_judge.rubrics import (
    deliverable_type_display_name,
    get_dimensions,
)
from eval_v2.models.audit import AuditSnapshot
from eval_v2.models.enums import FailureClass, Level
from eval_v2.models.result import (
    CheckResult,
    DimensionScore,
    FailureRecord,
)
from eval_v2.scorers.base import ScorerBase, ScorerResult

logger = logging.getLogger(__name__)


class L3SemanticScorer(ScorerBase):
    """L3 语义质量评分器（权重 0.45）。

    使用跨家族 LLM Judge 进行多维度 CoT 评分。
    """

    level = Level.L3_SEMANTIC

    def __init__(
        self,
        judge_client: JudgeClient | None = None,
        config: dict[str, Any] | None = None,
    ):
        super().__init__(config)
        self.judge = judge_client
        self.pass_threshold = self.config.get("pass_threshold", 3) if self.config else 3
        self.min_prior_score = self.config.get("min_prior_score_for_judge", 0.3) if self.config else 0.3
        self.unreliable_std_threshold = self.config.get("unreliable_std_threshold", 0.8) if self.config else 0.8

    async def score(
        self,
        audit: AuditSnapshot,
        raw_progress: dict[str, Any] | None = None,
        raw_meeting: dict[str, Any] | None = None,
        http_errors: list[dict[str, Any]] | None = None,
        prior_l1_score: float = 1.0,
        prior_l2_score: float = 1.0,
    ) -> ScorerResult:
        checks: list[CheckResult] = []
        failures: list[FailureRecord] = []
        dimension_scores: list[DimensionScore] = []
        sub_scores: dict[str, float] = {}

        # 检查 Judge 是否可用
        if self.judge is None or not self.judge.available:
            return ScorerResult(
                score=0.5,
                passed=True,
                weight=self.config.get("weight", 0.45) if self.config else 0.45,
                confidence=0.0,
                details=[
                    self._make_check(
                        "judge_available",
                        False,
                        1.0,
                        score=0.5,
                        evidence="Judge client not available (no API key)",
                        detail="L3 semantic evaluation skipped: no Judge API key configured",
                    )
                ],
                failures=[],
                skipped=True,
                skip_reason="Judge unavailable",
            )

        # 如果 L1/L2 分数过低，跳过 Judge 调用以节省成本
        prior_score = min(prior_l1_score, prior_l2_score)
        if prior_score < self.min_prior_score:
            return ScorerResult(
                score=0.0,
                passed=False,
                weight=self.config.get("weight", 0.45) if self.config else 0.45,
                confidence=0.5,
                details=[
                    self._make_check(
                        "prior_quality_gate",
                        False,
                        1.0,
                        score=0.0,
                        evidence=f"prior_l1={prior_l1_score:.2f}, prior_l2={prior_l2_score:.2f}",
                        detail="Prior quality too low, skipping Judge evaluation",
                    )
                ],
                failures=[
                    FailureRecord(
                        failure_class=FailureClass.MODEL,
                        check_name="prior_quality_gate",
                        detail=f"L1/L2 score too low ({prior_score:.2f}), model output failed basic checks",
                    )
                ],
            )

        # 获取 artifact 文本
        artifact_text = audit.get_artifact_text()
        if not artifact_text or len(artifact_text) < 50:
            return ScorerResult(
                score=0.0,
                passed=False,
                weight=self.config.get("weight", 0.45) if self.config else 0.45,
                confidence=0.8,
                details=[
                    self._make_check(
                        "artifact_available",
                        False,
                        1.0,
                        score=0.0,
                        evidence=f"artifact_length={len(artifact_text)}",
                        detail="No artifact content to evaluate",
                    )
                ],
                failures=[
                    FailureRecord(
                        failure_class=FailureClass.MODEL,
                        check_name="artifact_available",
                        detail="Meeting completed but produced no meaningful artifact",
                    )
                ],
            )

        # 获取维度集
        deliverable_type = audit.meeting.deliverable_type
        dimensions = get_dimensions(deliverable_type)
        deliverable_name = deliverable_type_display_name(deliverable_type)
        topic = audit.meeting.clarified_topic or audit.meeting.topic

        system_prompt = build_judge_system_prompt(deliverable_name=deliverable_name)

        total_weight = sum(d.weight for d in dimensions)
        weighted_score_sum = 0.0
        passed_count = 0
        unreliable_count = 0

        for dim in dimensions:
            user_prompt = build_cot_rubric_prompt(
                topic=topic,
                artifact_text=artifact_text,
                dimension=dim,
                deliverable_name=deliverable_name,
            )

            try:
                judgments = await self.judge.judge_cot(system_prompt, user_prompt)
            except Exception as e:
                logger.warning(f"Judge call failed for dimension {dim.name}: {e}")
                judgments = []

            if not judgments:
                checks.append(
                    self._make_check(
                        f"dim_{dim.name}",
                        False,
                        dim.weight,
                        score=0.0,
                        evidence="Judge returned no results",
                        detail=f"Judge evaluation failed for dimension '{dim.name}'",
                    )
                )
                failures.append(
                    FailureRecord(
                        failure_class=FailureClass.INFRASTRUCTURE,
                        check_name=f"dim_{dim.name}",
                        detail=f"Judge API call failed for dimension {dim.name}",
                    )
                )
                continue

            median, mean, std = median_likert(judgments)
            consistency = self_consistency(judgments)
            binary_pass = median >= self.pass_threshold
            dim_score = (median - 1) / 4.0  # 归一化到 0-1

            # 检测不可靠评分（标准差过大）
            is_unreliable = std > self.unreliable_std_threshold
            if is_unreliable:
                unreliable_count += 1

            reasonings = aggregate_reasoning(judgments)

            ds = DimensionScore(
                dimension=dim.name,
                weight=dim.weight,
                likert_median=median,
                likert_mean=mean,
                likert_std=std,
                score=dim_score,
                binary_pass=binary_pass,
                self_consistency=consistency,
                reasonings=reasonings,
            )
            dimension_scores.append(ds)
            sub_scores[dim.name] = dim_score

            evidence = f"median={median}, mean={mean:.1f}, std={std:.2f}, consistency={consistency:.2f}"
            check_detail = ""
            if is_unreliable:
                check_detail = f"UNRELIABLE: high variance (std={std:.2f})"
            elif not binary_pass:
                check_detail = f"Failed: median likert={median} < {self.pass_threshold}"

            checks.append(
                self._make_check(
                    f"dim_{dim.name}",
                    binary_pass and not is_unreliable,
                    dim.weight,
                    score=dim_score,
                    evidence=evidence,
                    detail=check_detail,
                )
            )

            weighted_score_sum += dim_score * dim.weight
            if binary_pass:
                passed_count += 1

        # 聚合分数
        if total_weight > 0:
            aggregate = weighted_score_sum / total_weight
        else:
            aggregate = 0.0

        # 判定：加权分 ≥ 0.6 且不可靠维度 < 一半
        all_passed = aggregate >= 0.6 and unreliable_count < len(dimensions) / 2

        return ScorerResult(
            score=aggregate,
            passed=all_passed,
            weight=self.config.get("weight", 0.45) if self.config else 0.45,
            confidence=1.0 - (unreliable_count / max(len(dimensions), 1)),
            sub_scores=sub_scores,
            details=checks,
            failures=failures,
            dimension_scores=dimension_scores,
        )
