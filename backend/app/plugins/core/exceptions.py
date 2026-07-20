"""插件系统异常类。

P1b 阶段填充具体异常子类；Phase 0 仅提供基类。
"""
from __future__ import annotations

from typing import Any


class ConclaveException(Exception):
    """插件系统异常基类。所有插件抛出的异常应继承此类。"""

    def __init__(
        self,
        message: str,
        *,
        code: str = "PLUGIN_ERROR",
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class PluginRejected(ConclaveException):
    """插件拦截器主动拒绝操作（通用拒绝，Fallback 语义）。"""

    def __init__(
        self,
        message: str,
        *,
        code: str = "PLUGIN_REJECTED",
        status_code: int = 403,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code, details=details)


class SetupRequired(ConclaveException):
    """系统尚未完成初始化 setup（无管理员账户）。"""

    def __init__(self, message: str = "系统尚未初始化，请先完成 setup") -> None:
        super().__init__(message, code="SETUP_REQUIRED", status_code=403)


class QuotaExceeded(ConclaveException):
    """配额耗尽。"""

    def __init__(self, message: str = "配额已耗尽") -> None:
        super().__init__(message, code="QUOTA_EXCEEDED", status_code=429)


class AccessDenied(ConclaveException):
    """访问被拒绝（权限不足）。"""

    def __init__(self, message: str = "访问被拒绝") -> None:
        super().__init__(message, code="ACCESS_DENIED", status_code=403)


class PluginDependencyError(ConclaveException):
    """插件依赖解析失败（循环依赖、硬依赖缺失等）。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="PLUGIN_DEPENDENCY_ERROR", status_code=500)


class PluginLoadError(ConclaveException):
    """插件加载失败。"""

    def __init__(self, plugin_name: str, reason: str) -> None:
        super().__init__(
            f"插件 {plugin_name} 加载失败: {reason}",
            code="PLUGIN_LOAD_ERROR",
            status_code=500,
            details={"plugin_name": plugin_name, "reason": reason},
        )
