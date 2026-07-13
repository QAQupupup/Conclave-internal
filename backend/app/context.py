# 全链路追踪上下文：request_id + meeting_id 关联
# 使用 contextvars 在异步调用链中传播，确保一个请求从入口到出口的所有日志、事件、LLM 调用都能关联
from __future__ import annotations

import contextvars
import uuid

# ---------- contextvars ----------

# request_id：每个 HTTP 请求唯一（入口中间件分配）
_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

# meeting_id：当前请求关联的会议 ID（运行会议时设置）
_meeting_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "meeting_id", default="-"
)

# runner_session_id：Runner 执行会话 ID（每次 run() 调用分配）
# 用于关联一次会议运行期间的所有日志、事件、LLM 调用
_runner_session_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "runner_session_id", default="-"
)

# agent_role：当前 LLM 调用的 Agent 角色（每次 think/complete 调用前设置）
# 用于在日志/trace/cost 中标识是哪个角色发出的调用
_agent_role: contextvars.ContextVar[str] = contextvars.ContextVar(
    "agent_role", default=""
)


def new_request_id() -> str:
    """生成新的 request_id（短格式 UUID）"""
    return f"req-{uuid.uuid4().hex[:12]}"


def get_request_id() -> str:
    """获取当前上下文的 request_id"""
    return _request_id.get()


def set_request_id(rid: str) -> contextvars.Token[str]:
    """设置 request_id，返回 token 用于恢复"""
    return _request_id.set(rid)


def reset_request_id(token: contextvars.Token[str]) -> None:
    """恢复 request_id 到之前的值"""
    _request_id.reset(token)


def get_meeting_id() -> str:
    """获取当前上下文关联的 meeting_id"""
    return _meeting_id.get()


def set_meeting_id(mid: str) -> contextvars.Token[str]:
    """设置 meeting_id（在运行会议时调用），返回 token"""
    return _meeting_id.set(mid)


def reset_meeting_id(token: contextvars.Token[str]) -> None:
    """恢复 meeting_id"""
    _meeting_id.reset(token)


def new_runner_session_id() -> str:
    """生成新的 runner_session_id"""
    return f"rs-{uuid.uuid4().hex[:12]}"


def get_runner_session_id() -> str:
    """获取当前 Runner 执行会话 ID"""
    return _runner_session_id.get()


def set_runner_session_id(sid: str) -> contextvars.Token[str]:
    """设置 runner_session_id（在 Runner.run() 开头调用）"""
    return _runner_session_id.set(sid)


def reset_runner_session_id(token: contextvars.Token[str]) -> None:
    """恢复 runner_session_id"""
    _runner_session_id.reset(token)


def get_agent_role() -> str:
    """获取当前 LLM 调用的 Agent 角色"""
    return _agent_role.get()


def set_agent_role(role: str) -> contextvars.Token[str]:
    """设置当前 LLM 调用的 Agent 角色，返回 token 用于恢复"""
    return _agent_role.set(role)


def reset_agent_role(token: contextvars.Token[str]) -> None:
    """恢复 agent_role"""
    _agent_role.reset(token)


def get_trace_context() -> dict[str, str]:
    """获取当前追踪上下文快照（用于日志注入）

    返回 {"request_id": "...", "meeting_id": "...", "runner_session_id": "...", "agent_role": "..."}
    """
    return {
        "request_id": _request_id.get(),
        "meeting_id": _meeting_id.get(),
        "runner_session_id": _runner_session_id.get(),
        "agent_role": _agent_role.get(),
    }
