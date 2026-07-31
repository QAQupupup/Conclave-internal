"""Ablation comparator - pairwise blind comparison between Multi-Agent and Direct LLM."""

from __future__ import annotations

import logging

from eval_v2.llm_judge.bias_mitigation import (
    map_pairwise_winner,
    randomize_pairwise_order,
)
from eval_v2.llm_judge.client import JudgeClient
from eval_v2.llm_judge.prompts import build_judge_system_prompt, build_pairwise_prompt
from eval_v2.llm_judge.rubrics import deliverable_type_display_name
from eval_v2.models.result import AblationComparison

logger = logging.getLogger(__name__)


class AblationComparator:
    """消融实验对比器。

    使用 Pairwise 盲评比较 Conclave 多 Agent 管线 vs 单 Agent 直接生成。
    """

    def __init__(self, judge_client: JudgeClient | None = None):
        self.judge = judge_client

    async def compare(
        self,
        topic: str,
        multi_agent_text: str,
        direct_llm_text: str,
        deliverable_type: str = "prd_openapi",
    ) -> AblationComparison:
        """执行 Pairwise 对比。"""
        result = AblationComparison()

        if not self.judge or not self.judge.available:
            return result

        deliverable_name = deliverable_type_display_name(deliverable_type)

        # 位置随机化
        first, second, a_was_first, mapping = randomize_pairwise_order(multi_agent_text, direct_llm_text)

        # 确定哪个候选是 Multi-Agent
        if a_was_first:
            label_a = "Conclave多Agent系统"
            label_b = "单Agent直接生成"
        else:
            label_a = "单Agent直接生成"
            label_b = "Conclave多Agent系统"

        system_prompt = build_judge_system_prompt(deliverable_name=deliverable_name)
        user_prompt = build_pairwise_prompt(
            topic=topic,
            candidate_a=first,
            candidate_b=second,
            dimension_criteria="综合质量（准确性、完整性、可操作性、具体性）",
            deliverable_name=deliverable_name,
        )

        try:
            judgment = await self.judge.judge_pairwise(system_prompt, user_prompt, a_was_first=True)
        except Exception as e:
            logger.warning(f"Ablation pairwise judgment failed: {e}")
            return result

        if judgment is None:
            return result

        # 映射回原始候选
        winner = map_pairwise_winner(judgment.winner, a_was_first)

        if winner == "A":
            result.pairwise_wins = 1
        elif winner == "B":
            result.pairwise_losses = 1
        else:
            result.pairwise_ties = 1

        total = result.pairwise_wins + result.pairwise_losses + result.pairwise_ties
        if total > 0:
            result.pairwise_win_rate = result.pairwise_wins / total

        return result

    @staticmethod
    def aggregate(results: list[AblationComparison]) -> AblationComparison:
        """聚合多个用例的消融结果。"""
        agg = AblationComparison()
        total_wins = sum(r.pairwise_wins for r in results)
        total_losses = sum(r.pairwise_losses for r in results)
        total_ties = sum(r.pairwise_ties for r in results)
        total_comparisons = total_wins + total_losses + total_ties

        agg.pairwise_wins = total_wins
        agg.pairwise_losses = total_losses
        agg.pairwise_ties = total_ties

        if total_comparisons > 0:
            agg.pairwise_win_rate = total_wins / total_comparisons

        # 分数提升
        ma_scores = [r.multi_agent_score for r in results if r.multi_agent_score > 0]
        dl_scores = [r.direct_llm_score for r in results if r.direct_llm_score > 0]
        if ma_scores and dl_scores:
            avg_ma = sum(ma_scores) / len(ma_scores)
            avg_dl = sum(dl_scores) / len(dl_scores)
            agg.multi_agent_score = avg_ma
            agg.direct_llm_score = avg_dl
            agg.uplift = avg_ma - avg_dl

        # 成本比
        ma_costs = [r.multi_agent_cost for r in results]
        dl_costs = [r.direct_llm_cost for r in results]
        total_ma_cost = sum(ma_costs)
        total_dl_cost = sum(dl_costs)
        agg.multi_agent_cost = total_ma_cost
        agg.direct_llm_cost = total_dl_cost
        if total_dl_cost > 0:
            agg.cost_ratio = total_ma_cost / total_dl_cost

        return agg
