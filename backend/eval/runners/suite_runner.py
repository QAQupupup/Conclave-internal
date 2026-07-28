# 批量执行器：并发运行多个用例，支持 pass@k，汇总统计
from __future__ import annotations

import asyncio
import os

import httpx

from eval.models import CaseResult, SuiteResult
from eval.runners.case_runner import CaseRunner
from eval.stats.confidence import wilson_ci
from eval.stats.metrics import (
    calculate_avg_score,
    calculate_pass_at_k,
    calculate_percentile,
    calculate_stage_pass_rate,
)


class SuiteRunner:
    """批量用例执行器。

    根据 config 并发运行用例，每个用例可重复 pass_k 次，最终汇总为 SuiteResult。
    """

    def __init__(self, config: dict) -> None:
        self.config = config
        service = config.get("service", {}) or {}
        execution = config.get("execution", {}) or {}
        self.base_url = service.get("base_url", "http://localhost:8000")
        self.admin_username = service.get("admin_username", "")
        self.admin_password = service.get("admin_password", "")
        self.auth_token: str | None = service.get("auth_token")
        self.max_concurrent = int(execution.get("max_concurrent", 3))
        self.default_pass_k = int(execution.get("pass_k", 1))

    async def run_suite(self, cases: list[dict], pass_k: int = 1) -> SuiteResult:
        k = pass_k or self.default_pass_k

        # 1. 获取 auth token（若未显式提供则尝试登录）
        token = self.auth_token
        if not token and self.admin_username:
            token = await self._login()

        # 2. 构造 CaseRunner 并按需注入 LLM judge
        runner = CaseRunner(self.base_url, token)
        self._configure_judge(runner)

        # 3. 并发执行（Semaphore 控制并发度），每个用例跑 k 次
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def _run_one(case: dict, run_index: int) -> CaseResult:
            async with semaphore:
                case_copy = dict(case)
                case_copy["run_index"] = run_index
                return await runner.run_case(case_copy)

        tasks: list[asyncio.Future[CaseResult]] = []
        for case in cases:
            for i in range(k):
                tasks.append(asyncio.ensure_future(_run_one(case, i)))
        results = await asyncio.gather(*tasks)

        return self._build_suite_result(results, cases, k)

    # ---------- 内部方法 ----------

    async def _login(self) -> str | None:
        """通过 /auth/login 获取 JWT token。"""
        try:
            async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
                resp = await client.post(
                    f"{self.base_url}/auth/login",
                    json={"username": self.admin_username, "password": self.admin_password},
                )
                resp.raise_for_status()
                return resp.json().get("access_token")
        except Exception:
            return None

    def _configure_judge(self, runner: CaseRunner) -> None:
        """根据 config.judge 配置注入 LLMJudgeGrader（需对应环境变量已配置）。"""
        judge_cfg = self.config.get("judge", {}) or {}
        api_key_env = judge_cfg.get("api_key_env", "")
        api_key = os.environ.get(api_key_env, "") if api_key_env else ""
        if not api_key:
            return
        model = judge_cfg.get("model", "")
        base_url = judge_cfg.get("base_url", self.base_url)
        judge_runs = int(judge_cfg.get("judge_runs", 3))
        unreliable_threshold = float(judge_cfg.get("unreliable_threshold", 0.2))
        if not model or not base_url:
            return
        from eval.graders.llm_judge import LLMJudgeGrader

        runner.set_judge(
            LLMJudgeGrader(
                model=model,
                base_url=base_url,
                api_key=api_key,
                judge_runs=judge_runs,
                unreliable_threshold=unreliable_threshold,
            )
        )

    def _build_suite_result(self, results: list[CaseResult], cases: list[dict], k: int) -> SuiteResult:
        total_cases = len(cases)

        # Pass@1：仅取每个用例的第 0 次运行
        pass1_flags = [r.passed for r in results if r.run_index == 0]
        pass1 = calculate_pass_at_k(pass1_flags, 1) if pass1_flags else 0.0
        pass1_ci = wilson_ci(pass1, len(pass1_flags))

        # Pass@3：若运行次数足够则按 3 分组，否则退化为 pass1
        all_flags = [r.passed for r in results]
        pass3 = calculate_pass_at_k(all_flags, 3) if k >= 3 else pass1

        avg_score = calculate_avg_score(results)

        # 阶段通过率明细
        stages: set[str] = set()
        for r in results:
            stages.update(r.stage_scores.keys())
        stage_breakdown = {s: calculate_stage_pass_rate(results, s) for s in sorted(stages)}

        total_tokens = sum(r.total_tokens for r in results)
        latencies = [r.latency_ms for r in results]
        p50 = calculate_percentile(latencies, 50)
        p95 = calculate_percentile(latencies, 95)

        # 不稳定用例：k>=2 时，同一用例多次运行结果不一致
        unstable_cases = self._find_unstable(results, k)

        return SuiteResult(
            total_cases=total_cases,
            pass1=pass1,
            pass1_ci=pass1_ci,
            pass3=pass3,
            avg_score=avg_score,
            stage_breakdown=stage_breakdown,
            per_case_results=results,
            total_tokens=total_tokens,
            total_cost_usd=0.0,
            p50_latency_ms=p50,
            p95_latency_ms=p95,
            unstable_cases=unstable_cases,
            unreliable_judgments=[],
        )

    @staticmethod
    def _find_unstable(results: list[CaseResult], k: int) -> list[str]:
        if k < 2:
            return []
        by_case: dict[str, list[bool]] = {}
        for r in results:
            by_case.setdefault(r.case_id, []).append(r.passed)
        return [cid for cid, flags in by_case.items() if len(set(flags)) > 1]
