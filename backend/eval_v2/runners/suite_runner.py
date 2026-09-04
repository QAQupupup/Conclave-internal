"""Suite runner - batch execution with concurrency control and statistical aggregation."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime
from typing import Any

from eval_v2.cost.efficiency import compute_efficiency_metrics
from eval_v2.cost.tracker import CostTracker
from eval_v2.llm_judge.bias_mitigation import detect_length_bias
from eval_v2.llm_judge.client import JudgeClient
from eval_v2.models.case import EvalCase
from eval_v2.models.enums import FailureClass, Level, RunMode
from eval_v2.models.result import (
    CaseRunResult,
    ModelInfo,
    SuiteResult,
)
from eval_v2.runners.case_runner import CaseRunner
from eval_v2.runners.sut_client import SUTClient
from eval_v2.scorers.l0_system_health import L0SystemHealthScorer
from eval_v2.scorers.l1_process_integrity import L1ProcessIntegrityScorer
from eval_v2.scorers.l2_internal_quality import L2InternalQualityScorer
from eval_v2.scorers.l3_semantic import L3SemanticScorer
from eval_v2.scorers.l4_comparative import L4ComparativeScorer
from eval_v2.stats.confidence import wilson_interval
from eval_v2.stats.pass_at_k import compute_pass_at_k, compute_stable_pass_at_k, mark_stability

logger = logging.getLogger(__name__)


class SuiteRunner:
    """批量执行器。"""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.target = config.get("target", {})
        self.judge_config = config.get("judge", {})
        self.exec_config = config.get("execution", {})
        self.weights = config.get("weights", {})

        # 初始化客户端
        self.sut_client: SUTClient | None = None
        self.judge_client: JudgeClient | None = None
        self.cost_tracker = CostTracker(config.get("cost", {}))

        # 初始化评分器
        self.l0_scorer = L0SystemHealthScorer(config.get("l0_health", {}))
        self.l1_scorer = L1ProcessIntegrityScorer(config.get("l1_process", {}))
        self.l2_scorer = L2InternalQualityScorer(config.get("l2_internal", {}))
        self.l3_scorer: L3SemanticScorer | None = None
        self.l4_scorer = L4ComparativeScorer(config.get("l4_comparative", {}))

    async def __aenter__(self) -> SuiteRunner:
        # 创建 SUT 客户端
        self.sut_client = SUTClient(
            base_url=self.target.get("base_url", "http://localhost:8000"),
            auth_token=self.target.get("auth_token"),
            dev_token=self.target.get("dev_token"),
            admin_username=self.target.get("admin_username", "admin"),
            admin_password=self.target.get("admin_password", "admin"),
            timeout=self.exec_config.get("per_case_timeout", 600),
            poll_interval=self.exec_config.get("poll_interval", 3),
            max_poll_attempts=self.exec_config.get("max_poll_attempts", 200),
        )
        await self.sut_client.__aenter__()

        # 创建 Judge 客户端
        judge_api_key = self.judge_config.get("api_key", "")
        self.judge_client = JudgeClient(
            model=self.judge_config.get("model", "deepseek-v4-flash"),
            base_url=self.judge_config.get("base_url", "https://api.deepseek.com"),
            api_key=judge_api_key,
            api_key_env=self.judge_config.get("api_key_env", "DEEPSEEK_API_KEY"),
            temperature=self.judge_config.get("temperature", 0.0),
            seed=self.judge_config.get("seed", 42),
            timeout=self.judge_config.get("timeout", 60),
            max_retries=2,
            judge_runs=self.judge_config.get("judge_runs", 3),
        )

        # 初始化 L3 评分器
        self.l3_scorer = L3SemanticScorer(
            judge_client=self.judge_client,
            config={**self.config.get("l3_semantic", {}), "weight": self.weights.get("l3_semantic", 0.45)},
        )

        return self

    async def __aexit__(self, *args: Any) -> None:
        if self.sut_client:
            await self.sut_client.__aexit__(*args)

    async def run_suite(
        self,
        cases: list[EvalCase],
        pass_k: int = 3,
        mode: RunMode = RunMode.STANDARD,
    ) -> SuiteResult:
        """运行整批测试。"""
        start_time = time.monotonic()
        suite_id = datetime.now().strftime("%Y%m%d-%H%M%S")

        # 登录 SUT
        if self.sut_client:
            await self.sut_client.login()

        # 获取 prompt 版本快照（ADR-015 Phase 1）：将本批结果绑定到精确 prompt 版本
        prompt_snapshot: dict[str, Any] = {}
        if self.sut_client:
            prompt_snapshot = await self.sut_client.get_prompt_snapshot()
            if not prompt_snapshot:
                logger.warning("未获取到 prompt 快照（SUT 版本较旧或端点不可用），本批结果不做版本绑定")

        # 创建 CaseRunner
        case_runner = CaseRunner(
            sut_client=self.sut_client,
            config=self.config,
        )
        case_runner.set_scorers(l2=self.l2_scorer, l3=self.l3_scorer, l4=self.l4_scorer)

        # 并发控制
        max_concurrent = self.exec_config.get("max_concurrent", 2)
        semaphore = asyncio.Semaphore(max_concurrent)

        all_results: list[CaseRunResult] = []

        async def run_case_with_sem(case: EvalCase, run_idx: int) -> CaseRunResult:
            async with semaphore:
                logger.info(f"Running {case.case_id} (run {run_idx + 1}/{pass_k})...")
                try:
                    result = await case_runner.run_single(case, run_index=run_idx)
                    logger.info(
                        f"  {case.case_id} run {run_idx + 1}: "
                        f"score={result.aggregate_score:.1f}, passed={result.passed}, "
                        f"failure={result.failure_class.value if result.failure_class else 'none'}"
                    )
                    return result
                except Exception as e:
                    logger.error(f"  {case.case_id} run {run_idx + 1} ERROR: {e}")
                    return CaseRunResult(
                        case_id=case.case_id,
                        run_index=run_idx,
                        error=str(e),
                        failure_class=FailureClass.TEST_BUG,
                    )

        # 构建所有任务
        tasks = []
        for case in cases:
            for run_idx in range(pass_k):
                tasks.append(run_case_with_sem(case, run_idx))

        # 执行
        all_results = await asyncio.gather(*tasks)

        # 标记稳定性
        mark_stability(all_results)

        # 统计汇总
        suite_result = self._aggregate_results(all_results, cases, suite_id, pass_k, mode)
        suite_result.duration_seconds = time.monotonic() - start_time

        # 绑定 prompt 版本快照（ADR-015 Phase 1）
        suite_result.prompt_snapshot_id = prompt_snapshot.get("snapshot_id", "")
        suite_result.prompt_snapshot = prompt_snapshot.get("prompts", {})
        suite_result.git_commit = prompt_snapshot.get("git_commit", "")
        suite_result.git_dirty = bool(prompt_snapshot.get("git_dirty", False))

        # 检测长度偏置
        scores = [r.aggregate_score for r in all_results if r.audit and r.audit.meeting.artifact_length > 0]
        lengths = [
            r.audit.meeting.artifact_length for r in all_results if r.audit and r.audit.meeting.artifact_length > 0
        ]
        if len(scores) >= 5:
            r, has_bias = detect_length_bias(scores, lengths)
            suite_result.length_bias_pearson_r = r
            if has_bias:
                logger.warning(f"Length bias detected: Pearson r = {r:.3f}")

        # Judge 成本
        if self.judge_client:
            suite_result.judge_cost_usd = self.judge_client.total_cost_usd
            suite_result.total_cost_usd += self.judge_client.total_cost_usd

        # 模型信息
        suite_result.model_info = self._detect_model_info(all_results)

        return suite_result

    def _aggregate_results(
        self,
        results: list[CaseRunResult],
        cases: list[EvalCase],
        suite_id: str,
        pass_k: int,
        mode: RunMode,
    ) -> SuiteResult:
        """聚合统计结果。"""
        n_cases = len(cases)
        len(results)

        # Pass@k
        pass1 = compute_pass_at_k(results, k=1)
        pass3 = compute_pass_at_k(results, k=pass_k)
        pass3_stable = compute_stable_pass_at_k(results, k=pass_k)

        # Wilson CI for Pass@1
        pass1_count = sum(1 for r in results if r.run_index == 0 and r.passed)
        n_first_runs = sum(1 for r in results if r.run_index == 0)
        ci = wilson_interval(pass1_count, n_first_runs)

        # 各层通过率
        layer_pass_rates: dict[str, float] = {}
        for level in Level:
            layer_results = [r.layers.get(level.value) for r in results if level.value in r.layers]
            layer_passed = [lr for lr in layer_results if lr and lr.passed and not lr.skipped]
            layer_total = [lr for lr in layer_results if lr and not lr.skipped]
            if layer_total:
                layer_pass_rates[level.value] = len(layer_passed) / len(layer_total)
            else:
                layer_pass_rates[level.value] = 0.0

        # 维度平均分（L3）
        dim_scores: dict[str, list[float]] = defaultdict(list)
        for r in results:
            l3 = r.layers.get(Level.L3_SEMANTIC.value)
            if l3 and not l3.skipped:
                for ds in l3.dimension_scores:
                    dim_scores[ds.dimension].append(ds.score)
        dimension_avg = {dim: sum(s) / len(s) for dim, s in dim_scores.items()}

        # 故障模式分布
        failure_breakdown: dict[str, int] = {"none": 0}
        infra_failures = 0
        model_failures = 0
        test_bugs = 0
        for r in results:
            if r.failure_class == FailureClass.INFRASTRUCTURE:
                infra_failures += 1
                failure_breakdown["infrastructure"] = failure_breakdown.get("infrastructure", 0) + 1
            elif r.failure_class == FailureClass.MODEL:
                model_failures += 1
                failure_breakdown["model"] = failure_breakdown.get("model", 0) + 1
            elif r.failure_class == FailureClass.TEST_BUG:
                test_bugs += 1
                failure_breakdown["test_bug"] = failure_breakdown.get("test_bug", 0) + 1
            else:
                failure_breakdown["none"] += 1

        # 延迟统计
        latencies = sorted([r.latency_ms for r in results if r.latency_ms > 0])
        p50 = latencies[len(latencies) // 2] if latencies else 0
        p95_idx = int(len(latencies) * 0.95)
        p95 = latencies[min(p95_idx, len(latencies) - 1)] if latencies else 0
        avg_latency = sum(latencies) / len(latencies) if latencies else 0

        # 成本统计
        eff = compute_efficiency_metrics(results)
        total_cost = eff["total_cost_usd"]
        cost_per_pass = eff["cost_per_pass"]
        total_tokens = eff["total_tokens"]
        judge_cost_total = sum(r.cost.judge_cost_usd for r in results)

        # 平均分数
        first_run_results = [r for r in results if r.run_index == 0]
        avg_score = (
            sum(r.aggregate_score for r in first_run_results) / len(first_run_results) if first_run_results else 0
        )

        # Judge 不可靠数量
        unreliable_count = 0
        for r in results:
            l3 = r.layers.get(Level.L3_SEMANTIC.value)
            if l3 and l3.dimension_scores:
                for ds in l3.dimension_scores:
                    if ds.likert_std > self.judge_config.get("unreliable_std_threshold", 0.8):
                        unreliable_count += 1

        return SuiteResult(
            suite_id=suite_id,
            timestamp=datetime.now().isoformat(),
            mode=mode.value,
            pass_at_1=pass1,
            pass_at_1_ci=ci,
            pass_at_3=pass3,
            pass_at_3_stable=pass3_stable,
            avg_aggregate_score=avg_score,
            layer_pass_rates=layer_pass_rates,
            dimension_scores=dimension_avg,
            failure_mode_breakdown=failure_breakdown,
            total_cost_usd=total_cost,
            cost_per_pass=cost_per_pass,
            total_tokens=total_tokens,
            judge_cost_usd=judge_cost_total,
            latency_p50_ms=p50,
            latency_p95_ms=p95,
            latency_avg_ms=avg_latency,
            n_cases=n_cases,
            n_runs_per_case=pass_k,
            n_infrastructure_failures=infra_failures,
            n_model_failures=model_failures,
            n_test_bugs=test_bugs,
            per_case_results=results,
            judge_unreliable_count=unreliable_count,
            config_snapshot=self.config,
        )

    def _detect_model_info(self, results: list[CaseRunResult]) -> ModelInfo:
        """从结果中检测被测模型信息。"""
        info = ModelInfo(
            judge_model=self.judge_config.get("model", ""),
            judge_provider=self.judge_config.get("llm_vendor", ""),
        )
        # 从 audit trace 中检测模型
        for r in results:
            if r.audit and r.audit.trace.calls:
                models = set()
                providers = set()
                for call in r.audit.trace.calls:
                    if call.model:
                        models.add(call.model)
                    if call.provider:
                        providers.add(call.provider)
                if models:
                    info.model = next(iter(models))
                if providers:
                    info.provider = next(iter(providers))
                break

        # 同族检测
        if info.model and info.judge_model:
            from eval_v2.llm_judge.bias_mitigation import is_same_family

            info.is_same_family = is_same_family(info.model, info.judge_model)

        return info
