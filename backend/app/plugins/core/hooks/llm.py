"""LLM 调用相关钩子 Mixin。

拦截型（PreCall/Error）：可返回 Override/Fallback/Next 影响调用链
观察型（PostCall）：不影响主流程，用于审计/计量/日志
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from app.plugins.core.types import Fallback, LLMFallback, LLMOverride, Next, PluginContext


@dataclass
class LLMRequest:
    """LLM 调用请求。"""

    prompt: str
    schema_hint: str
    model: str
    base_url: str
    api_key: str
    agent_role: str
    stage: str
    meeting_id: str
    request_id: str
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """LLM 调用响应。"""

    content: str
    parsed: dict | None
    model: str
    provider: str


@dataclass
class LLMUsage:
    """LLM 调用用量统计。"""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: int
    cost_usd: float


@dataclass
class LLMErrorInfo:
    """LLM 调用错误信息。"""

    error_type: str  # connection | http | validation | quota | timeout | unknown
    status_code: int | None
    message: str
    raw_error: Exception | None = None


@runtime_checkable
class LLMPreCallMixin(Protocol):
    """LLM 调用前拦截钩子（拦截型）。

    返回:
      - LLMOverride: 替换本次调用的 api_key/model/base_url，终止后续拦截器
      - Fallback:     拒绝调用，返回 HTTP 错误（如配额耗尽）
      - Next/None:    弃权，交给下一个插件
    """

    async def on_llm_pre_call(
        self, ctx: PluginContext, req: LLMRequest
    ) -> LLMOverride | Next | Fallback | None: ...


@runtime_checkable
class LLMObserverMixin(Protocol):
    """LLM 调用后观察钩子（观察型）。用于记录用量、审计、成本统计。"""

    async def on_llm_post_call(
        self, ctx: PluginContext, req: LLMRequest, resp: LLMResponse, usage: LLMUsage
    ) -> None: ...


@runtime_checkable
class LLMErrorMixin(Protocol):
    """LLM 调用错误拦截钩子（拦截型）。

    返回:
      - LLMFallback: 提供降级配置（切换 key/model），触发重试
      - Next/None:    弃权，错误上抛
    """

    async def on_llm_error(
        self, ctx: PluginContext, req: LLMRequest, err: LLMErrorInfo
    ) -> LLMFallback | Next | None: ...
