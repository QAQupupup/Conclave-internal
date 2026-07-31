"""LLM Judge client - OpenAI-compatible API caller.

Features:
- Multi-vendor support (OpenAI-compatible)
- 3 concurrent calls with median aggregation
- Timeout/retry
- JSON response parsing with error handling
- Token counting
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from eval_v2.models.enums import ConfidenceLevel
from eval_v2.models.judgment import CoTJudgment, PairwiseJudgment

logger = logging.getLogger(__name__)


class JudgeClient:
    """LLM Judge 客户端，使用 OpenAI 兼容 API。"""

    def __init__(
        self,
        model: str = "deepseek-ai/DeepSeek-V4-Flash",
        base_url: str = "https://api.siliconflow.cn/v1",
        api_key: str = "",
        api_key_env: str = "SILICONFLOW_API_KEY",
        temperature: float = 0.0,
        seed: int = 42,
        timeout: float = 60.0,
        max_retries: int = 2,
        judge_runs: int = 3,
    ):
        import os

        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get(api_key_env, "")
        self.temperature = temperature
        self.seed = seed
        self.timeout = timeout
        self.max_retries = max_retries
        self.judge_runs = judge_runs
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cost_usd = 0.0
        self._available = bool(self.api_key)

    @property
    def available(self) -> bool:
        """Judge API 是否可用（有 API key）。"""
        return self._available

    @property
    def total_input_tokens(self) -> int:
        return self._total_input_tokens

    @property
    def total_output_tokens(self) -> int:
        return self._total_output_tokens

    @property
    def total_cost_usd(self) -> float:
        return self._total_cost_usd

    def reset_stats(self) -> None:
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cost_usd = 0.0

    async def judge_cot(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> list[CoTJudgment]:
        """执行 CoT 评分，返回 judge_runs 次的评分结果。"""
        if not self._available:
            return []

        tasks = [self._call_judge_once(system_prompt, user_prompt) for _ in range(self.judge_runs)]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        judgments = []
        for raw in raw_results:
            if isinstance(raw, Exception):
                logger.warning(f"Judge call failed: {raw}")
                continue
            if raw is None:
                continue
            parsed = self._parse_cot_response(raw["content"], raw.get("input_tokens", 0), raw.get("output_tokens", 0))
            if parsed is not None:
                judgments.append(parsed)

        return judgments

    async def judge_pairwise(
        self,
        system_prompt: str,
        user_prompt: str,
        a_was_first: bool = True,
    ) -> PairwiseJudgment | None:
        """执行 Pairwise 比较，返回单次判断（Pairwise 取单次，不做3次因为已经做了位置随机化）。"""
        if not self._available:
            return None

        raw = await self._call_judge_once(system_prompt, user_prompt)
        if raw is None:
            return None

        return self._parse_pairwise_response(
            raw["content"], a_was_first, raw.get("input_tokens", 0), raw.get("output_tokens", 0)
        )

    async def _call_judge_once(self, system_prompt: str, user_prompt: str) -> dict[str, Any] | None:
        """单次 Judge API 调用。"""
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self.model,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            "temperature": self.temperature,
                            "seed": self.seed,
                            "response_format": {"type": "json_object"},
                        },
                    )
                    if resp.status_code != 200:
                        logger.warning(f"Judge API returned {resp.status_code}: {resp.text[:200]}")
                        if resp.status_code == 401 or resp.status_code == 402:
                            self._available = False
                            return None
                        if attempt < self.max_retries:
                            await asyncio.sleep(2**attempt)
                            continue
                        return None

                    data = resp.json()
                    choice = data.get("choices", [{}])[0]
                    content = choice.get("message", {}).get("content", "")
                    usage = data.get("usage", {})
                    in_tokens = usage.get("prompt_tokens", 0)
                    out_tokens = usage.get("completion_tokens", 0)

                    self._total_input_tokens += in_tokens
                    self._total_output_tokens += out_tokens

                    return {
                        "content": content,
                        "input_tokens": in_tokens,
                        "output_tokens": out_tokens,
                    }

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                logger.warning(f"Judge call attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(2**attempt)
                else:
                    return None
            except Exception as e:
                logger.warning(f"Judge call unexpected error: {e}")
                return None

        return None

    def _parse_cot_response(self, content: str, in_tokens: int, out_tokens: int) -> CoTJudgment | None:
        """解析 CoT 评分 JSON 响应。"""
        try:
            # 尝试提取 JSON 块
            json_str = self._extract_json(content)
            if not json_str:
                logger.warning(f"Could not extract JSON from judge response: {content[:200]}")
                return None

            data = json.loads(json_str)
            likert = int(data.get("likert_score", 0))
            if likert < 1 or likert > 5:
                likert = max(1, min(5, likert))

            binary_pass = bool(data.get("binary_pass", likert >= 3))
            conf_str = data.get("confidence", "medium")
            try:
                confidence = ConfidenceLevel(conf_str)
            except ValueError:
                confidence = ConfidenceLevel.MEDIUM

            # 估算成本（粗略）
            cost = (in_tokens / 1_000_000) * 0.07 + (out_tokens / 1_000_000) * 0.28
            self._total_cost_usd += cost

            return CoTJudgment(
                binary_pass=binary_pass,
                likert_score=likert,
                confidence=confidence,
                reasoning=data.get("reasoning", ""),
                raw_response=content,
            )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"Failed to parse judge response: {e}, content: {content[:200]}")
            return None

    def _parse_pairwise_response(
        self, content: str, a_was_first: bool, in_tokens: int, out_tokens: int
    ) -> PairwiseJudgment | None:
        """解析 Pairwise 比较 JSON 响应。"""
        try:
            json_str = self._extract_json(content)
            if not json_str:
                return None

            data = json.loads(json_str)
            winner = data.get("winner", "tie")
            if winner not in ("A", "B", "tie"):
                winner = "tie"

            conf_str = data.get("confidence", "medium")
            try:
                confidence = ConfidenceLevel(conf_str)
            except ValueError:
                confidence = ConfidenceLevel.MEDIUM

            cost = (in_tokens / 1_000_000) * 0.07 + (out_tokens / 1_000_000) * 0.28
            self._total_cost_usd += cost

            return PairwiseJudgment(
                winner=winner,
                reasoning=data.get("reasoning", ""),
                confidence=confidence,
                a_was_first=a_was_first,
                raw_response=content,
            )
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse pairwise response: {e}")
            return None

    @staticmethod
    def _extract_json(text: str) -> str | None:
        """从文本中提取 JSON 对象。"""
        # 尝试直接解析
        text = text.strip()
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass

        # 尝试从 ```json ... ``` 块提取
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            candidate = match.group(1).strip()
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass

        # 尝试找第一个 { 到最后一个 }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass

        return None
