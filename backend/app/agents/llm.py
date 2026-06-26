# LLM 调用封装：真实 LLM（httpx 调 openai 兼容接口）+ StubLLM（无 key 时返回符合 schema 的假数据）
from __future__ import annotations

import json
import uuid
from typing import Any, Protocol

import httpx

from app.config import settings


class LLMClient(Protocol):
    """LLM 客户端协议：输入 prompt，返回解析后的 dict"""
    async def complete(self, prompt: str, schema_hint: str = "") -> dict[str, Any]: ...


class StubLLM:
    """桩 LLM：无 API key 时返回符合各阶段 JSON schema 的假数据

    根据 prompt 中出现的阶段关键字返回对应结构的假数据，
    保证端到端流程在无 LLM 时也能跑通。
    """

    async def complete(self, prompt: str, schema_hint: str = "") -> dict[str, Any]:
        # 根据内容判定阶段，返回对应 schema 的假数据
        if "Clarify" in prompt or schema_hint == "clarify":
            return {
                "clarified_topic": f"澄清后的议题：{self._extract_topic(prompt)}",
                "key_questions": [
                    "目标用户的核心场景是什么？",
                    "系统的关键约束有哪些？",
                    "如何度量成功？",
                ],
                "team_config": [
                    {"role": "product_architect", "stance": "重价值与边界"},
                    {"role": "engineer", "stance": "重可行性与风险"},
                ],
            }
        if "IntraTeam" in prompt or schema_hint == "intra_team":
            # 根据角色区分偏置
            if "工程师" in prompt or "Engineer" in prompt:
                return {
                    "claims": [
                        {
                            "claim": "基于现有技术栈可实现，但需引入异步任务队列",
                            "evidence_ref": "[doc:架构]",
                            "risk_level": "medium",
                            "type": "constraint",
                        },
                        {
                            "claim": "高并发写场景下存在性能瓶颈，需做分库分表",
                            "evidence_ref": "[assumption]",
                            "risk_level": "high",
                            "type": "assumption",
                        },
                        {
                            "claim": "测试需覆盖边界：空输入、超长文本、并发上传",
                            "evidence_ref": "[assumption]",
                            "risk_level": "low",
                            "type": "constraint",
                        },
                    ]
                }
            # 默认产品架构师
            return {
                "claims": [
                    {
                        "claim": "目标用户为中小团队，核心价值在于降低决策成本",
                        "evidence_ref": "[doc:用户调研]",
                        "type": "fact",
                    },
                    {
                        "claim": "系统边界限定在会议场景内，不覆盖执行阶段",
                        "evidence_ref": "[doc:范围]",
                        "type": "constraint",
                    },
                    {
                        "claim": "接口需保持幂等以支持重试",
                        "evidence_ref": "[assumption]",
                        "type": "constraint",
                    },
                ]
            }
        if "CrossTeam" in prompt or schema_hint == "cross_team":
            return {
                "conflicts": [
                    {
                        "id": "c1",
                        "type": "preference",
                        "summary": "是否引入异步任务队列：架构师认为必要，工程师认为过度设计",
                        "side_a": "架构师：引入队列保障一致性",
                        "side_b": "工程师：增加复杂度，短期不必要",
                    },
                    {
                        "id": "c2",
                        "type": "scope",
                        "summary": "是否覆盖执行阶段：架构师认为应扩展，工程师认为应聚焦会议",
                        "side_a": "架构师：扩展到执行",
                        "side_b": "工程师：聚焦会议闭环",
                    },
                ]
            }
        if "EvidenceCheck" in prompt or schema_hint == "evidence_check":
            return {
                "conflict_id": self._extract_conflict_id(prompt),
                "evidence_assessments": [
                    {
                        "evidence_id": "ev-0",
                        "quote": "系统应支持异步任务处理以解耦耗时操作",
                        "source": "doc:架构",
                        "supports": "a",
                    },
                    {
                        "evidence_id": "ev-1",
                        "quote": "短期 MVP 不应引入额外中间件",
                        "source": "doc:范围",
                        "supports": "b",
                    },
                ],
            }
        if "Arbitrate" in prompt or schema_hint == "arbitrate":
            return {
                "decisions": [
                    {
                        "conflict_id": "c1",
                        "verdict": "compromise",
                        "rationale": "采用轻量级本地异步实现，不引入外部队列",
                    },
                    {
                        "conflict_id": "c2",
                        "verdict": "b",
                        "rationale": "聚焦会议闭环，执行阶段留待后续迭代",
                    },
                ],
                "adopted_claims": [
                    "目标用户为中小团队",
                    "接口需保持幂等",
                ],
            }
        if "Produce" in prompt or schema_hint == "produce":
            return {
                "prd": {
                    "title": "Conclave 会议决策系统",
                    "goal": "通过多智能体会议结构化产出 PRD 与 OpenAPI，降低团队决策成本",
                    "scope": "覆盖会议创建、议题澄清、队内讨论、跨队辩论、证据对照、仲裁裁决、产物生成全链路",
                    "assumptions": [
                        "用户具备基础 Markdown 与 API 知识",
                        "LLM 服务可用或走 stub 模式",
                    ],
                    "constraints": [
                        "单会议串行执行六阶段",
                        "无外部向量库依赖",
                        "WebSocket 实时推送",
                    ],
                    "api_endpoints": [
                        "POST /meetings",
                        "GET /meetings/{id}",
                        "POST /meetings/{id}/run",
                        "POST /meetings/{id}/control",
                        "POST /meetings/{id}/documents",
                        "WS /ws/meetings/{id}",
                    ],
                    "open_questions": [
                        "是否需要多会议并发隔离？",
                        "借调专家的裁决策略如何？",
                    ],
                },
                "openapi": (
                    "openapi: 3.0.3\n"
                    "info:\n"
                    "  title: Conclave\n"
                    "  version: 0.1.0\n"
                    "paths:\n"
                    "  /meetings:\n"
                    "    post:\n"
                    "      summary: 创建会议\n"
                    "      responses:\n"
                    "        '200':\n"
                    "          description: 创建成功\n"
                ),
            }
        # 兜底
        return {"result": "stub"}

    @staticmethod
    def _extract_topic(prompt: str) -> str:
        """从 prompt 中提取议题文本"""
        for line in prompt.splitlines():
            if "输入议题" in line and "：" in line:
                return line.split("：", 1)[1].strip()
        return "示例议题"

    @staticmethod
    def _extract_conflict_id(prompt: str) -> str:
        """从 prompt 中提取冲突 id"""
        import re

        m = re.search(r'"id":\s*"(c\d+)"', prompt)
        return m.group(1) if m else "c1"


class RealLLM:
    """真实 LLM 客户端：调 openai 兼容接口（httpx）

    读取 env: CONCLAVE_LLM_API_KEY / CONCLAVE_LLM_BASE_URL / CONCLAVE_LLM_MODEL
    """

    def __init__(self) -> None:
        self.api_key = settings.llm_api_key
        self.base_url = settings.llm_base_url or "https://api.openai.com/v1"
        self.model = settings.llm_model
        self._client = httpx.AsyncClient(timeout=60.0)

    async def complete(self, prompt: str, schema_hint: str = "") -> dict[str, Any]:
        """调用 chat completions，解析 JSON 返回"""
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是会议决策助手，严格输出 JSON，不要输出多余文本。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        }
        resp = await self._client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        # 尝试提取 JSON（容错：去掉可能的 ```json 围栏）
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(content)


def get_llm() -> LLMClient:
    """按配置返回 LLM 客户端：有 key 用真实，否则用 stub"""
    if settings.use_real_llm:
        return RealLLM()
    return StubLLM()
