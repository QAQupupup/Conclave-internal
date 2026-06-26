# LLM 调用封装：真实 LLM（httpx 调 openai 兼容接口）+ StubLLM（无 key 时返回符合 schema 的假数据）
from __future__ import annotations

import json
import uuid
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ValidationError

from app.agents.schemas import SCHEMA_MAP
from app.agents.trace import record_call, update_last_record
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

    三明治模式（结构化输出加固）：
    1. 请求层：system message 注入对应 Pydantic 模型的 JSON Schema；
       传 response_format={"type":"json_object"}（接口不支持时自动降级）。
    2. 解析层：用 schemas.py 对应模型 model_validate 校验。
    3. 重试层：解析失败把 ValidationError 信息追加到 prompt 再调，最多 3 次；
       3 次都失败则降级用 StubLLM 同阶段数据，保证流程不中断。
    """

    # 最大重试次数（含首次）
    MAX_ATTEMPTS = 3

    def __init__(self) -> None:
        self.api_key = settings.llm_api_key
        self.base_url = settings.llm_base_url or "https://api.openai.com/v1"
        self.model = settings.llm_model
        self._client = httpx.AsyncClient(timeout=60.0)
        # 接口是否支持 json_object 响应格式；遇到 400 时自动置 False 并回退
        self._supports_json_mode: bool = True

    async def complete(self, prompt: str, schema_hint: str = "") -> dict[str, Any]:
        """三明治模式：请求层 schema 注入 -> 解析层 Pydantic 校验 -> 重试层 -> 降级"""
        model_cls = SCHEMA_MAP.get(schema_hint)
        schema_desc = self._schema_description(model_cls)
        # schema_hint 即阶段名，用于 trace 记录
        stage = schema_hint

        current_prompt = prompt
        last_error = ""
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                content = await self._call_api(current_prompt, schema_desc, stage, attempt)
                parsed = self._extract_json(content)
                if model_cls is not None:
                    validated: BaseModel = model_cls.model_validate(parsed)
                    result = validated.model_dump()
                else:
                    # schema_hint 未注册时，仅做 JSON 解析兜底返回 dict
                    result = parsed if isinstance(parsed, dict) else {"result": parsed}
                # 解析成功：更新最后一条 trace 记录的解析结果和验证状态
                update_last_record(
                    parsed_result=result if isinstance(result, dict) else None,
                    validation_status="valid",
                )
                return result
            except (ValidationError, json.JSONDecodeError, KeyError, httpx.HTTPError) as e:
                last_error = f"{type(e).__name__}: {e}"
                # 更新 trace 记录：本次调用校验失败
                update_last_record(validation_status="invalid")
                # 重试层：把校验错误追加进 prompt，引导 LLM 修正
                current_prompt = (
                    f"{prompt}\n\n"
                    f"【上一次输出校验失败（第 {attempt} 次），错误：{last_error}】\n"
                    f"请严格按给定 JSON Schema 重新输出，仅输出合法 JSON，不要包含注释或围栏。"
                )

        # 3 次都失败：降级到 StubLLM 同阶段数据，保证流程不中断（不报错）
        # 记录降级到 trace
        record_call(
            stage=stage,
            model=self.model,
            temperature=0,
            seed=42,
            prompt=prompt,
            raw_response="",
            parsed_result=None,
            validation_status="fallback_stub",
            attempt=self.MAX_ATTEMPTS,
            latency_ms=0,
        )
        stub = StubLLM()
        return await stub.complete(prompt, schema_hint=schema_hint)

    # ---------- 请求层 ----------

    @staticmethod
    def _schema_description(model_cls: type[BaseModel] | None) -> str:
        """把 Pydantic 模型转成 JSON Schema 文本，注入 system message"""
        if model_cls is None:
            return ""
        schema = model_cls.model_json_schema()
        return json.dumps(schema, ensure_ascii=False, indent=2)

    async def _call_api(self, user_prompt: str, schema_desc: str, stage: str = "", attempt: int = 1) -> str:
        """调用 chat completions，返回 message content 字符串

        第1层确定性约束：
        - temperature 强制为 0（不可配）
        - top_p 固定 1.0
        - seed 固定 42（API 支持则同一输入必同一输出）
        - system message 末尾加 /no_think（关闭 Qwen3.5 思考模式）
        """
        import time

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        system_content = "你是会议决策助手，严格输出 JSON，不要输出多余文本。"
        if schema_desc:
            system_content += (
                "\n输出必须严格符合以下 JSON Schema（多余字段会被忽略，缺字段尽量补全默认值）：\n"
                f"{schema_desc}"
            )
        # 关闭 Qwen3.5 思考模式，防止思考过程干扰 JSON 输出
        system_content += "\n/no_think"
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_prompt},
            ],
            # 第1层：参数确定性 —— temperature=0, top_p=1.0, seed=42
            "temperature": 0,
            "top_p": 1.0,
            "seed": 42,
        }
        # 请求层：优先传 json_object 响应格式
        if self._supports_json_mode:
            body["response_format"] = {"type": "json_object"}

        latency_ms = 0
        try:
            t0 = time.monotonic()
            resp = await self._client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            latency_ms = int((time.monotonic() - t0) * 1000)
        except httpx.HTTPStatusError as e:
            # 接口可能不支持 response_format（返回 400），自动降级去掉该参数重试一次
            if (
                self._supports_json_mode
                and e.response.status_code == 400
                and self._looks_like_json_mode_error(e)
            ):
                self._supports_json_mode = False
                body.pop("response_format", None)
                t0 = time.monotonic()
                resp = await self._client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                latency_ms = int((time.monotonic() - t0) * 1000)
            else:
                # 记录失败的调用到 trace
                record_call(
                    stage=stage,
                    model=self.model,
                    temperature=0,
                    seed=42,
                    prompt=user_prompt,
                    raw_response=str(e),
                    validation_status="invalid",
                    attempt=attempt,
                    latency_ms=latency_ms,
                )
                raise

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        # 第1层：记录完整调用信息到 trace
        record_call(
            stage=stage,
            model=self.model,
            temperature=0,
            seed=42,
            prompt=user_prompt,
            raw_response=content,
            parsed_result=None,  # 解析后由 complete() 更新
            validation_status="valid",  # 默认，complete() 会根据解析结果更新
            attempt=attempt,
            latency_ms=latency_ms,
        )
        return content

    @staticmethod
    def _looks_like_json_mode_error(e: httpx.HTTPStatusError) -> bool:
        """粗判 400 是否由 response_format 引起"""
        try:
            text = e.response.text.lower()
        except Exception:
            return False
        return any(kw in text for kw in ("response_format", "json_object", "json_schema", "not support"))

    @staticmethod
    def _extract_json(content: str) -> Any:
        """容错提取 JSON：去掉 ```json 围栏与多余文本"""
        content = (content or "").strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(content)


def get_llm() -> LLMClient:
    """按配置返回 LLM 客户端：有 key 用真实，否则用 stub"""
    if settings.use_real_llm:
        return RealLLM()
    return StubLLM()
