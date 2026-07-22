"""WebSocket 入站/出站消息的 Pydantic Schema。

目的：
- 对客户端 -> 服务端的消息做基本结构校验，避免脏数据进入控制路径；
- 为前端/客户端提供类型契约。

设计原则：
- 入站采用"宽进严出"：未识别的 type 字段不直接报错，而是返回 validation_result；
- 调用方根据 validation_result.is_valid 决定是否处理该消息；
- 严格校验控制信号路径（control.signal），防止注入/非法字段。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

# ---------------------------------------------------------------------------
# 入站消息
# ---------------------------------------------------------------------------


class WsPongMessage(BaseModel):
    type: Literal["pong"]


class WsPingMessage(BaseModel):
    type: Literal["ping"]


class WsControlSignalMessage(BaseModel):
    type: Literal["control.signal"]
    signal: Literal[
        "pause",
        "resume",
        "abort",
        "intervene",
        "approve_borrow",
        "reject_borrow",
        "freeze_borrow",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)


class WsChatMessage(BaseModel):
    """普通聊天消息（观众/参与者发言）"""

    type: Literal["chat"]
    content: str = Field(..., min_length=1, max_length=10000)
    reply_to: str | None = None


class WsReactionMessage(BaseModel):
    """反应/反馈消息（点赞、踩、追问等）"""

    type: Literal["reaction"]
    reaction: str = Field(..., min_length=1, max_length=32)
    target_id: str | None = None


class WsTypingMessage(BaseModel):
    type: Literal["typing"]
    is_typing: bool = True


# 所有入站类型的 Union
WsInboundMessage = (
    WsPongMessage | WsPingMessage | WsControlSignalMessage | WsChatMessage | WsReactionMessage | WsTypingMessage
)


class WsValidationResult(BaseModel):
    """校验结果。"""

    is_valid: bool
    message: WsInboundMessage | None = None
    error: str | None = None
    raw_type: str | None = None


def validate_inbound(raw: dict[str, Any]) -> WsValidationResult:
    """校验一条入站消息。

    策略：
    - 若 type 字段缺失或非字符串 -> invalid；
    - 若 type 是已注册类型 -> 按 schema 校验，失败返回 invalid；
    - 若 type 是未注册类型 -> is_valid=True，message=None，raw_type 透传。
      （宽松处理，允许未来扩展类型不阻塞旧服务）
    """
    if not isinstance(raw, dict):
        return WsValidationResult(is_valid=False, error="消息必须是 JSON 对象")

    msg_type = raw.get("type")
    if not isinstance(msg_type, str):
        return WsValidationResult(is_valid=False, error="消息缺少 type 字段")

    # pong 纯文本也允许
    if msg_type == "pong":
        return WsValidationResult(is_valid=True, message=WsPongMessage(type="pong"), raw_type="pong")

    type_map: dict[str, type[BaseModel]] = {
        "ping": WsPingMessage,
        "control.signal": WsControlSignalMessage,
        "chat": WsChatMessage,
        "reaction": WsReactionMessage,
        "typing": WsTypingMessage,
    }

    model_cls = type_map.get(msg_type)
    if model_cls is None:
        # 未知类型，宽容放行（交给上层处理/忽略）
        return WsValidationResult(is_valid=True, message=None, raw_type=msg_type)

    try:
        parsed = model_cls.model_validate(raw)
    except ValidationError as e:
        return WsValidationResult(
            is_valid=False,
            error=f"消息格式错误: {e.errors()[0].get('msg', 'invalid') if e.errors() else 'invalid'}",
            raw_type=msg_type,
        )
    # mypy: parsed 类型是 BaseModel，运行时是 WsInboundMessage 的子类
    return WsValidationResult(is_valid=True, message=parsed, raw_type=msg_type)  # type: ignore[arg-type]
