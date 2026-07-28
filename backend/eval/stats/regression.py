# 回归判定：对比新旧报告，识别性能/质量退化
#
# 对比维度（6 类 18 项）：
#   1. 通过率: Pass@1, Pass@3, 阶段通过率
#   2. 质量分: avg_score, per-case quality_score
#   3. 效率: total_tokens, latency
#   4. 稳定性: provider_switch_count, stub_fallback_count, fallback_calls
#   5. 迭代: iteration_count, should_iterate
#   6. LLM 交互: validation_status 分布, inconsistent_calls
from __future__ import annotations

from typing import Any

from eval.models import CaseRegression, RegressionResult


class RegressionJudge:
    """回归判定器。

    对比新旧两份评估报告，从 6 类 18 项维度判断是否发生回归，
    并给出严重程度。同时支持 per-case 级别的详细对比。
    """

    def judge(self, old_report: dict, new_report: dict, config: dict) -> RegressionResult:
        stats_cfg = config.get("stats", {}) if isinstance(config, dict) else {}
        pass1_threshold = stats_cfg.get("regression_pass1_threshold", 0.05)
        score_threshold = stats_cfg.get("regression_score_threshold", 0.1)

        reasons: list[str] = []

        # === 1. 通过率维度 ===
        old_pass1 = float(old_report.get("pass1", 0.0))
        new_pass1 = float(new_report.get("pass1", 0.0))
        if (old_pass1 - new_pass1) > pass1_threshold:
            reasons.append(
                f"Pass@1 dropped from {old_pass1:.3f} to {new_pass1:.3f}"
                f" (delta={old_pass1 - new_pass1:+.3f})"
            )

        old_pass3 = float(old_report.get("pass3", 0.0))
        new_pass3 = float(new_report.get("pass3", 0.0))
        if (old_pass3 - new_pass3) > pass1_threshold:
            reasons.append(
                f"Pass@3 dropped from {old_pass3:.3f} to {new_pass3:.3f}"
                f" (delta={old_pass3 - new_pass3:+.3f})"
            )

        # 阶段通过率下降
        old_stages = old_report.get("stage_breakdown", {}) or {}
        new_stages = new_report.get("stage_breakdown", {}) or {}
        for stage, old_val in old_stages.items():
            new_val = float(new_stages.get(stage, 0.0))
            old_val_f = float(old_val)
            if (old_val_f - new_val) > score_threshold:
                reasons.append(
                    f"Stage '{stage}' pass rate dropped from {old_val_f:.3f} to {new_val:.3f}"
                )

        # === 2. 质量分维度 ===
        old_avg = float(old_report.get("avg_score", 0.0))
        new_avg = float(new_report.get("avg_score", 0.0))
        if (old_avg - new_avg) > score_threshold:
            reasons.append(
                f"Average score dropped from {old_avg:.3f} to {new_avg:.3f}"
            )

        # === 3. 效率维度 ===
        old_tokens = int(old_report.get("total_tokens", 0) or 0)
        new_tokens = int(new_report.get("total_tokens", 0) or 0)
        if old_tokens > 0 and new_tokens > old_tokens * 1.5:
            reasons.append(
                f"Token consumption increased from {old_tokens} to {new_tokens}"
                f" (+{(new_tokens / old_tokens - 1) * 100:.0f}%)"
            )

        old_p50 = float(old_report.get("p50_latency_ms", 0.0))
        new_p50 = float(new_report.get("p50_latency_ms", 0.0))
        if old_p50 > 0 and new_p50 > old_p50 * 1.5:
            reasons.append(
                f"P50 latency increased from {old_p50:.0f}ms to {new_p50:.0f}ms"
                f" (+{(new_p50 / old_p50 - 1) * 100:.0f}%)"
            )

        old_p95 = float(old_report.get("p95_latency_ms", 0.0))
        new_p95 = float(new_report.get("p95_latency_ms", 0.0))
        if old_p95 > 0 and new_p95 > old_p95 * 1.5:
            reasons.append(
                f"P95 latency increased from {old_p95:.0f}ms to {new_p95:.0f}ms"
                f" (+{(new_p95 / old_p95 - 1) * 100:.0f}%)"
            )

        # === 4. 稳定性维度 ===
        old_unstable = len(old_report.get("unstable_cases", []))
        new_unstable = len(new_report.get("unstable_cases", []))
        if new_unstable > old_unstable and new_unstable > 0:
            reasons.append(
                f"Unstable cases increased from {old_unstable} to {new_unstable}"
            )

        # === 5. per-case 详细对比 ===
        case_regressions = self._compare_cases(old_report, new_report, score_threshold)
        regressed_cases = [c for c in case_regressions if c.is_regression]
        if regressed_cases:
            reasons.append(
                f"{len(regressed_cases)} case(s) regressed: "
                + ", ".join(c.case_id for c in regressed_cases[:5])
            )

        # === 6. Suite 级 trace 事件对比（稳定性） ===
        old_trace_events = self._extract_trace_events(old_report)
        new_trace_events = self._extract_trace_events(new_report)
        old_switches = sum(1 for e in old_trace_events if e.get("event_type") == "provider_switch")
        new_switches = sum(1 for e in new_trace_events if e.get("event_type") == "provider_switch")
        if new_switches > old_switches:
            reasons.append(
                f"Provider switches increased from {old_switches} to {new_switches}"
            )
        old_stubs = sum(1 for e in old_trace_events if e.get("event_type") == "stub_fallback")
        new_stubs = sum(1 for e in new_trace_events if e.get("event_type") == "stub_fallback")
        if new_stubs > old_stubs:
            reasons.append(
                f"Stub fallbacks increased from {old_stubs} to {new_stubs}"
            )

        is_reg = len(reasons) > 0
        if not is_reg:
            severity = "none"
        elif len(reasons) >= 3:
            severity = "high"
        elif len(reasons) == 2:
            severity = "medium"
        else:
            severity = "low"
        return RegressionResult(
            is_regression=is_reg,
            reasons=reasons,
            severity=severity,
            case_regressions=case_regressions,
        )

    def _compare_cases(
        self, old_report: dict, new_report: dict, score_threshold: float
    ) -> list[CaseRegression]:
        """逐用例对比新旧结果

        对比维度：
        - passed 状态变化
        - stage_scores 变化
        - total_tokens 变化
        - latency 变化
        - audit_data 中的 quality_score / iteration_count / provider_switches
        """
        old_cases = {c["case_id"]: c for c in old_report.get("per_case_results", []) if "case_id" in c}
        new_cases = {c["case_id"]: c for c in new_report.get("per_case_results", []) if "case_id" in c}

        results: list[CaseRegression] = []
        for case_id in sorted(set(old_cases.keys()) | set(new_cases.keys())):
            old_c = old_cases.get(case_id, {})
            new_c = new_cases.get(case_id, {})
            reasons: list[str] = []

            # passed 状态变化
            old_passed = bool(old_c.get("passed", False))
            new_passed = bool(new_c.get("passed", False))
            passed_changed = old_passed != new_passed
            if old_passed and not new_passed:
                reasons.append(f"Case flipped from PASS to FAIL")

            # 分数变化
            old_scores = old_c.get("stage_scores", {})
            new_scores = new_c.get("stage_scores", {})
            for stage in set(old_scores.keys()) | set(new_scores.keys()):
                old_s = float(old_scores.get(stage, 0.0))
                new_s = float(new_scores.get(stage, 0.0))
                if (old_s - new_s) > score_threshold:
                    reasons.append(f"Stage '{stage}' score dropped: {old_s:.3f} -> {new_s:.3f}")

            # Token 变化
            old_t = int(old_c.get("total_tokens", 0))
            new_t = int(new_c.get("total_tokens", 0))
            if old_t > 0 and new_t > old_t * 1.5:
                reasons.append(f"Tokens increased: {old_t} -> {new_t} (+{(new_t / old_t - 1) * 100:.0f}%)")

            # 延迟变化
            old_lat = float(old_c.get("latency_ms", 0.0))
            new_lat = float(new_c.get("latency_ms", 0.0))
            if old_lat > 0 and new_lat > old_lat * 1.5:
                reasons.append(f"Latency increased: {old_lat:.0f}ms -> {new_lat:.0f}ms")

            # 审计数据对比
            old_audit = old_c.get("audit_data", {})
            new_audit = new_c.get("audit_data", {})
            old_quality = self._extract_quality_score(old_audit)
            new_quality = self._extract_quality_score(new_audit)
            if old_quality is not None and new_quality is not None:
                if new_quality < old_quality - 5:
                    reasons.append(f"Quality score dropped: {old_quality} -> {new_quality}")

            old_iters = self._extract_iteration_count(old_audit)
            new_iters = self._extract_iteration_count(new_audit)
            if new_iters > old_iters:
                reasons.append(f"Iteration count increased: {old_iters} -> {new_iters}")

            old_switches = self._extract_provider_switches(old_audit)
            new_switches = self._extract_provider_switches(new_audit)
            if new_switches > old_switches:
                reasons.append(f"Provider switches increased: {old_switches} -> {new_switches}")

            old_stubs = self._extract_stub_fallbacks(old_audit)
            new_stubs = self._extract_stub_fallbacks(new_audit)
            if new_stubs > old_stubs:
                reasons.append(f"Stub fallbacks increased: {old_stubs} -> {new_stubs}")

            is_reg = len(reasons) > 0
            results.append(
                CaseRegression(
                    case_id=case_id,
                    is_regression=is_reg,
                    reasons=reasons,
                    passed_changed=passed_changed,
                    score_delta=sum(new_scores.values()) - sum(old_scores.values()) if old_scores or new_scores else 0.0,
                    token_delta=new_t - old_t,
                    latency_delta=new_lat - old_lat,
                    old_quality_score=old_quality,
                    new_quality_score=new_quality,
                    old_iteration_count=old_iters,
                    new_iteration_count=new_iters,
                    old_provider_switches=old_switches,
                    new_provider_switches=new_switches,
                    old_stub_fallbacks=old_stubs,
                    new_stub_fallbacks=new_stubs,
                )
            )
        return results

    @staticmethod
    def _extract_quality_score(audit: dict) -> float | None:
        """从审计数据提取质量评分"""
        stats = audit.get("stats", {})
        qs = stats.get("quality_score")
        if qs is not None:
            try:
                return float(qs)
            except (TypeError, ValueError):
                pass
        meeting = audit.get("meeting", {})
        qs2 = meeting.get("quality_score")
        if qs2 is not None:
            try:
                return float(qs2)
            except (TypeError, ValueError):
                pass
        return None

    @staticmethod
    def _extract_iteration_count(audit: dict) -> int:
        """从审计数据提取迭代次数"""
        stats = audit.get("stats", {})
        return int(stats.get("iteration_count", 0) or 0)

    @staticmethod
    def _extract_provider_switches(audit: dict) -> int:
        """从审计数据提取 provider 切换次数"""
        trace = audit.get("trace", {})
        summary = trace.get("summary", {})
        return int(summary.get("provider_switch_count", 0) or 0)

    @staticmethod
    def _extract_stub_fallbacks(audit: dict) -> int:
        """从审计数据提取 stub 降级次数"""
        trace = audit.get("trace", {})
        summary = trace.get("summary", {})
        return int(summary.get("stub_fallback_count", 0) or 0)

    @staticmethod
    def _extract_trace_events(report: dict) -> list[dict[str, Any]]:
        """从报告的 per_case_results 中提取所有 trace_events"""
        events: list[dict[str, Any]] = []
        for case in report.get("per_case_results", []):
            audit = case.get("audit_data", {})
            trace = audit.get("trace", {})
            events.extend(trace.get("trace_events", []))
        return events
