"""插件系统异常类（从 app.core.exceptions 重新导出，保持向后兼容）。"""

from __future__ import annotations

from typing import Any

from app.core.exceptions import (
    AccessDeniedError,
    AlreadyExistsError,
    AppException,
    BadRequestError,
    ConflictError,
    ErrorCode,
    InvalidCredentialsError,
    NotFoundError,
    PluginDependencyError,
    PluginLoadError,
    PluginRejected,
    QuotaExceededError,
    SetupRequired,
    UnauthenticatedError,
    ValidationError,
)


class ConclaveException(AppException):
    """向后兼容：原插件异常基类，默认 code=PLUGIN_ERROR。

    新代码应直接使用 AppException 或其子类。
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "PLUGIN_ERROR",
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code, details=details)


# 向后兼容别名
QuotaExceeded = QuotaExceededError
AccessDenied = AccessDeniedError

__all__ = [
    "AccessDenied",
    "AccessDeniedError",
    "AlreadyExistsError",
    "AppException",
    "BadRequestError",
    "ConclaveException",
    "ConflictError",
    "ErrorCode",
    "InvalidCredentialsError",
    "NotFoundError",
    "PluginDependencyError",
    "PluginLoadError",
    "PluginRejected",
    "QuotaExceeded",
    "QuotaExceededError",
    "SetupRequired",
    "UnauthenticatedError",
    "ValidationError",
]
