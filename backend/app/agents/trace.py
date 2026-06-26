# 第4层：调用追踪 —— 记录每次 LLM 调用的完整信息，用于审计和复现
# 仅 RealLLM 记录调用（StubLLM 不记录），但 CallTrace 对象对 stub 也存在（空记录）
from __future__ import annotations

import contextvars
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class LLMCallRecord(BaseModel):
    """单次 LLM 调用记录"""
    call_id: str
    timestamp: str
    stage: str = ""               # 阶段名（与 schema_hint 一致）
    model: str = ""
    temperature: float = 0.0
    seed: int = 42
    prompt: str = ""              # 完整 prompt
    raw_response: str = ""        # LLM 原始返回
    parsed_result: dict[str, Any] | None = None
    validation_status: str = "valid"       # "valid" | "invalid" | "fallback_stub"
    consistency_status: str = "consistent"  # "consistent" | "inconsistent_retry" | "low_confidence"
    attempt: int = 1              # 第几次尝试（校验重试）
    latency_ms: int = 0


class CallTrace(BaseModel):
    """一次会议的完整 LLM 调用追踪"""
    meeting_id: str = ""
    calls: list[LLMCallRecord] = Field(default_factory=list)

    def add_call(self, record: LLMCallRecord) -> None:
        """追加一条调用记录"""
        self.calls.append(record)

    def summary(self) -> dict[str, Any]:
        """返回追踪摘要：总调用数、成功率、降级数、不一致数"""
        total = len(self.calls)
        valid = sum(1 for c in self.calls if c.validation_status == "valid")
        fallback = sum(1 for c in self.calls if c.validation_status == "fallback_stub")
        inconsistent = sum(1 for c in self.calls if c.consistency_status != "consistent")
        return {
            "total_calls": total,
            "valid_calls": valid,
            "fallback_calls": fallback,
            "inconsistent_calls": inconsistent,
        }


# ---------- 模块级上下文：供 RealLLM 记录调用 ----------
# 使用 contextvars 确保异步环境下每个会议运行的 trace 隔离
_current_trace: contextvars.ContextVar[CallTrace | None] = contextvars.ContextVar(
    "conclave_current_trace", default=None
)


def set_current_trace(trace: CallTrace | None) -> None:
    """设置当前活跃的 CallTrace（nodes.py 在每个节点开始时调用）"""
    _current_trace.set(trace)


def get_current_trace() -> CallTrace | None:
    """获取当前活跃的 CallTrace"""
    return _current_trace.get()


def record_call(
    stage: str,
    model: str,
    temperature: float,
    seed: int,
    prompt: str,
    raw_response: str,
    parsed_result: dict[str, Any] | None = None,
    validation_status: str = "valid",
    attempt: int = 1,
    latency_ms: int = 0,
) -> None:
    """记录一次 LLM 调用到当前 trace（仅 RealLLM._call_api 调用）

    如果当前没有活跃的 trace（如 stub 模式或单元测试），静默跳过。
    """
    trace = _current_trace.get()
    if trace is None:
        return
    record = LLMCallRecord(
        call_id=f"call-{uuid.uuid4().hex[:12]}",
        timestamp=datetime.now(timezone.utc).isoformat(),
        stage=stage,
        model=model,
        temperature=temperature,
        seed=seed,
        prompt=prompt,
        raw_response=raw_response,
        parsed_result=parsed_result,
        validation_status=validation_status,
        attempt=attempt,
        latency_ms=latency_ms,
    )
    trace.add_call(record)


def update_last_record(**kwargs: Any) -> None:
    """更新当前 trace 中最后一条记录的字段（如解析后更新 validation_status / parsed_result）"""
    trace = _current_trace.get()
    if trace is None or not trace.calls:
        return
    last = trace.calls[-1]
    for key, value in kwargs.items():
        setattr(last, key, value)
