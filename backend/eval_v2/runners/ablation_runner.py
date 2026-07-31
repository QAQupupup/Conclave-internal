"""Ablation study runner - compares Multi-Agent pipeline vs Direct LLM baseline."""

from __future__ import annotations

import logging
from typing import Any

from eval_v2.ablation.comparator import AblationComparator
from eval_v2.ablation.direct_llm import DirectLLMBaseline
from eval_v2.models.case import EvalCase
from eval_v2.models.result import AblationComparison, CaseRunResult
from eval_v2.runners.suite_runner import SuiteRunner

logger = logging.getLogger(__name__)


class AblationRunner:
    """消融实验执行器。"""

    def __init__(self, suite_runner: SuiteRunner, config: dict[str, Any]):
        self.suite_runner = suite_runner
        self.config = config
        self.direct_llm = DirectLLMBaseline(
            temperature=config.get("ablation", {}).get("direct_llm_temperature", 0.1),
            max_tokens=config.get("ablation", {}).get("direct_llm_max_tokens", 8192),
        )
        self.comparator: AblationComparator | None = None

    async def run_ablation(
        self,
        cases: list[EvalCase],
        multi_agent_results: list[CaseRunResult],
    ) -> AblationComparison:
        """运行消融实验。"""
        judge = self.suite_runner.judge_client
        if not judge or not judge.available:
            logger.warning("Judge not available, skipping ablation pairwise comparison")
            return AblationComparison()

        self.comparator = AblationComparator(judge)
        self.direct_llm.configure_from_sut(
            llm_model=self.suite_runner.model_info.model if self.suite_runner.model_info else "",
            llm_base_url=self.config.get("target", {}).get("llm_base_url", ""),
            llm_api_key_env=self.config.get("target", {}).get("llm_api_key_env", ""),
        )

        if not self.direct_llm.available:
            logger.warning("Direct LLM baseline not configured, skipping ablation")
            return AblationComparison()

        comparisons = []

        for case in cases:
            # 获取 Multi-Agent 产出
            ma_result = next(
                (r for r in multi_agent_results if r.case_id == case.case_id and r.run_index == 0),
                None,
            )
            if not ma_result or not ma_result.audit:
                continue

            ma_text = ma_result.audit.get_artifact_text()
            if not ma_text or len(ma_text) < 50:
                continue

            # 生成 Direct LLM 基线
            logger.info(f"Running Direct LLM baseline for {case.case_id}...")
            dl_result = await self.direct_llm.generate(
                topic=case.topic,
                deliverable_type=case.config.deliverable_type.value,
            )

            if not dl_result["success"]:
                continue

            dl_text = dl_result["text"]

            # Pairwise 比较
            comparison = await self.comparator.compare(
                topic=case.topic,
                multi_agent_text=ma_text,
                direct_llm_text=dl_text,
                deliverable_type=case.config.deliverable_type.value,
            )
            comparison.multi_agent_cost = ma_result.cost.total_cost_usd
            comparison.direct_llm_cost = dl_result["cost_usd"]
            comparison.multi_agent_score = ma_result.aggregate_score / 100.0
            # Direct LLM 无多层评分，用0.5作为默认
            comparison.direct_llm_score = 0.5
            comparisons.append(comparison)

        if comparisons:
            return AblationComparator.aggregate(comparisons)
        return AblationComparison()
