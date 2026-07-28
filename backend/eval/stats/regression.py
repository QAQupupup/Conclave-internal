# 回归判定：对比新旧报告，识别性能/质量退化
from __future__ import annotations

from eval.models import RegressionResult


class RegressionJudge:
    """回归判定器。

    对比新旧两份评估报告，从 Pass@1、阶段通过率、平均分、Token 消耗四个维度
    判断是否发生回归，并给出严重程度。
    """

    def judge(self, old_report: dict, new_report: dict, config: dict) -> RegressionResult:
        stats_cfg = config.get("stats", {}) if isinstance(config, dict) else {}
        pass1_threshold = stats_cfg.get("regression_pass1_threshold", 0.05)
        score_threshold = stats_cfg.get("regression_score_threshold", 0.1)

        reasons: list[str] = []

        # 1. Pass@1 下降
        old_pass1 = float(old_report.get("pass1", 0.0))
        new_pass1 = float(new_report.get("pass1", 0.0))
        if (old_pass1 - new_pass1) > pass1_threshold:
            reasons.append(
                f"Pass@1 dropped from {old_pass1:.3f} to {new_pass1:.3f}"
                f" (delta={old_pass1 - new_pass1:+.3f})"
            )

        # 2. 阶段通过率下降
        old_stages = old_report.get("stage_breakdown", {}) or {}
        new_stages = new_report.get("stage_breakdown", {}) or {}
        for stage, old_val in old_stages.items():
            new_val = float(new_stages.get(stage, 0.0))
            old_val_f = float(old_val)
            if (old_val_f - new_val) > score_threshold:
                reasons.append(
                    f"Stage '{stage}' pass rate dropped from {old_val_f:.3f} to {new_val:.3f}"
                )

        # 3. 平均分下降
        old_avg = float(old_report.get("avg_score", 0.0))
        new_avg = float(new_report.get("avg_score", 0.0))
        if (old_avg - new_avg) > score_threshold:
            reasons.append(
                f"Average score dropped from {old_avg:.3f} to {new_avg:.3f}"
            )

        # 4. Token 消耗显著增加（>50% 视为异常）
        old_tokens = int(old_report.get("total_tokens", 0) or 0)
        new_tokens = int(new_report.get("total_tokens", 0) or 0)
        if old_tokens > 0 and new_tokens > old_tokens * 1.5:
            reasons.append(
                f"Token consumption increased from {old_tokens} to {new_tokens}"
                f" (+{(new_tokens / old_tokens - 1) * 100:.0f}%)"
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
        return RegressionResult(is_regression=is_reg, reasons=reasons, severity=severity)
