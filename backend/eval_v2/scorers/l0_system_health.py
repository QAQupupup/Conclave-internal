"""L0 System Health Scorer - hard gate for infrastructure failures."""

from __future__ import annotations

from typing import Any

from eval_v2.models.audit import AuditSnapshot
from eval_v2.models.enums import FailureClass, Level
from eval_v2.models.result import CheckResult, FailureRecord
from eval_v2.scorers.base import ScorerBase, ScorerResult


class L0SystemHealthScorer(ScorerBase):
    """L0 系统健康检查（硬门槛）。

    任何 L0 检查项失败 → failure_class=INFRASTRUCTURE，
    该用例标记为基础设施故障，不调用 L1-L4 评分。
    """

    level = Level.L0_HEALTH

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.weights = {
            "service_reachable": config.get("service_reachable_weight", 0.30) if config else 0.30,
            "auth_valid": config.get("auth_valid_weight", 0.25) if config else 0.25,
            "meeting_created": config.get("meeting_created_weight", 0.20) if config else 0.20,
            "audit_endpoint_available": config.get("audit_endpoint_weight", 0.15) if config else 0.15,
            "no_http_5xx": config.get("no_http_5xx_weight", 0.10) if config else 0.10,
        }

    async def score(
        self,
        audit: AuditSnapshot,
        raw_progress: dict[str, Any] | None = None,
        raw_meeting: dict[str, Any] | None = None,
        http_errors: list[dict[str, Any]] | None = None,
    ) -> ScorerResult:
        checks: list[CheckResult] = []
        failures: list[FailureRecord] = []
        http_errors = http_errors or []

        # 1. service_reachable: 有 audit 数据或 meeting 数据说明服务可达
        service_ok = audit is not None and audit.meeting.meeting_id != ""
        checks.append(
            self._make_check(
                "service_reachable",
                service_ok,
                self.weights["service_reachable"],
                evidence=f"meeting_id={audit.meeting.meeting_id}" if service_ok else "no meeting data",
            )
        )
        if not service_ok:
            failures.append(
                FailureRecord(
                    failure_class=FailureClass.INFRASTRUCTURE,
                    check_name="service_reachable",
                    detail="SUT service unreachable or returned no meeting data",
                )
            )

        # 2. auth_valid: 如果有 http_errors 中的 401/403，认证失败
        auth_errors = [e for e in http_errors if e.get("status") in (401, 403)]
        auth_ok = len(auth_errors) == 0
        checks.append(
            self._make_check(
                "auth_valid",
                auth_ok,
                self.weights["auth_valid"],
                evidence="no 401/403 errors" if auth_ok else f"auth errors: {[e.get('status') for e in auth_errors]}",
            )
        )
        if not auth_ok:
            failures.append(
                FailureRecord(
                    failure_class=FailureClass.INFRASTRUCTURE,
                    check_name="auth_valid",
                    detail=f"Authentication failed: {[e.get('detail', '')[:100] for e in auth_errors]}",
                )
            )

        # 3. meeting_created: meeting_id 存在
        meeting_created = audit.meeting.meeting_id != "" if audit else False
        checks.append(
            self._make_check(
                "meeting_created",
                meeting_created,
                self.weights["meeting_created"],
                evidence=f"meeting_id={audit.meeting.meeting_id}" if meeting_created else "no meeting_id",
            )
        )
        if not meeting_created:
            failures.append(
                FailureRecord(
                    failure_class=FailureClass.INFRASTRUCTURE,
                    check_name="meeting_created",
                    detail="Meeting was not created successfully",
                )
            )

        # 4. audit_endpoint_available: audit 中有 trace 或 cost 数据
        audit_ok = audit is not None and (
            audit.trace.total_calls > 0 or len(audit.cost.cost_records) > 0 or audit.meeting.status != ""
        )
        checks.append(
            self._make_check(
                "audit_endpoint_available",
                audit_ok,
                self.weights["audit_endpoint_available"],
                evidence=(
                    f"trace_calls={audit.trace.total_calls}, status={audit.meeting.status}"
                    if audit
                    else "no audit data"
                ),
            )
        )
        if not audit_ok:
            # 审计端点不可用不一定是基础设施故障（可能是会议刚启动），
            # 但如果其他检查也失败则标记
            if not service_ok or not meeting_created:
                failures.append(
                    FailureRecord(
                        failure_class=FailureClass.INFRASTRUCTURE,
                        check_name="audit_endpoint_available",
                        detail="Audit endpoint returned no usable data",
                    )
                )

        # 5. no_http_5xx: 检查 http_errors 中的 5xx 和 402
        server_errors = [e for e in http_errors if e.get("status", 0) >= 500 or e.get("status") == 402]
        # 也检查 trace 中的 circuit_breaker
        circuit_breaker = audit.trace.circuit_breaker_trips if audit else 0
        no_5xx = len(server_errors) == 0 and circuit_breaker == 0
        checks.append(
            self._make_check(
                "no_http_5xx",
                no_5xx,
                self.weights["no_http_5xx"],
                evidence=(
                    f"server_errors={len(server_errors)}, circuit_breaker_trips={circuit_breaker}"
                    if not no_5xx
                    else "no 5xx/402/circuit_breaker errors"
                ),
            )
        )
        if not no_5xx:
            for e in server_errors:
                failures.append(
                    FailureRecord(
                        failure_class=FailureClass.INFRASTRUCTURE,
                        check_name="no_http_5xx",
                        detail=f"HTTP {e.get('status')}: {e.get('detail', '')[:200]}",
                        stage=e.get("stage", ""),
                    )
                )
            if circuit_breaker > 0:
                failures.append(
                    FailureRecord(
                        failure_class=FailureClass.INFRASTRUCTURE,
                        check_name="no_http_5xx",
                        detail=f"Circuit breaker tripped {circuit_breaker} times",
                    )
                )

        score = self._weighted_score(checks)
        passed = all(c.passed for c in checks)

        return ScorerResult(
            score=score,
            passed=passed,
            weight=0.0,  # L0 is hard gate, not included in weighted aggregate
            confidence=1.0,
            details=checks,
            failures=failures,
        )
