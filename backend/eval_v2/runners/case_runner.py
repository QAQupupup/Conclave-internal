"""Single test case runner.

Orchestrates: create meeting → upload docs → start → poll → fetch audit → L0→L4 scoring.
"""

from __future__ import annotations

import time
import traceback
from typing import Any

from eval_v2.models.audit import (
    AuditSnapshot,
    CostSnapshot,
    DegradationSummary,
    MeetingSnapshot,
    TraceSnapshot,
)
from eval_v2.models.case import EvalCase
from eval_v2.models.enums import FailureClass, Level
from eval_v2.models.result import (
    CaseRunResult,
    CostBreakdown,
    LayerResult,
    TokenBreakdown,
)
from eval_v2.runners.sut_client import SUTClient, SUTError
from eval_v2.scorers.l0_system_health import L0SystemHealthScorer
from eval_v2.scorers.l1_process_integrity import L1ProcessIntegrityScorer
from eval_v2.stats.failure_classifier import classify_failure


class CaseRunner:
    """单用例执行器。"""

    def __init__(
        self,
        sut_client: SUTClient,
        config: dict[str, Any] | None = None,
    ):
        self.sut = sut_client
        self.config = config or {}
        self.l0_scorer = L0SystemHealthScorer(self.config.get("l0_health", {}))
        self.l1_scorer = L1ProcessIntegrityScorer(self.config.get("l1_process", {}))
        # L2-L4 scorer will be injected later (Phases 3-5)
        self.l2_scorer = None
        self.l3_scorer = None
        self.l4_scorer = None

    def set_scorers(self, l2=None, l3=None, l4=None) -> None:
        """注入 L2-L4 评分器（在 Phase 3-5 完成后调用）。"""
        if l2:
            self.l2_scorer = l2
        if l3:
            self.l3_scorer = l3
        if l4:
            self.l4_scorer = l4

    async def run_single(self, case: EvalCase, run_index: int = 0) -> CaseRunResult:
        """执行单用例单次运行。"""
        start_time = time.monotonic()
        result = CaseRunResult(
            case_id=case.case_id,
            run_index=run_index,
        )

        http_errors: list[dict[str, Any]] = []
        audit: AuditSnapshot | None = None
        raw_progress: dict[str, Any] = {}
        raw_meeting: dict[str, Any] = {}
        meeting_id: str = ""

        try:
            # 1. 创建会议
            try:
                meeting_id = await self.sut.create_meeting(
                    topic=case.topic,
                    deliverable_type=case.config.deliverable_type.value,
                    flow_plan=case.config.flow_plan,
                    workflow_template=case.config.workflow_template,
                    debate_depth=case.config.debate_depth,
                    dynamic_routing=case.config.dynamic_routing,
                )
                result.meeting_id = meeting_id
            except SUTError as e:
                http_errors.append(
                    {
                        "stage": "create_meeting",
                        "status": e.http_status,
                        "detail": str(e),
                        "error": str(e),
                        "failure_class": e.failure_class.value,
                    }
                )
                result.error = f"Create meeting failed: {e}"
                result.failure_class = e.failure_class
                return self._finalize(result, start_time, http_errors, audit)

            # 2. 上传文档（best-effort）
            for doc in case.uploaded_docs:
                content = doc.content
                if content is None:
                    # TODO: 从 dataset 目录读取
                    continue
                await self.sut.upload_document(meeting_id, doc.filename, content)

            # 3. 启动会议
            try:
                await self.sut.start_meeting(meeting_id)
            except SUTError as e:
                http_errors.append(
                    {
                        "stage": "start_meeting",
                        "status": e.http_status,
                        "detail": str(e),
                        "error": str(e),
                        "failure_class": e.failure_class.value,
                    }
                )
                # 409 = already running, 继续轮询
                if e.http_status != 409:
                    result.error = f"Start meeting failed: {e}"
                    result.failure_class = e.failure_class
                    # 仍然尝试获取 audit
                    audit = await self._fetch_audit(meeting_id)
                    return self._finalize(result, start_time, http_errors, audit)

            # 4. 轮询直到终态
            try:
                raw_progress = await self.sut.poll_progress(
                    meeting_id,
                    timeout=self.config.get("execution", {}).get("per_case_timeout", 600),
                )
            except SUTError as e:
                http_errors.append(
                    {
                        "stage": "poll",
                        "status": e.http_status,
                        "detail": str(e),
                        "error": str(e),
                        "failure_class": e.failure_class.value,
                    }
                )
                result.error = f"Polling failed: {e}"
                result.failure_class = e.failure_class

            # 5. 获取完整审计数据
            audit = await self._fetch_audit(meeting_id)
            if not audit or not audit.meeting.meeting_id:
                # 尝试获取 meeting 详情
                raw_meeting = await self.sut.fetch_meeting(meeting_id)
                if raw_meeting:
                    audit = AuditSnapshot.from_raw({"meeting": raw_meeting})

        except Exception as e:
            result.error = f"Unexpected error: {type(e).__name__}: {e}\n{traceback.format_exc()}"
            result.failure_class = FailureClass.TEST_BUG

        # 6. 逐层评分
        await self._score_all_layers(result, audit, raw_progress, raw_meeting, http_errors)

        return self._finalize(result, start_time, http_errors, audit)

    async def _fetch_audit(self, meeting_id: str) -> AuditSnapshot | None:
        """获取并解析审计数据。"""
        raw = await self.sut.fetch_audit(meeting_id)
        if not raw:
            return None
        try:
            return AuditSnapshot.from_raw(raw)
        except Exception:
            return None

    async def _score_all_layers(
        self,
        result: CaseRunResult,
        audit: AuditSnapshot | None,
        raw_progress: dict[str, Any],
        raw_meeting: dict[str, Any],
        http_errors: list[dict[str, Any]],
    ) -> None:
        """执行 L0-L4 所有层评分。"""
        if audit is None:
            # 无审计数据，L0 必然失败
            audit = AuditSnapshot(
                meeting=MeetingSnapshot(meeting_id=result.meeting_id),
                trace=TraceSnapshot(),
                cost=CostSnapshot(),
                degradation=DegradationSummary(),
            )

        # L0: 系统健康
        l0_result = await self.l0_scorer.score(audit, raw_progress, raw_meeting, http_errors)
        l0_layer = l0_result.to_layer_result(Level.L0_HEALTH)
        l0_layer.weight = 0.0  # hard gate
        result.layers[Level.L0_HEALTH.value] = l0_layer

        l0_passed = l0_result.passed

        # L1: 流程完整性（仅在 L0 通过时执行）
        if l0_passed:
            l1_result = await self.l1_scorer.score(audit, raw_progress, raw_meeting, http_errors)
            l1_layer = l1_result.to_layer_result(Level.L1_PROCESS)
            l1_layer.weight = self.config.get("weights", {}).get("l1_process_integrity", 0.20)
            result.layers[Level.L1_PROCESS.value] = l1_layer
            l1_passed = l1_result.passed
            l1_score = l1_result.score
        else:
            l1_layer = LayerResult(
                layer=Level.L1_PROCESS,
                score=0.0,
                passed=False,
                weight=self.config.get("weights", {}).get("l1_process_integrity", 0.20),
                skipped=True,
                skip_reason="L0 failed (infrastructure issue)",
            )
            result.layers[Level.L1_PROCESS.value] = l1_layer
            l1_passed = False
            l1_score = 0.0

        # L2: 内部质量（Phase 3 实现）
        l2_score = 0.0
        if l0_passed and self.l2_scorer:
            l2_result = await self.l2_scorer.score(audit, raw_progress, raw_meeting, http_errors)
            l2_layer = l2_result.to_layer_result(Level.L2_INTERNAL)
            l2_layer.weight = self.config.get("weights", {}).get("l2_internal_quality", 0.20)
            result.layers[Level.L2_INTERNAL.value] = l2_layer
            l2_score = l2_result.score
        elif l0_passed:
            # Placeholder - L2 not yet implemented
            l2_layer = LayerResult(
                layer=Level.L2_INTERNAL,
                score=0.5,  # neutral for now
                passed=True,
                weight=self.config.get("weights", {}).get("l2_internal_quality", 0.20),
                skipped=True,
                skip_reason="L2 scorer not yet implemented",
            )
            result.layers[Level.L2_INTERNAL.value] = l2_layer
            l2_score = 0.5
        else:
            l2_layer = LayerResult(
                layer=Level.L2_INTERNAL,
                score=0.0,
                passed=False,
                weight=self.config.get("weights", {}).get("l2_internal_quality", 0.20),
                skipped=True,
                skip_reason="L0 failed",
            )
            result.layers[Level.L2_INTERNAL.value] = l2_layer

        # L3: 语义质量（Phase 4 实现）
        l3_failed_dims = 0
        l3_total_dims = 0
        if l0_passed and l1_score >= 0.3 and self.l3_scorer:
            l3_result = await self.l3_scorer.score(audit, raw_progress, raw_meeting, http_errors)
            l3_layer = l3_result.to_layer_result(Level.L3_SEMANTIC)
            l3_layer.weight = self.config.get("weights", {}).get("l3_semantic", 0.45)
            result.layers[Level.L3_SEMANTIC.value] = l3_layer
            l3_failed_dims = sum(1 for c in l3_result.details if not c.passed)
            l3_total_dims = len(l3_result.details)
        elif l0_passed:
            l3_layer = LayerResult(
                layer=Level.L3_SEMANTIC,
                score=0.5,
                passed=True,
                weight=self.config.get("weights", {}).get("l3_semantic", 0.45),
                skipped=True,
                skip_reason="L3 scorer not yet implemented",
            )
            result.layers[Level.L3_SEMANTIC.value] = l3_layer
        else:
            l3_layer = LayerResult(
                layer=Level.L3_SEMANTIC,
                score=0.0,
                passed=False,
                weight=self.config.get("weights", {}).get("l3_semantic", 0.45),
                skipped=True,
                skip_reason="L0 failed",
            )
            result.layers[Level.L3_SEMANTIC.value] = l3_layer

        # L4: 对比评估（Phase 5 实现）
        if l0_passed and self.l4_scorer:
            l4_result = await self.l4_scorer.score(audit, raw_progress, raw_meeting, http_errors)
            l4_layer = l4_result.to_layer_result(Level.L4_COMPARATIVE)
            l4_layer.weight = self.config.get("weights", {}).get("l4_comparative", 0.15)
            result.layers[Level.L4_COMPARATIVE.value] = l4_layer
        elif l0_passed:
            l4_layer = LayerResult(
                layer=Level.L4_COMPARATIVE,
                score=1.0,  # single run, stability=1.0
                passed=True,
                weight=self.config.get("weights", {}).get("l4_comparative", 0.15),
                skipped=True,
                skip_reason="L4 scorer not yet implemented (requires multiple runs)",
            )
            result.layers[Level.L4_COMPARATIVE.value] = l4_layer
        else:
            l4_layer = LayerResult(
                layer=Level.L4_COMPARATIVE,
                score=0.0,
                passed=False,
                weight=self.config.get("weights", {}).get("l4_comparative", 0.15),
                skipped=True,
                skip_reason="L0 failed",
            )
            result.layers[Level.L4_COMPARATIVE.value] = l4_layer

        # 故障分类
        if result.failure_class is None:
            result.failure_class = classify_failure(
                audit=audit,
                http_errors=http_errors,
                l0_passed=l0_passed,
                l1_passed=l1_passed,
                l2_score=l2_score,
                l3_failed_dimensions=l3_failed_dims,
                l3_total_dimensions=l3_total_dims,
            )

    def _finalize(
        self,
        result: CaseRunResult,
        start_time: float,
        http_errors: list[dict[str, Any]],
        audit: AuditSnapshot | None,
    ) -> CaseRunResult:
        """计算最终聚合分数和成本。"""
        elapsed_ms = (time.monotonic() - start_time) * 1000
        result.latency_ms = elapsed_ms

        # 成本
        if audit:
            result.cost = CostBreakdown(
                total_cost_usd=audit.cost.total_cost_usd,
                sut_cost_usd=audit.cost.total_cost_usd,
                judge_cost_usd=0.0,
                per_stage_cost=audit.cost.per_stage_cost,
                per_provider_cost=audit.cost.per_provider_cost,
            )
            result.tokens = TokenBreakdown(
                total_input_tokens=audit.trace.total_input_tokens,
                total_output_tokens=audit.trace.total_output_tokens,
                total_tokens=audit.trace.total_tokens,
                sut_input_tokens=audit.trace.total_input_tokens,
                sut_output_tokens=audit.trace.total_output_tokens,
            )
            result.audit = audit
        else:
            result.audit = audit

        # 聚合加权分数（L0 硬门槛，L1-L4 加权）
        weights = self.config.get("weights", {})
        w1 = weights.get("l1_process_integrity", 0.20)
        w2 = weights.get("l2_internal_quality", 0.20)
        w3 = weights.get("l3_semantic", 0.45)
        w4 = weights.get("l4_comparative", 0.15)

        l0 = result.layers.get(Level.L0_HEALTH.value)
        l1 = result.layers.get(Level.L1_PROCESS.value)
        l2 = result.layers.get(Level.L2_INTERNAL.value)
        l3 = result.layers.get(Level.L3_SEMANTIC.value)
        l4 = result.layers.get(Level.L4_COMPARATIVE.value)

        # 如果 L0 失败，总分 0
        if l0 and not l0.passed:
            result.aggregate_score = 0.0
            result.passed = False
        else:
            scores = []
            total_w = 0.0
            if l1 and not l1.skipped:
                scores.append((l1.score, w1))
                total_w += w1
            if l2 and not l2.skipped:
                scores.append((l2.score, w2))
                total_w += w2
            if l3 and not l3.skipped:
                scores.append((l3.score, w3))
                total_w += w3
            if l4 and not l4.skipped:
                scores.append((l4.score, w4))
                total_w += w4

            if total_w > 0:
                weighted = sum(s * w for s, w in scores) / total_w
            else:
                # 所有层都 skipped（不应该发生，但做防御）
                weighted = 0.5
            result.aggregate_score = weighted * 100
            result.passed = weighted >= 0.6 and (l0.passed if l0 else True)

        return result
