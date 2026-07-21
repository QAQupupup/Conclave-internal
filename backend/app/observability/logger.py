"""统一日志门面。

目的：
- 消除项目中 `logging.getLogger(__name__)` / `log_bus.xxx()` / `audit()` 三种日志写法的分歧；
- 自动注入 contextvars（request_id / meeting_id / tenant_id / user_id / agent_role）到 extra；
- 提供统一的结构化字段约定：extra 中的字段自动透传到 log_bus（warning/error 级自动旁路）。

用法：
    from app.observability.logger import get_logger
    logger = get_logger(__name__)
    logger.info("阶段完成", extra={"stage": "clarify", "duration_ms": 123})
    logger.warning("LLM 调用失败", extra={"provider": "siliconflow", "attempt": 2})

注意：
- 不强制替换所有现有 logging.getLogger 调用，仅用于新代码和关键路径；
- 审计事件（auth/权限/敏感操作）仍走 app.observability.audit，不合并到这里。
"""
from __future__ import annotations

import logging
from typing import Any, MutableMapping

# 日志 -> log_bus 的最低级别（warning 及以上自动旁路）
_BUS_MIN_LEVEL = logging.WARNING


def _context_extras() -> dict[str, Any]:
    """从 contextvars 提取公共上下文字段（不抛异常，失败时返回空 dict）。"""
    out: dict[str, Any] = {}
    try:
        from app.context import (
            get_meeting_id,
            get_request_id,
            get_user_id,
            get_agent_role,
            get_runner_session_id,
        )

        rid = get_request_id()
        if rid and rid != "-":
            out["request_id"] = rid
        mid = get_meeting_id()
        if mid and mid != "-":
            out["meeting_id"] = mid
        uid = get_user_id()
        if uid and uid != "-":
            out["user_id"] = uid
        role = get_agent_role()
        if role:
            out["agent_role"] = role
        rsid = get_runner_session_id()
        if rsid and rsid != "-":
            out["runner_session_id"] = rsid
    except Exception:
        pass
    try:
        from app.tenants.context import get_tenant_id

        tid = get_tenant_id()
        if tid is not None:
            out["tenant_id"] = tid
    except Exception:
        pass
    return out


class _ContextLogger(logging.LoggerAdapter):
    """自动注入 contextvars extra 的 Logger 适配器。"""

    def __init__(self, logger: logging.Logger, extra: dict[str, Any]) -> None:
        super().__init__(logger, extra)
        self.name = logger.name

    def process(self, msg: str, kwargs: MutableMapping[str, Any]) -> tuple[str, MutableMapping[str, Any]]:
        base_extra = dict(self.extra or {}) if self.extra else {}
        base_extra.update(_context_extras())
        existing = kwargs.get("extra")
        if existing:
            # kwargs.extra 优先级最高
            merged = {**base_extra, **existing}
        else:
            merged = base_extra
        kwargs["extra"] = merged
        return msg, kwargs

    def log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        # 旁路到 log_bus（warning/error 及以上）
        if level >= _BUS_MIN_LEVEL:
            try:
                from app.observability.log_bus import log_bus

                extra = dict(kwargs.get("extra") or {})
                if self.name:
                    extra.setdefault("logger", self.name)
                if level >= logging.ERROR:
                    log_bus.error(msg, extra=extra)
                elif level >= logging.WARNING:
                    log_bus.warning(msg, extra=extra)
            except Exception:
                pass
        return super().log(level, msg, *args, **kwargs)


_loggers: dict[str, _ContextLogger] = {}


def get_logger(name: str) -> _ContextLogger:
    """获取带上下文自动注入的 logger。幂等缓存。"""
    if name in _loggers:
        return _loggers[name]
    base = logging.getLogger(name)
    adapter = _ContextLogger(base, extra={})
    _loggers[name] = adapter
    return adapter
