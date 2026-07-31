"""Direct LLM baseline for ablation study.

Bypasses the Conclave multi-agent pipeline and generates output directly
using the same LLM model with a single prompt.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class DirectLLMBaseline:
    """单 Agent 直接生成基线。

    绕过 Conclave 多 Agent 管线，直接调用同一 LLM 单轮生成产出。
    """

    def __init__(
        self,
        model: str = "",
        base_url: str = "",
        api_key: str = "",
        api_key_env: str = "",
        temperature: float = 0.1,
        max_tokens: int = 8192,
        timeout: float = 120.0,
    ):
        import os as _os

        self.model = model
        self.base_url = base_url.rstrip("/") if base_url else ""
        if api_key_env and not api_key:
            api_key = _os.environ.get(api_key_env, "")
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0

    @property
    def available(self) -> bool:
        return bool(self.model and self.base_url and self.api_key)

    def configure_from_sut(
        self,
        llm_model: str,
        llm_base_url: str,
        llm_api_key: str = "",
        llm_api_key_env: str = "OPENAI_API_KEY",
    ) -> None:
        """从 SUT 配置中获取 LLM 参数。"""
        self.model = llm_model
        self.base_url = llm_base_url.rstrip("/") if llm_base_url else ""
        if llm_api_key:
            self.api_key = llm_api_key
        elif llm_api_key_env:
            self.api_key = os.environ.get(llm_api_key_env, "")

    async def generate(
        self,
        topic: str,
        deliverable_type: str = "prd_openapi",
    ) -> dict[str, Any]:
        """直接生成产出。

        Returns:
            {"text": str, "input_tokens": int, "output_tokens": int, "cost_usd": float, "success": bool}
        """
        if not self.available:
            return {"text": "", "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "success": False}

        prompt = self._build_prompt(topic, deliverable_type)

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
                            {
                                "role": "system",
                                "content": "你是一位资深的技术专家，能够生成高质量的技术文档。请直接输出完整内容，不要解释过程。",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": self.temperature,
                        "max_tokens": self.max_tokens,
                    },
                )
                if resp.status_code != 200:
                    logger.warning(f"Direct LLM call failed: {resp.status_code}: {resp.text[:200]}")
                    return {"text": "", "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "success": False}

                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                in_tokens = usage.get("prompt_tokens", 0)
                out_tokens = usage.get("completion_tokens", 0)

                # 粗略成本估算
                cost = (in_tokens / 1_000_000) * 0.14 + (out_tokens / 1_000_000) * 0.28

                self.total_input_tokens += in_tokens
                self.total_output_tokens += out_tokens
                self.total_cost_usd += cost

                return {
                    "text": content,
                    "input_tokens": in_tokens,
                    "output_tokens": out_tokens,
                    "cost_usd": cost,
                    "success": True,
                }
        except Exception as e:
            logger.warning(f"Direct LLM call error: {e}")
            return {"text": "", "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "success": False}

    def _build_prompt(self, topic: str, deliverable_type: str) -> str:
        """根据产出类型构建 prompt。"""
        type_prompts = {
            "prd_openapi": "请根据以下需求，生成一份完整的产品需求文档（PRD）和 OpenAPI 3.0 规范。PRD 应包含：产品概述、目标用户、功能需求、非功能需求、API 端点设计。OpenAPI 规范应包含完整的 paths、components、schemas、request/response 定义。",
            "design_doc": "请根据以下需求，生成一份完整的技术设计文档。包含：架构概述、技术选型、模块设计、数据模型、接口设计、部署方案、风险评估。",
            "research_report": "请根据以下主题，生成一份完整的调研报告。包含：背景、技术方案对比、优劣势分析、推荐方案、实施建议。",
            "business_report": "请根据以下主题，生成一份完整的商业分析报告。包含：市场分析、竞品分析、商业模式、财务预测、风险分析、建议。",
        }
        instruction = type_prompts.get(deliverable_type, "请根据以下需求，生成一份完整的专业文档。")
        return f"{instruction}\n\n需求：{topic}\n\n请直接输出完整文档内容："

    def format_as_artifact(self, text: str, deliverable_type: str) -> dict[str, Any]:
        """将直接生成的文本格式化为与 SUT artifact 兼容的结构。"""
        # 简单封装为 artifact 结构
        if deliverable_type == "prd_openapi":
            return {
                "prd": {"raw_text": text},
                "openapi": text,
            }
        return {"raw_text": text}
