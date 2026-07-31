"""Failure classification - three-way decision tree.

Distinguishes between:
- INFRASTRUCTURE: HTTP errors, auth failures, connection issues, circuit breakers
- MODEL: stub fallbacks, low quality scores, degradation, semantic failures
- TEST_BUG: invalid test cases, configuration errors, framework bugs
"""

from __future__ import annotations

from typing import Any

from eval_v2.models.audit import AuditSnapshot
from eval_v2.models.enums import FailureClass


def classify_failure(
    audit: AuditSnapshot | None,
    http_errors: list[dict[str, Any]] | None = None,
    l0_passed: bool = True,
    l1_passed: bool = True,
    l2_score: float = 1.0,
    l3_failed_dimensions: int = 0,
    l3_total_dimensions: int = 0,
) -> FailureClass:
    """三分类决策树，判定失败原因。

    优先级：INFRASTRUCTURE > TEST_BUG > MODEL
    """
    http_errors = http_errors or []

    # 1. 基础设施故障检测
    # HTTP 5xx
    for e in http_errors:
        status = e.get("status", 0)
        if status >= 500 or status in (401, 403, 402, 408):
            return FailureClass.INFRASTRUCTURE
        if isinstance(e.get("error"), str) and "timeout" in e["error"].lower():
            return FailureClass.INFRASTRUCTURE
        if isinstance(e.get("error"), str) and "connect" in e["error"].lower():
            return FailureClass.INFRASTRUCTURE

    # 连接类错误（无 status 字段的）
    for e in http_errors:
        err = e.get("error", "")
        if isinstance(err, str) and any(
            kw in err.lower() for kw in ("connect", "timeout", "connection", "refused", "reset")
        ):
            return FailureClass.INFRASTRUCTURE

    if audit:
        # circuit_breaker 触发
        if audit.trace.circuit_breaker_trips > 0:
            return FailureClass.INFRASTRUCTURE

        # provider_switch 过多（>=3 次说明基础设施不稳定）
        if audit.trace.provider_switches >= 3:
            return FailureClass.INFRASTRUCTURE

    # 2. L0 失败 = 基础设施
    if not l0_passed:
        return FailureClass.INFRASTRUCTURE

    # 3. 测试缺陷检测（暂不实现，需要测试框架支持）

    # 4. 模型/系统能力缺陷
    if audit:
        # stub fallback
        if audit.trace.stub_fallbacks > 0:
            return FailureClass.MODEL

        # 低质量分
        if audit.meeting.quality_score < 60 and audit.meeting.quality_score > 0:
            return FailureClass.MODEL

        # critical degradation
        if audit.degradation.has_critical_degradation:
            return FailureClass.MODEL

        # hard failures
        if audit.meeting.hard_failures:
            return FailureClass.MODEL

        # 终态不正确
        if audit.meeting.status != "done" or audit.meeting.stage != "produce":
            return FailureClass.MODEL

    # L3 语义失败（超过一半维度 likert < 3）
    if l3_total_dimensions > 0 and l3_failed_dimensions > l3_total_dimensions / 2:
        return FailureClass.MODEL

    # L2 分数过低
    if l2_score < 0.5:
        return FailureClass.MODEL

    # 默认归类为模型问题
    return FailureClass.MODEL
