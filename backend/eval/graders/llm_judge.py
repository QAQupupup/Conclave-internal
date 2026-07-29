# Type C: LLM-as-Judge 评分器（OpenAI 兼容 API）
from __future__ import annotations

import asyncio
import re
import statistics

import httpx

from eval.graders.base import GraderResult

# 评分 prompt 模板：要求 LLM 仅输出 0-1 之间的数字
JUDGE_PROMPT_TEMPLATE = """You are an impartial judge evaluating the quality of a meeting deliverable produced by a multi-agent system.

Topic: {topic}
Evaluation dimension: {dimension}

Expected (reference):
{expected}

Actual (produced):
{actual}

Evaluate the actual output against the expected reference on the dimension "{dimension}".
Respond with ONLY a single decimal number between 0.0 and 1.0, where 1.0 means perfect and 0.0 means worst.
Do not include any explanation, only the number."""


class LLMJudgeGrader:
    """LLM-as-Judge 评分器。

    使用 OpenAI 兼容的 /v1/chat/completions 接口对产出进行评分。
    跑 judge_runs 次，取中位数作为最终得分；标准差超过 unreliable_threshold 标记不可信。
    若未配置 API key，返回 score=0.5, passed=False, detail="LLM judge not configured"。
    """

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str,
        judge_runs: int = 3,
        unreliable_threshold: float = 0.2,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.judge_runs = max(1, judge_runs)
        self.unreliable_threshold = unreliable_threshold

    async def grade(
        self,
        topic: str,
        expected: str,
        actual: str,
        dimension: str,
    ) -> GraderResult:
        if not self.api_key:
            return GraderResult(
                score=0.5,
                passed=False,
                detail="LLM judge not configured",
            )

        prompt = JUDGE_PROMPT_TEMPLATE.format(
            topic=topic,
            dimension=dimension,
            expected=expected,
            actual=actual,
        )

        tasks = [self._call_llm(prompt) for _ in range(self.judge_runs)]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        scores: list[float] = []
        errors: list[str] = []
        for r in raw_results:
            if isinstance(r, Exception):
                errors.append(f"{type(r).__name__}: {r}")
            elif isinstance(r, float):
                scores.append(r)

        if not scores:
            return GraderResult(
                score=0.0,
                passed=False,
                detail="all judge calls failed: " + "; ".join(errors[:3]),
                unreliable=True,
            )

        median = statistics.median(scores)
        stdev = statistics.pstdev(scores) if len(scores) > 1 else 0.0
        unreliable = stdev > self.unreliable_threshold
        passed = median >= 0.6
        detail = f"median={median:.3f}, stdev={stdev:.3f}, n={len(scores)}"
        if errors:
            detail += f", errors={len(errors)}"
        return GraderResult(score=median, passed=passed, detail=detail, unreliable=unreliable)

    async def _call_llm(self, prompt: str) -> float:
        """调用 OpenAI 兼容 API，返回解析后的 0-1 分数。

        URL 格式与后端 llm.py 一致：{base_url}/chat/completions
        base_url 需包含完整 API 路径前缀（如 .../api/v3 或 .../v1）。
        """
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            return self._parse_score(content)

    @staticmethod
    def _parse_score(content: str) -> float:
        """从 LLM 输出中解析 0-1 分数。"""
        match = re.search(r"\d+(?:\.\d+)?", content)
        if not match:
            return 0.0
        score = float(match.group(0))
        # 处理可能输出 0-100 的情况
        if score > 1.0:
            score = score / 100.0
        return max(0.0, min(1.0, score))
