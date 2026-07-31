"""Cost tracking - parses real costs from audit.cost_records and adds Judge costs."""

from __future__ import annotations

from typing import Any

from eval_v2.models.audit import AuditSnapshot
from eval_v2.models.result import CostBreakdown, TokenBreakdown


class CostTracker:
    """从 audit 数据解析真实成本，追踪 Judge 调用成本。"""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.judge_input_price = self.config.get("judge_input_price_per_mtok", 0.07)
        self.judge_output_price = self.config.get("judge_output_price_per_mtok", 0.28)
        self._judge_input_tokens = 0
        self._judge_output_tokens = 0
        self._judge_cost_usd = 0.0

    def record_judge_call(self, input_tokens: int, output_tokens: int) -> float:
        """记录一次 Judge 调用的 token 使用，返回估算成本。"""
        in_cost = (input_tokens / 1_000_000) * self.judge_input_price
        out_cost = (output_tokens / 1_000_000) * self.judge_output_price
        call_cost = in_cost + out_cost
        self._judge_input_tokens += input_tokens
        self._judge_output_tokens += output_tokens
        self._judge_cost_usd += call_cost
        return call_cost

    def build_cost_breakdown(self, audit: AuditSnapshot | None) -> CostBreakdown:
        """构建完整成本明细。"""
        if audit is None:
            return CostBreakdown(
                judge_cost_usd=self._judge_cost_usd,
            )

        sut_cost = audit.cost.total_cost_usd
        total = sut_cost + self._judge_cost_usd

        return CostBreakdown(
            total_cost_usd=total,
            sut_cost_usd=sut_cost,
            judge_cost_usd=self._judge_cost_usd,
            per_stage_cost=dict(audit.cost.per_stage_cost),
            per_provider_cost=dict(audit.cost.per_provider_cost),
        )

    def build_token_breakdown(self, audit: AuditSnapshot | None) -> TokenBreakdown:
        """构建 token 明细。"""
        if audit is None:
            return TokenBreakdown(
                judge_input_tokens=self._judge_input_tokens,
                judge_output_tokens=self._judge_output_tokens,
                total_tokens=self._judge_input_tokens + self._judge_output_tokens,
            )

        return TokenBreakdown(
            total_input_tokens=audit.trace.total_input_tokens + self._judge_input_tokens,
            total_output_tokens=audit.trace.total_output_tokens + self._judge_output_tokens,
            total_tokens=audit.trace.total_tokens + self._judge_input_tokens + self._judge_output_tokens,
            sut_input_tokens=audit.trace.total_input_tokens,
            sut_output_tokens=audit.trace.total_output_tokens,
            judge_input_tokens=self._judge_input_tokens,
            judge_output_tokens=self._judge_output_tokens,
        )

    def reset(self) -> None:
        """重置 Judge 成本统计（每个用例开始前调用）。"""
        self._judge_input_tokens = 0
        self._judge_output_tokens = 0
        self._judge_cost_usd = 0.0

    @property
    def judge_cost_usd(self) -> float:
        return self._judge_cost_usd

    @property
    def judge_total_tokens(self) -> int:
        return self._judge_input_tokens + self._judge_output_tokens
