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
    input_tokens: int = 0          # prompt tokens
    output_tokens: int = 0         # completion tokens
    total_tokens: int = 0          # 总 tokens
    agent_role: str = ""          # 发起调用的 Agent 角色（如 engineer, moderator）
    provider_id: str = ""         # 实际使用的 provider（siliconflow, deepseek 等）
    error_detail: str = ""        # 错误详情（HTTP 错误响应体、异常信息等，便于排查）
    request_id: str = ""          # 关联的 HTTP 请求 ID（全链路追踪）
    meeting_id: str = ""          # 关联的会议 ID（全链路追踪）
    runner_session_id: str = ""   # 关联的 Runner 执行会话 ID（因果链）


class CallTrace(BaseModel):
    """一次会议的完整 LLM 调用追踪"""
    meeting_id: str = ""
    calls: list[LLMCallRecord] = Field(default_factory=list)

    def add_call(self, record: LLMCallRecord) -> None:
        """追加一条调用记录"""
        self.calls.append(record)

    def summary(self) -> dict[str, Any]:
        """返回追踪摘要：总调用数、成功率、降级数、不一致数、延迟分布、token 统计"""
        total = len(self.calls)
        valid = sum(1 for c in self.calls if c.validation_status == "valid")
        fallback = sum(1 for c in self.calls if c.validation_status == "fallback_stub")
        invalid = sum(1 for c in self.calls if c.validation_status == "invalid")
        inconsistent = sum(1 for c in self.calls if c.consistency_status != "consistent")
        latencies = [c.latency_ms for c in self.calls if c.latency_ms > 0]
        # token 统计
        total_input_tokens = sum(c.input_tokens for c in self.calls)
        total_output_tokens = sum(c.output_tokens for c in self.calls)
        total_tokens = sum(c.total_tokens for c in self.calls)
        # 按阶段分组统计
        stage_stats: dict[str, dict[str, Any]] = {}
        for c in self.calls:
            s = stage_stats.setdefault(
                c.stage,
                {"calls": 0, "valid": 0, "fallback": 0, "latencies": [], "input_tokens": 0, "output_tokens": 0},
            )
            s["calls"] += 1
            if c.validation_status == "valid":
                s["valid"] += 1
            if c.validation_status == "fallback_stub":
                s["fallback"] += 1
            if c.latency_ms > 0:
                s["latencies"].append(c.latency_ms)
            s["input_tokens"] += c.input_tokens
            s["output_tokens"] += c.output_tokens
        # 按角色分组统计
        role_stats: dict[str, dict[str, Any]] = {}
        for c in self.calls:
            role = c.agent_role or "unknown"
            r = role_stats.setdefault(
                role,
                {"calls": 0, "valid": 0, "fallback": 0, "latencies": [], "input_tokens": 0, "output_tokens": 0},
            )
            r["calls"] += 1
            if c.validation_status == "valid":
                r["valid"] += 1
            if c.validation_status == "fallback_stub":
                r["fallback"] += 1
            if c.latency_ms > 0:
                r["latencies"].append(c.latency_ms)
            r["input_tokens"] += c.input_tokens
            r["output_tokens"] += c.output_tokens
        # 计算各阶段/角色平均延迟
        for stats_dict in (stage_stats, role_stats):
            for s in stats_dict.values():
                lats = s.pop("latencies")
                s["avg_latency_ms"] = sum(lats) / len(lats) if lats else 0
        # 收集所有错误详情
        errors = [c.error_detail for c in self.calls if c.error_detail]
        return {
            "total_calls": total,
            "valid_calls": valid,
            "fallback_calls": fallback,
            "invalid_calls": invalid,
            "inconsistent_calls": inconsistent,
            "success_rate": f"{valid / total * 100:.1f}%" if total > 0 else "N/A",
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
            "max_latency_ms": max(latencies) if latencies else 0,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_tokens": total_tokens,
            "avg_tokens_per_call": total_tokens // total if total > 0 else 0,
            "stage_stats": stage_stats,
            "role_stats": role_stats,
            "errors": errors[:10],  # 最多返回前 10 条错误
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
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    agent_role: str = "",
    provider_id: str = "",
) -> None:
    """记录一次 LLM 调用到当前 trace（仅 RealLLM._call_api 调用）

    如果当前没有活跃的 trace（如 stub 模式或单元测试），静默跳过。
    自动注入 request_id 和 meeting_id 实现全链路追踪。
    """
    trace = _current_trace.get()
    if trace is None:
        import logging
        logging.getLogger("agents.trace").warning(
            f"record_call 跳过：当前无活跃 trace (stage={stage}, model={model})"
        )
        return
    # 从追踪上下文取 request_id 和 meeting_id
    from app.context import get_request_id, get_meeting_id, get_runner_session_id
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
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        agent_role=agent_role,
        provider_id=provider_id,
        request_id=get_request_id(),
        meeting_id=trace.meeting_id,
        runner_session_id=get_runner_session_id(),
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
