"""领域事件 Payload 的 Pydantic 模型。

目的：
1. 为高频事件类型提供结构化 schema（替代裸 dict），IDE/类型检查器可提示；
2. 为未来 schema_version 迁移提供版本锚点；
3. 消费者可通过 model_validate 对 payload 做运行时校验（可选）。

约定：
- 每个具体事件类型一个 XxxPayload 模型，类名以 Payload 结尾；
- EVENT_REGISTRY 映射 type 字符串 -> 模型类，运行时校验时查；
- 未注册的事件类型仍按 dict 透传，不强校验（保持宽松兼容）。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 通用 Payload
# ---------------------------------------------------------------------------


class ErrorPayload(BaseModel):
    """节点执行异常"""

    stage: str
    error: str
    detail: dict[str, Any] = Field(default_factory=dict)


class StageChangePayload(BaseModel):
    """阶段切换"""

    from_stage: str
    to_stage: str
    reason: str = ""


class MessagePayload(BaseModel):
    """Agent 发言"""

    sender: str
    sender_role: str = ""
    content: str
    round: int = 0
    kind: str = "speak"  # speak | inject | moderator | system
    reply_to: str | None = None


class ProgressPayload(BaseModel):
    """进度事件（无结构变化，仅更新百分比/状态文字）"""

    stage: str
    percent: int = 0
    message: str = ""
    substep: str = ""


class MeetingLifecyclePayload(BaseModel):
    """会议生命周期：created/running/paused/completed/failed"""

    status: Literal["created", "running", "paused", "completed", "failed", "cancelled"]
    detail: dict[str, Any] = Field(default_factory=dict)


class ArtifactPayload(BaseModel):
    """产出物更新（PRD/OpenAPI/代码/报告）"""

    deliverable_type: str
    artifact_type: str  # prd | openapi | code | report | ...
    preview: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class UserInterventionPayload(BaseModel):
    """用户介入（inject/approve/reject/pause/resume）"""

    action: Literal["inject", "approve_borrow", "reject_borrow", "pause", "resume", "stop"]
    content: str = ""
    target: str | None = None


# ---------------------------------------------------------------------------
# 注册表（event_type -> Payload 模型）
# ---------------------------------------------------------------------------

EVENT_REGISTRY: dict[str, type[BaseModel]] = {
    "error": ErrorPayload,
    "stage_change": StageChangePayload,
    "message": MessagePayload,
    "progress": ProgressPayload,
    "meeting_status": MeetingLifecyclePayload,
    "artifact": ArtifactPayload,
    "user_intervention": UserInterventionPayload,
}


def validate_payload(event_type: str, payload: dict[str, Any]) -> BaseModel | None:
    """若 event_type 在注册表中，校验并返回 Pydantic 模型；否则返回 None。

    校验失败时抛 pydantic.ValidationError，由调用方决定是否降级为 dict。
    """
    model_cls = EVENT_REGISTRY.get(event_type)
    if model_cls is None:
        return None
    return model_cls.model_validate(payload)
