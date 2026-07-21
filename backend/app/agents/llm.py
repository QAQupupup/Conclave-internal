# LLM 调用封装：真实 LLM（httpx 调 openai 兼容接口）+ StubLLM（无 key 时返回符合 schema 的假数据）
from __future__ import annotations

import contextlib
import json
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ValidationError

from app.agents.schemas import SCHEMA_MAP
from app.agents.trace import record_call, update_last_record
from app.config import settings
from app.logging_config import get_logger

logger = get_logger("agents.llm")


def _get_stage_temperatures() -> dict[str, float]:
    """从 settings.llm_stage_temperatures 解析阶段温度映射，解析失败回退到默认值"""
    import json

    try:
        result = json.loads(settings.llm_stage_temperatures)
        if isinstance(result, dict):
            return {k: float(v) for k, v in result.items()}
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning("解析 CONCLAVE_LLM_STAGE_TEMPERATURES 失败，使用默认值: %s", e)
    # 默认值（与原 STAGE_TEMPERATURES 常量一致）
    return {
        "clarify": 0.0,
        "intra_team": 0.3,
        "cross_team": 0.0,
        "evidence_check": 0.0,
        "arbitrate": 0.0,
        "produce": 0.1,
        "produce_prd_openapi": 0.1,
        "produce_design_doc": 0.1,
        "produce_comprehensive": 0.1,
        "produce_research_report": 0.1,
        "produce_business_report": 0.1,
        "produce_code_analysis": 0.1,
        "produce_tested_system": 0.1,
        "produce_deployable_service": 0.1,
    }


# 缓存解析结果
_STAGE_TEMPERATURES_CACHE: dict[str, float] | None = None


def STAGE_TEMPERATURES() -> dict[str, float]:
    """获取阶段温度映射（带缓存）"""
    global _STAGE_TEMPERATURES_CACHE
    if _STAGE_TEMPERATURES_CACHE is None:
        _STAGE_TEMPERATURES_CACHE = _get_stage_temperatures()
    return _STAGE_TEMPERATURES_CACHE


class LLMClient(Protocol):
    """LLM 客户端协议：输入 prompt，返回解析后的 dict"""

    async def complete(
        self, prompt: str, schema_hint: str = "", model_override: str = "", agent_role: str = ""
    ) -> dict[str, Any]: ...


class StubLLM:
    """桩 LLM：无 API key 时返回符合各阶段 JSON schema 的假数据

    根据 prompt 中出现的阶段关键字返回对应结构的假数据，
    保证端到端流程在无 LLM 时也能跑通。
    """

    async def complete(
        self,
        prompt: str,
        schema_hint: str = "",
        model_override: str = "",
        agent_role: str = "",
    ) -> dict[str, Any]:
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
                "complexity": "full",
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
        if "Produce" in prompt or schema_hint.startswith("produce"):
            # 默认 PRD + OpenAPI 交付物
            if schema_hint == "produce_prd_openapi" or "PRD" in prompt or "OpenAPI" in prompt:
                return {
                    "prd": {
                        "title": "会议决策系统 PRD",
                        "goal": "构建面向中小团队的会议决策系统",
                        "scope": "MVP 范围覆盖会议创建、六阶段讨论、结构化产出",
                        "assumptions": ["团队已具备基本技术能力"],
                        "constraints": ["单会议串行执行"],
                        "api_endpoints": ["POST /meetings - 创建会议", "POST /meetings/{id}/run - 运行会议"],
                        "open_questions": ["是否需要支持分布式部署？"],
                    },
                    "openapi": (
                        "openapi: 3.0.0\n"
                        "info:\n"
                        "  title: 会议决策系统 API\n"
                        "  version: 1.0.0\n"
                        "paths:\n"
                        "  /meetings:\n"
                        "    post:\n"
                        "      summary: 创建会议\n"
                    ),
                }
            # 根据产出模板中的任务描述关键字区分交付物类型
            if "产出架构设计文档" in prompt:
                return {
                    "design_doc": {
                        "title": "系统架构设计文档",
                        "overview": "本系统基于多智能体协作实现会议决策结构化产出。",
                        "architecture": "分层架构：API 层（FastAPI）、编排层（状态机）、Agent 层（LLM 调用）、存储层（SQLite + 向量库）。",
                        "tech_stack": ["Python 3.12", "FastAPI", "Pydantic", "SQLite"],
                        "data_model": "核心实体：Meeting、Message、Claim、Conflict、Artifact。",
                        "api_design": "RESTful API，JSON 格式，支持 WebSocket 实时推送。",
                        "deployment": "Docker 容器部署，支持水平扩展。",
                        "risks": ["LLM 调用延迟", "并发会议资源隔离"],
                        "open_questions": ["是否需要分布式部署？"],
                    }
                }
            if "产出综合设计文档" in prompt:
                return {
                    "comprehensive": {
                        "title": "综合设计文档",
                        "requirements": {
                            "goal": "构建多智能体会议决策系统",
                            "functional": ["会议创建与管理", "多阶段讨论流程", "结构化产出"],
                            "non_functional": ["响应时间 < 5s", "支持并发会议"],
                            "constraints": ["单会议串行执行"],
                        },
                        "system_design": {
                            "architecture": "分层架构，状态机驱动",
                            "components": ["编排器: 控制阶段流转", "Agent 层: 调用 LLM 生成内容"],
                            "data_flow": "用户请求 → 编排器 → Agent → LLM → 产出物",
                        },
                        "api_design": {
                            "endpoints": ["POST /meetings - 创建会议", "POST /meetings/{id}/run - 运行会议"],
                            "auth": "API Key 认证",
                            "error_handling": "统一 JSON 错误响应",
                        },
                        "data_model": {
                            "entities": ["Meeting: 会议聚合根", "Artifact: 产出物"],
                            "relationships": "Meeting 1:1 Artifact",
                            "storage": "SQLite 持久化",
                        },
                    }
                }
            if "产出调研报告" in prompt:
                return {
                    "research_report": {
                        "title": "技术调研报告",
                        "summary": "围绕会议决策系统的技术选型与可行性进行了调研。",
                        "findings": [
                            {
                                "topic": "LLM 集成方案",
                                "detail": "采用 OpenAI 兼容接口，支持多模型切换。",
                                "source": "技术调研",
                            },
                            {"topic": "沙箱隔离", "detail": "Docker 容器隔离用户代码执行。", "source": "安全评估"},
                        ],
                        "analysis": "当前技术方案可行，需关注 LLM 调用成本和延迟。",
                        "recommendations": ["优先使用 stub 模式进行开发测试", "生产环境接入真实 LLM"],
                        "references": ["OpenAI API 文档", "Docker 安全最佳实践"],
                    }
                }
            if "产出商业报告" in prompt:
                return {
                    "business_report": {
                        "title": "商业分析报告",
                        "executive_summary": "会议决策系统可显著降低团队决策成本。",
                        "market_analysis": "目标市场为中小型技术团队，存在明确的效率痛点。",
                        "financial_projection": "预计首年覆盖 1000+ 团队，营收增长稳定。",
                        "risk_assessment": "主要风险为 LLM 成本波动和竞品压力。",
                        "strategic_recommendation": "建议以 SaaS 模式切入，先免费后付费。",
                        "next_steps": ["完成 MVP 开发", "小范围内测", "收集用户反馈"],
                    }
                }
            if "生成 Python 数据分析代码" in prompt:
                return {
                    "code_analysis": {
                        "title": "数据分析示例",
                        "description": "基础数据统计与输出",
                        "code": "data = [10, 20, 30, 40, 50]\nprint('count:', len(data))\nprint('sum:', sum(data))\nprint('mean:', sum(data) / len(data))",
                        "expected_output": "输出数据计数、总和与均值",
                    }
                }
            if "生成完整的 Python 代码和对应的 pytest 测试" in prompt:
                return {
                    "tested_system": {
                        "title": "计算器模块测试",
                        "description": "基础加法运算模块及测试",
                        "main_code": "def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n",
                        "test_code": "from main_generated import add, multiply\n\ndef test_add():\n    assert add(1, 2) == 3\n\ndef test_add_negative():\n    assert add(-1, -1) == -2\n\ndef test_multiply():\n    assert multiply(3, 4) == 12\n",
                        "run_command": "python -m pytest test_generated.py -v",
                    }
                }
            if "可部署服务" in prompt or "deployable_service" in prompt:
                return {
                    "deployable_service": {
                        "title": "示例 Wiki 服务",
                        "description": "基础 FastAPI Wiki 服务（Stub 降级数据）",
                        "app_code": (
                            "from fastapi import FastAPI\n"
                            "from pydantic import BaseModel\n"
                            "\n"
                            'app = FastAPI(title="Stub Wiki")\n'
                            "\n"
                            "pages = {}\n"
                            "\n"
                            "class Page(BaseModel):\n"
                            "    title: str\n"
                            '    content: str = ""\n'
                            "\n"
                            '@app.get("/health")\n'
                            "def health():\n"
                            '    return {"status": "ok"}\n'
                            "\n"
                            '@app.get("/pages/{title}")\n'
                            "def get_page(title: str):\n"
                            '    return pages.get(title, {"detail": "not found"})\n'
                            "\n"
                            '@app.post("/pages")\n'
                            "def create_page(page: Page):\n"
                            "    pages[page.title] = page\n"
                            '    return {"status": "created", "title": page.title}\n'
                        ),
                        "requirements_txt": "fastapi\nuvicorn[standard]\n",
                        "dockerfile": (
                            "FROM python:3.12-slim\n"
                            "WORKDIR /app\n"
                            "COPY requirements.txt .\n"
                            "RUN pip install --no-cache-dir -r requirements.txt\n"
                            "COPY app.py .\n"
                            "EXPOSE 8000\n"
                            'CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]\n'
                        ),
                        "docker_compose": (
                            "version: '3.8'\nservices:\n  wiki:\n    build: .\n    ports:\n      - \"8000:8000\"\n"
                        ),
                        "readme": "# Stub Wiki\n\n开发降级模式生成的示例服务。\n\n## 启动\n```bash\npip install -r requirements.txt\nuvicorn app:app --host 0.0.0.0 --port 8000\n```\n",
                        "port": 8000,
                        "run_command": "uvicorn app:app --host 0.0.0.0 --port 8000",
                        "credentials": {},
                    }
                }
            # 默认：PRD + OpenAPI
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

    async def complete_text(self, prompt: str, temperature: float = 0.1) -> str:
        """M1.1: 桩摘要生成——从 prompt 中提取发言行生成简化摘要"""
        lines = []
        for line in prompt.splitlines():
            stripped = line.strip()
            if (
                stripped
                and not stripped.startswith("请")
                and not stripped.startswith("丢弃")
                and not stripped.startswith("发言内容")
                and not stripped.startswith("摘要")
            ):
                lines.append(stripped)
        if not lines:
            return "（stub 摘要：无发言内容）"
        return "历史摘要（stub）：" + "；".join(l[:60] for l in lines[:5])

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


# 分阶段温度策略已迁移到 config.py 的 settings.llm_stage_temperatures
# 通过 STAGE_TEMPERATURES() 函数获取（带缓存和 JSON 解析容错）


class CircuitBreaker:
    """LLM 熔断器：连续失败超阈值时熔断，拒绝后续请求一段时间

    状态机：closed → open（连续失败 >= threshold）→ half_open（冷却后）→ closed/half_open
    """

    def __init__(
        self,
        failure_threshold: int = settings.llm_circuit_failure_threshold,
        recovery_timeout: float = settings.llm_circuit_recovery_timeout,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._state = "closed"  # closed | open | half_open
        self._opened_at: float = 0.0

    @property
    def state(self) -> str:
        return self._state

    def can_call(self) -> bool:
        """是否允许调用 LLM"""
        if self._state == "open":
            import time

            if time.monotonic() - self._opened_at >= self.recovery_timeout:
                self._state = "half_open"
                logger.info("熔断器进入 half_open 状态，尝试恢复")
                return True
            return False
        return True

    def record_success(self) -> None:
        self._failure_count = 0
        if self._state != "closed":
            logger.info("熔断器恢复到 closed 状态")
        self._state = "closed"

    def record_failure(self) -> None:
        self._failure_count += 1
        if self._failure_count >= self.failure_threshold and self._state != "open":
            self._state = "open"
            import time

            self._opened_at = time.monotonic()
            logger.error(
                "熔断器打开：连续失败 %d 次，%gs 内拒绝所有 LLM 调用",
                self._failure_count,
                self.recovery_timeout,
            )
            # 审计：熔断器跳闸
            try:
                from app.observability.audit import audit

                audit(
                    "system.llm_circuit_tripped",
                    "error",
                    {
                        "failure_count": self._failure_count,
                        "recovery_timeout_s": self.recovery_timeout,
                    },
                )
            except Exception:
                pass


# 进程级单例熔断器
_circuit_breaker = CircuitBreaker()


def get_circuit_breaker() -> CircuitBreaker:
    """获取全局熔断器"""
    return _circuit_breaker


class RealLLM:
    """真实 LLM 客户端：调 openai 兼容接口（httpx）

    读取 env: CONCLAVE_LLM_API_KEY / CONCLAVE_LLM_BASE_URL / CONCLAVE_LLM_MODEL

    支持会议级别的模型覆盖：通过 llm_providers.get_meeting_llm_config(meeting_id)
    读取当前会议设置的模型/API Key/Base URL 覆盖全局默认。
    会议ID通过 contextvars.get_meeting_id() 获取。

    三明治模式（结构化输出加固）：
    1. 请求层：system message 注入对应 Pydantic 模型的 JSON Schema；
       传 response_format={"type":"json_object"}（接口不支持时自动降级）。
    2. 解析层：用 schemas.py 对应模型 model_validate 校验。
    3. 重试层：解析失败把 ValidationError 信息追加到 prompt 再调，最多 3 次；
       3 次都失败则降级用 StubLLM 同阶段数据，保证流程不中断。

    分阶段温度：temperature 不再全局锁死为 0，而是按 schema_hint（阶段名）
    查 STAGE_TEMPERATURES 取值。关键阶段锁死，讨论阶段适度放开。
    """

    # 最大重试次数（含首次）
    MAX_ATTEMPTS = settings.llm_max_attempts

    def __init__(self) -> None:
        self.api_key = settings.llm_api_key
        self.base_url = settings.llm_base_url or "https://api.openai.com/v1"
        self.model = settings.llm_model
        # [SECURITY-FIX] 配置连接池限制 + 响应体大小保护
        self._max_response_size = 10 * 1024 * 1024  # 10MB 响应体上限
        self._client = httpx.AsyncClient(
            timeout=settings.llm_default_timeout,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30,
            ),
        )
        # 接口是否支持 json_object 响应格式；遇到 400 时自动置 False 并回退
        # 注意：按 (base_url, model) 维度缓存，不同provider/model支持情况可能不同
        self._json_mode_supported: dict[str, bool] = {}

    def _resolve_config(self) -> tuple[str, str, str]:
        """解析当前调用应使用的 (base_url, api_key, model)

        优先级：会议级覆盖 > 租户级覆盖 > 全局默认（环境变量）
        """
        try:
            from app.context import get_meeting_id
            from app.llm_providers import get_meeting_llm_config

            mid = get_meeting_id()
            if mid and mid != "-":
                base_url, api_key, model, _pid = get_meeting_llm_config(mid)
                if base_url and api_key and model:
                    return base_url, api_key, model
        except Exception:
            pass
        # 租户级覆盖
        try:
            from app.tenants.context import get_tenant_id
            from app.tenants.settings_override import resolve_llm_config

            tid = get_tenant_id()
            if tid is not None:
                t_base, t_key, t_model = resolve_llm_config(
                    tid, self.base_url, self.api_key, self.model
                )
                if t_base and t_key and t_model:
                    return t_base, t_key, t_model
        except Exception:
            pass
        return self.base_url, self.api_key, self.model

    def _supports_json(self, base_url: str, model: str) -> bool:
        key = f"{base_url}|{model}"
        return self._json_mode_supported.get(key, True)

    def _set_json_mode(self, base_url: str, model: str, supported: bool) -> None:
        key = f"{base_url}|{model}"
        self._json_mode_supported[key] = supported

    async def aclose(self) -> None:
        """关闭底层 httpx 连接池，防止事件循环关闭时挂起"""
        with contextlib.suppress(Exception):
            await self._client.aclose()

    async def complete(
        self, prompt: str, schema_hint: str = "", model_override: str = "", agent_role: str = ""
    ) -> dict[str, Any]:
        """三明治模式：请求层 schema 注入 -> 解析层 Pydantic 校验 -> 重试层 -> 降级

        model_override: per-role 或 per-stage 模型覆盖（格式: "provider_id:model_id" 或 "model_id"）
        agent_role: 发起调用的 Agent 角色名（用于 trace/cost 记录）
        """
        # 熔断器检查
        if not _circuit_breaker.can_call():
            logger.warning("熔断器打开，跳过 LLM 调用，直接降级到 Stub")
            from app.observability.log_bus import log_bus

            log_bus.warning(
                f"LLM 熔断器打开，直接降级: stage={schema_hint}",
                logger="agents.llm",
            )
            return await StubLLM().complete(prompt, schema_hint)

        model_cls = SCHEMA_MAP.get(schema_hint)
        schema_desc = self._schema_description(model_cls)
        # schema_hint 即阶段名，用于 trace 记录
        stage = schema_hint
        temp = STAGE_TEMPERATURES().get(stage, 0.0)
        # 解析当前生效的模型配置（用于日志记录）
        _log_base, _log_key, _log_model = self._resolve_config()

        # [FALLBACK] 上下文窗口管理：超长 prompt 自动截断
        from app.llm_providers import estimate_tokens, trim_prompt_to_budget

        prompt_token_est = estimate_tokens(prompt)
        if prompt_token_est > settings.llm_max_prompt_tokens:
            from app.observability.log_bus import log_bus

            log_bus.warning(
                f"Prompt 超长 ({prompt_token_est} tokens), 自动截断到 {settings.llm_max_prompt_tokens}",
                logger="agents.llm",
                extra={"stage": stage, "original_tokens": prompt_token_est},
            )
            prompt = trim_prompt_to_budget(prompt, max_tokens=settings.llm_max_prompt_tokens)

        # [FALLBACK] Provider 回退链：连接失败时尝试下一个 provider
        from app.llm_providers import get_fallback_chain

        fallback_chain = get_fallback_chain(model_override=model_override or None)

        current_prompt = prompt
        last_error = ""
        provider_idx = 0

        while provider_idx < len(fallback_chain):
            config_override = fallback_chain[provider_idx]
            _p_url, _p_key, _p_model, _p_id = config_override

            for attempt in range(1, self.MAX_ATTEMPTS + 1):
                try:
                    content = await self._call_api(
                        current_prompt,
                        schema_desc,
                        stage,
                        attempt,
                        config_override=(_p_url, _p_key, _p_model),
                        agent_role=agent_role,
                        provider_id=_p_id,
                    )
                    # [FALLBACK] 最小输出长度校验：防止 LLM 返回空内容导致管线空转
                    # cross_team / produce / arbitrate 需要生成结构化内容（冲突列表、PRD、裁决），
                    # 50 字符远远不够；其他阶段（clarify, intra_team 等）保持较低阈值
                    _min_len = 200 if stage in ("cross_team", "produce", "arbitrate") else 50
                    if len(content.strip()) < _min_len:
                        raise ValueError(
                            f"LLM 返回内容过短 ({len(content.strip())} chars < {_min_len})，"
                            f"阶段={stage} 模型={_p_model} 输出质量不足"
                        )
                    parsed = self._extract_json(content)
                    if model_cls is not None:
                        validated: BaseModel = model_cls.model_validate(parsed)
                        result = validated.model_dump()
                    else:
                        result = parsed if isinstance(parsed, dict) else {"result": parsed}
                    update_last_record(
                        parsed_result=result if isinstance(result, dict) else None,
                        validation_status="valid",
                    )
                    logger.info(
                        "阶段=%s attempt=%d provider=%s 解析成功 (temp=%.1f)",
                        stage,
                        attempt,
                        _p_id,
                        temp,
                    )
                    from app.observability.log_bus import log_bus

                    log_bus.info(
                        f"LLM 调用成功: stage={stage}, attempt={attempt}, provider={_p_id}",
                        logger="agents.llm",
                        extra={"stage": stage, "attempt": attempt, "model": _p_model, "provider": _p_id, "temp": temp},
                    )
                    if schema_hint == "intra_team" and isinstance(result, dict):
                        claims_val = result.get("claims")
                        if not claims_val:
                            raise ValueError("intra_team 阶段 claims 为空，LLM 未输出有效论点")
                    # produce 阶段：校验代码类产出的关键字段非空
                    if schema_hint.startswith("produce") and isinstance(result, dict):
                        _ds = result.get("deployable_service")
                        if isinstance(_ds, dict) and not _ds.get("app_code"):
                            raise ValueError("deployable_service.app_code 为空，LLM 未生成有效应用代码")
                        _ca = result.get("code_analysis")
                        if isinstance(_ca, dict) and not _ca.get("code"):
                            raise ValueError("code_analysis.code 为空，LLM 未生成有效代码")
                        _ts = result.get("tested_system")
                        if isinstance(_ts, dict) and not _ts.get("main_code") and not _ts.get("test_code"):
                            raise ValueError("tested_system 主代码和测试代码均为空")
                    _circuit_breaker.record_success()
                    return result  # type: ignore[no-any-return]
                except (httpx.ConnectError, httpx.TimeoutException) as conn_err:
                    # 连接级错误：切换到下一个 provider
                    last_error = f"{_p_id}: {type(conn_err).__name__}: {conn_err}"
                    logger.warning(
                        "阶段=%s provider=%s 连接失败, 尝试下一个 provider: %s",
                        stage,
                        _p_id,
                        last_error[:200],
                    )
                    from app.observability.log_bus import log_bus

                    log_bus.warning(
                        f"Provider {_p_id} 连接失败, 尝试回退",
                        logger="agents.llm",
                        extra={"stage": stage, "provider": _p_id, "error": last_error[:300]},
                    )
                    break  # 跳出重试循环，尝试下一个 provider
                except (ValidationError, json.JSONDecodeError, KeyError, httpx.HTTPError) as e:
                    error_detail = ""
                    if isinstance(e, httpx.HTTPStatusError) and e.response is not None:
                        error_detail = f" [HTTP {e.response.status_code}: {e.response.text[:200]}]"
                    last_error = f"{_p_id}: {type(e).__name__}: {e}{error_detail}"
                    logger.warning("阶段=%s provider=%s attempt=%d 失败: %s", stage, _p_id, attempt, last_error[:200])
                    update_last_record(validation_status="invalid", error_detail=last_error)
                    current_prompt = (
                        f"{prompt}\n\n"
                        f"【上一次输出校验失败（第 {attempt} 次），错误：{last_error}】\n"
                        f"请严格按给定 JSON Schema 重新输出，仅输出合法 JSON，不要包含注释或围栏。"
                    )

            provider_idx += 1

        # 所有 provider 全部失败：降级到 StubLLM
        _circuit_breaker.record_failure()
        logger.error("阶段=%s 三次重试全部失败，降级到 StubLLM。最后错误: %s", stage, last_error[:300])
        # 旁路日志：LLM 降级
        from app.observability.log_bus import log_bus

        log_bus.error(
            f"LLM 降级到 StubLLM: stage={stage}",
            logger="agents.llm",
            extra={
                "stage": stage,
                "attempts": self.MAX_ATTEMPTS,
                "last_error": last_error[:500],
                "action": "fallback_stub",
            },
        )
        # 记录降级到 trace
        _fb_base, _fb_key, _fb_model = self._resolve_config()
        record_call(
            stage=stage,
            model=_fb_model,
            temperature=STAGE_TEMPERATURES().get(stage, 0.0),
            seed=settings.llm_seed,
            prompt=prompt,
            raw_response="",
            parsed_result=None,
            validation_status="fallback_stub",
            attempt=self.MAX_ATTEMPTS,
            latency_ms=0,
        )
        stub = StubLLM()
        return await stub.complete(prompt, schema_hint=schema_hint)

    async def complete_text(self, prompt: str, temperature: float = 0.1) -> str:
        """M1.1: 纯文本补全（非 JSON schema），用于上下文摘要生成等场景。

        比 complete() 轻量：无 schema 校验、无 JSON 解析、无 provider 回退链。
        失败时返回空字符串（ContextManager 已处理空值降级）。
        """
        if not _circuit_breaker.can_call():
            logger.warning("熔断器打开，跳过摘要 LLM 调用")
            return ""
        try:
            content = await self._call_api(
                prompt,
                schema_desc="",
                stage="summarize",
                attempt=1,
                agent_role="context_summarizer",
                system_message_override="你是会议助手。请用简洁的中文生成摘要，保留关键观点和结论。",
            )
            _circuit_breaker.record_success()
            return content
        except Exception as e:
            _circuit_breaker.record_failure()
            logger.warning("摘要 LLM 调用失败，返回空字符串: %s", e)
            return ""

    # ---------- 请求层 ----------

    @staticmethod
    def _schema_description(model_cls: type[BaseModel] | None) -> str:
        """把 Pydantic 模型转成 JSON Schema 文本，注入 system message"""
        if model_cls is None:
            return ""
        schema = model_cls.model_json_schema()
        return json.dumps(schema, ensure_ascii=False, indent=2)

    async def _call_api(
        self,
        user_prompt: str,
        schema_desc: str,
        stage: str = "",
        attempt: int = 1,
        config_override: tuple[str, str, str] | None = None,
        agent_role: str = "",
        provider_id: str = "",
        system_message_override: str = "",
    ) -> str:
        """调用 chat completions，返回 message content 字符串

        第1层确定性约束：
        - temperature 按阶段查 STAGE_TEMPERATURES（关键阶段=0，讨论阶段=0.3）
        - top_p 固定 1.0
        - seed 固定 42（API 支持则同一输入必同一输出）
        - system message 末尾加 /no_think（关闭 Qwen3.5 思考模式）

        支持会议级模型覆盖：每次调用解析 _resolve_config() 获取当前生效的
        base_url / api_key / model，支持会议运行中切换模型和BYOK。

        config_override: 外部指定的 (base_url, api_key, model)，用于 provider 回退链。
        """
        import time

        # 解析当前生效的 LLM 配置（支持会议级覆盖 + 外部回退覆盖）
        if config_override:
            base_url, api_key, model = config_override
        else:
            base_url, api_key, model = self._resolve_config()

        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if system_message_override:
            # M1.1: 纯文本模式（摘要生成等），不强制 JSON，不加 /no_think（允许模型思考）
            system_content = system_message_override
        else:
            system_content = "你是会议决策助手，严格输出 JSON，不要输出多余文本。"
            if schema_desc:
                system_content += (
                    f"\n输出必须严格符合以下 JSON Schema（多余字段会被忽略，缺字段尽量补全默认值）：\n{schema_desc}"
                )
            # 关闭 Qwen3.5 思考模式，防止思考过程干扰 JSON 输出
            if settings.llm_no_think:
                system_content += "\n/no_think"
        # 分阶段温度：按 stage 查表，默认 0（最严格）
        temp = STAGE_TEMPERATURES().get(stage, 0.0)
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_prompt},
            ],
            # 第1层：参数确定性 —— 分阶段温度, top_p=1.0, seed=settings.llm_seed
            "temperature": temp,
            "top_p": 1.0,
            "seed": 42,
        }
        # 请求层：纯文本模式不传 response_format；JSON 模式按 base_url+model 缓存支持情况
        if not system_message_override and self._supports_json(base_url, model):
            body["response_format"] = {"type": "json_object"}

        latency_ms = 0
        # produce 阶段生成大量文本（OpenAPI），需要更长超时
        # DeepSeek-V3.2 生成 PRD+OpenAPI 可能需要 200-400s
        # produce_* 子类型同样需要长超时
        stage_timeout = settings.llm_produce_timeout if stage.startswith("produce") else settings.llm_default_timeout
        t0 = time.monotonic()
        try:
            resp = await self._client.post(url, headers=headers, json=body, timeout=stage_timeout)
            # [SECURITY-FIX] 检查响应大小，防止恶意/故障端点返回超大响应体
            content_length = resp.headers.get("content-length")
            if content_length and int(content_length) > self._max_response_size:
                raise ValueError(f"LLM response too large: {content_length} bytes (max {self._max_response_size})")
            resp.raise_for_status()
            latency_ms = int((time.monotonic() - t0) * 1000)
        except httpx.HTTPStatusError as e:
            latency_ms = int((time.monotonic() - t0) * 1000)
            # 接口可能不支持 response_format（返回 400），自动降级去掉该参数重试一次
            if (
                self._supports_json(base_url, model)
                and e.response.status_code == 400
                and self._looks_like_json_mode_error(e)
            ):
                self._set_json_mode(base_url, model, False)
                body.pop("response_format", None)
                try:
                    t0 = time.monotonic()
                    resp = await self._client.post(url, headers=headers, json=body, timeout=stage_timeout)
                    resp.raise_for_status()
                    latency_ms = int((time.monotonic() - t0) * 1000)
                except httpx.HTTPStatusError as e2:
                    # json_mode降级后仍然HTTP错误，记录失败调用
                    latency_ms = int((time.monotonic() - t0) * 1000)
                    record_call(
                        stage=stage,
                        model=model,
                        temperature=temp,
                        seed=settings.llm_seed,
                        prompt=user_prompt,
                        raw_response=f"HTTP {e2.response.status_code}: {e2.response.text[:500]}",
                        validation_status="invalid",
                        attempt=attempt,
                        latency_ms=latency_ms,
                        input_tokens=0,
                        output_tokens=0,
                        total_tokens=0,
                        agent_role=agent_role,
                        provider_id=provider_id,
                        error_detail=f"HTTPStatusError after json_mode fallback: {e2.response.status_code} {e2.response.text[:300]}",
                    )
                    raise
            else:
                # 记录失败的HTTP错误调用到 trace（非json_mode 400或其他HTTP错误）
                record_call(
                    stage=stage,
                    model=model,
                    temperature=temp,
                    seed=settings.llm_seed,
                    prompt=user_prompt,
                    raw_response=f"HTTP {e.response.status_code}: {e.response.text[:500]}",
                    validation_status="invalid",
                    attempt=attempt,
                    latency_ms=latency_ms,
                    input_tokens=0,
                    output_tokens=0,
                    total_tokens=0,
                    agent_role=agent_role,
                    provider_id=provider_id,
                    error_detail=f"HTTPStatusError: {e.response.status_code} {e.response.text[:300]}",
                )
                raise
        except (
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
            httpx.NetworkError,
            httpx.TimeoutException,
            OSError,
        ) as e:
            # 网络级错误（连接失败、超时等）：必须先记录调用再抛出，
            # 否则 complete() 中的 update_last_record 会污染上一条成功记录
            latency_ms = int((time.monotonic() - t0) * 1000)
            record_call(
                stage=stage,
                model=model,
                temperature=temp,
                seed=settings.llm_seed,
                prompt=user_prompt,
                raw_response=str(e)[:500],
                validation_status="invalid",
                attempt=attempt,
                latency_ms=latency_ms,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                agent_role=agent_role,
                provider_id=provider_id,
                error_detail=f"{type(e).__name__}: {str(e)[:300]}",
            )
            raise

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        # 解析 token 用量
        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", input_tokens + output_tokens)
        # 第1层：记录完整调用信息到 trace（temperature 用实际阶段温度）
        record_call(
            stage=stage,
            model=model,
            temperature=temp,
            seed=settings.llm_seed,
            prompt=user_prompt,
            raw_response=content,
            parsed_result=None,  # 解析后由 complete() 更新
            validation_status="valid",  # 默认，complete() 会根据解析结果更新
            attempt=attempt,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            agent_role=agent_role,
            provider_id=provider_id,
        )
        # 成本可观测性：记录 LLM 调用成本到 CostTracker
        # （estimate_llm_cost 内部会优先查 llm_providers 的多厂商定价表）
        try:
            from app.observability.cost_tracker import get_cost_tracker

            await get_cost_tracker().record_llm(
                node=stage,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
            )
        except Exception:
            pass
        return content  # type: ignore[no-any-return]

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
            # 去掉首行围栏（```json 或 ```）
            parts = content.split("\n", 1)
            if len(parts) >= 2:
                content = parts[1]
                # 去掉闭合围栏（如果存在）
                closing = content.rsplit("```", 1)
                if len(closing) >= 2:
                    content = closing[0]
        return json.loads(content)


def get_llm() -> LLMClient:
    """按配置返回 LLM 客户端：有 key 用真实，否则用 stub"""
    if settings.use_real_llm:
        return RealLLM()
    return StubLLM()
