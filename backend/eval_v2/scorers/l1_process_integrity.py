"""L1 Process Integrity Scorer.

Evaluates whether the multi-agent pipeline completed correctly:
- Terminal state correctness
- Stage completion
- Stub fallback detection (4-signal composite)
- Degradation events
- Circuit breaker
- Drift rate
- Conflict resolution
- Iteration count
"""

from __future__ import annotations

from typing import Any

from eval_v2.models.audit import AuditSnapshot
from eval_v2.models.enums import FailureClass, Level
from eval_v2.models.result import CheckResult, FailureRecord
from eval_v2.scorers.base import ScorerBase, ScorerResult


class L1ProcessIntegrityScorer(ScorerBase):
    """L1 流程完整性评分器（权重 0.20）。"""

    level = Level.L1_PROCESS

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        w = config or {}
        self.weights = {
            "terminal_state_correct": w.get("terminal_state_correct_weight", 0.20),
            "expected_stages_completed": w.get("expected_stages_completed_weight", 0.15),
            "no_stub_fallback": w.get("no_stub_fallback_weight", 0.15),
            "no_critical_degradation": w.get("no_critical_degradation_events_weight", 0.15),
            "no_circuit_breaker": w.get("no_circuit_breaker_weight", 0.10),
            "drift_acceptable": w.get("drift_acceptable_weight", 0.10),
            "conflict_resolution": w.get("conflict_resolution_weight", 0.10),
            "iteration_normal": w.get("iteration_normal_weight", 0.05),
        }
        self.drift_threshold = w.get("drift_acceptable_threshold", 0.3)
        self.stub_token_threshold = w.get("stub_token_threshold", 10)
        self.stub_cost_threshold = w.get("stub_cost_threshold", 0.0001)

    async def score(
        self,
        audit: AuditSnapshot,
        raw_progress: dict[str, Any] | None = None,
        raw_meeting: dict[str, Any] | None = None,
        http_errors: list[dict[str, Any]] | None = None,
    ) -> ScorerResult:
        checks: list[CheckResult] = []
        failures: list[FailureRecord] = []
        m = audit.meeting
        t = audit.trace

        # 1. terminal_state_correct: status=done AND stage=produce
        # 但对于提前终止的用例（如空 topic 预期在 clarify 结束），需要特殊处理
        terminal_ok = m.status == "done" and m.stage == "produce"
        checks.append(
            self._make_check(
                "terminal_state_correct",
                terminal_ok,
                self.weights["terminal_state_correct"],
                evidence=f"status={m.status}, stage={m.stage}",
                detail=f"Expected status=done, stage=produce; got status={m.status}, stage={m.stage}",
            )
        )
        if not terminal_ok:
            failures.append(
                FailureRecord(
                    failure_class=FailureClass.MODEL,
                    stage=m.stage,
                    check_name="terminal_state_correct",
                    detail=f"Terminal state incorrect: status={m.status}, stage={m.stage}, error={m.error_detail[:200]}",
                )
            )

        # 2. expected_stages_completed: 标准流程的关键阶段应完成
        # 六阶段：clarify -> intra_team -> cross_team -> evidence_check -> arbitrate -> produce
        all_stages = ["clarify", "intra_team", "cross_team", "evidence_check", "arbitrate", "produce"]
        # 检查是否有 produce 阶段的产出（artifact 存在或 quality_score > 0）
        has_produce_output = m.artifact_available and m.artifact_length > 0
        # 检查完成的阶段
        stages_seen = set(m.completed_stages)
        # 如果状态是 done 且有 artifact，认为关键阶段完成
        stages_ok = terminal_ok and has_produce_output
        # 如果用了 fast/fast_path/instant 流程，阶段数可能不同
        if m.flow_plan in ("instant", "fast", "fast_path"):
            stages_ok = terminal_ok  # 快速流程只检查终态
        checks.append(
            self._make_check(
                "expected_stages_completed",
                stages_ok,
                self.weights["expected_stages_completed"],
                evidence=(
                    f"completed_stages={m.completed_stages}, artifact_available={m.artifact_available}, "
                    f"flow_plan={m.flow_plan}"
                ),
            )
        )
        if not stages_ok and not failures:  # 不重复记录
            failures.append(
                FailureRecord(
                    failure_class=FailureClass.MODEL,
                    check_name="expected_stages_completed",
                    detail=f"Expected stages not completed. completed={m.completed_stages}, artifact={m.artifact_available}",
                )
            )

        # 3. no_stub_fallback: 综合 4 信号检测
        # 信号1: total_tokens 极低（< threshold）
        signal_low_tokens = t.total_tokens < self.stub_token_threshold
        # 信号2: trace_events 含 stub_fallback
        signal_stub_event = t.stub_fallbacks > 0
        # 信号3: cost 极低
        signal_low_cost = audit.cost.total_cost_usd < self.stub_cost_threshold
        # 信号4: 有 fallback 状态的调用
        signal_fallback_calls = sum(1 for c in t.calls if c.status == "fallback")
        has_stub = signal_stub_event or (signal_low_tokens and signal_low_cost) or signal_fallback_calls > 0
        no_stub = not has_stub
        checks.append(
            self._make_check(
                "no_stub_fallback",
                no_stub,
                self.weights["no_stub_fallback"],
                evidence=(
                    f"total_tokens={t.total_tokens}, stub_events={t.stub_fallbacks}, "
                    f"cost={audit.cost.total_cost_usd:.6f}, fallback_calls={signal_fallback_calls}"
                ),
                detail="LLM degraded to stub/fallback" if has_stub else "",
            )
        )
        if has_stub:
            failures.append(
                FailureRecord(
                    failure_class=FailureClass.MODEL,
                    check_name="no_stub_fallback",
                    detail=(
                        f"Stub fallback detected: tokens={t.total_tokens}, "
                        f"stub_events={t.stub_fallbacks}, cost={audit.cost.total_cost_usd:.6f}"
                    ),
                )
            )

        # 4. no_critical_degradation_events
        has_critical = audit.degradation.has_critical_degradation
        checks.append(
            self._make_check(
                "no_critical_degradation_events",
                not has_critical,
                self.weights["no_critical_degradation"],
                evidence=f"high_severity_warnings={audit.degradation.high_severity}, total={audit.degradation.total_warnings}",
                detail=f"Degradation types: {audit.degradation.warning_types}" if has_critical else "",
            )
        )
        if has_critical:
            failures.append(
                FailureRecord(
                    failure_class=FailureClass.MODEL,
                    check_name="no_critical_degradation_events",
                    detail=f"Critical degradation events: {audit.degradation.high_severity} high severity warnings",
                )
            )

        # 5. no_circuit_breaker
        no_cb = t.circuit_breaker_trips == 0
        checks.append(
            self._make_check(
                "no_circuit_breaker",
                no_cb,
                self.weights["no_circuit_breaker"],
                evidence=f"circuit_breaker_trips={t.circuit_breaker_trips}",
            )
        )
        if not no_cb:
            failures.append(
                FailureRecord(
                    failure_class=FailureClass.INFRASTRUCTURE,
                    check_name="no_circuit_breaker",
                    detail=f"Circuit breaker tripped {t.circuit_breaker_trips} times",
                )
            )

        # 6. drift_acceptable
        drift_rate = m.drift_detected / m.total_checks if m.total_checks > 0 else 0.0
        drift_ok = drift_rate <= self.drift_threshold
        checks.append(
            self._make_check(
                "drift_acceptable",
                drift_ok,
                self.weights["drift_acceptable"],
                score=max(0.0, 1.0 - drift_rate / self.drift_threshold) if not drift_ok else 1.0,
                evidence=f"drift={m.drift_detected}/{m.total_checks} = {drift_rate:.2%}",
            )
        )
        if not drift_ok:
            failures.append(
                FailureRecord(
                    failure_class=FailureClass.MODEL,
                    check_name="drift_acceptable",
                    detail=f"Drift rate too high: {drift_rate:.2%} (threshold {self.drift_threshold:.0%})",
                )
            )

        # 7. conflict_resolution_complete
        # 关键修复：0 conflicts 是合理结果，不扣分
        if m.conflicts_count == 0:
            conflict_ok = True
            conflict_detail = "No conflicts detected (consensus reached)"
        else:
            # 有冲突时，decisions 应 >= conflicts（不一定1:1，因为一个decision可能解决多个conflict）
            conflict_ok = m.decisions_count >= m.conflicts_count * 0.5
            conflict_detail = f"conflicts={m.conflicts_count}, decisions={m.decisions_count}"
        checks.append(
            self._make_check(
                "conflict_resolution_complete",
                conflict_ok,
                self.weights["conflict_resolution"],
                evidence=conflict_detail,
            )
        )
        if not conflict_ok:
            failures.append(
                FailureRecord(
                    failure_class=FailureClass.MODEL,
                    check_name="conflict_resolution_complete",
                    detail=f"Unresolved conflicts: {m.conflicts_count} conflicts but only {m.decisions_count} decisions",
                )
            )

        # 8. iteration_normal
        iter_ok = m.iteration_count <= m.max_iterations
        checks.append(
            self._make_check(
                "iteration_normal",
                iter_ok,
                self.weights["iteration_normal"],
                evidence=f"iterations={m.iteration_count}/{m.max_iterations}",
            )
        )
        if not iter_ok:
            failures.append(
                FailureRecord(
                    failure_class=FailureClass.MODEL,
                    check_name="iteration_normal",
                    detail=f"Too many iterations: {m.iteration_count} > max {m.max_iterations}",
                )
            )

        score = self._weighted_score(checks)
        passed = score >= 0.6 and all(
            c.passed
            for c in [
                checks[0],  # terminal_state_correct 必须通过
                checks[2],  # no_stub_fallback 必须通过
            ]
        )

        return ScorerResult(
            score=score,
            passed=passed,
            weight=self.config.get("weight", 0.20) if self.config else 0.20,
            confidence=1.0,
            sub_scores={c.check_name: c.score for c in checks},
            details=checks,
            failures=failures,
        )
