"""统一应用异常体系。

所有业务异常继承 AppException，包含：
- code: 机器可读错误码（ErrorCode 枚举字符串）
- message: 人类可读错误信息（中文）
- status_code: HTTP 状态码
- details: 附加结构化信息

全局异常处理器捕获 AppException 后返回统一 JSON 格式：
{"error": {"code": "...", "message": "...", "details": {...}}}
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    """错误码枚举。按领域分组，code 格式: DOMAIN_SPECIFIC_ERROR。"""

    # 通用 (1xxx)
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    BAD_REQUEST = "BAD_REQUEST"
    CONFLICT = "CONFLICT"

    # 认证授权 (2xxx)
    UNAUTHENTICATED = "UNAUTHENTICATED"
    ACCESS_DENIED = "ACCESS_DENIED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    SETUP_REQUIRED = "SETUP_REQUIRED"
    CSRF_INVALID = "CSRF_INVALID"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"

    # 会议/业务 (3xxx)
    MEETING_NOT_FOUND = "MEETING_NOT_FOUND"
    MEETING_ALREADY_RUNNING = "MEETING_ALREADY_RUNNING"
    MEETING_NOT_RUNNING = "MEETING_NOT_RUNNING"
    MEETING_ACCESS_DENIED = "MEETING_ACCESS_DENIED"
    STAGE_INVALID = "STAGE_INVALID"
    CONTROL_SIGNAL_REJECTED = "CONTROL_SIGNAL_REJECTED"

    # 沙箱/执行 (4xxx)
    SANDBOX_UNAVAILABLE = "SANDBOX_UNAVAILABLE"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    EXECUTION_TIMEOUT = "EXECUTION_TIMEOUT"
    NETWORK_DENIED = "NETWORK_DENIED"
    DANGEROUS_COMMAND = "DANGEROUS_COMMAND"

    # LLM/外部服务 (5xxx)
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    LLM_RATE_LIMITED = "LLM_RATE_LIMITED"
    LLM_RESPONSE_INVALID = "LLM_RESPONSE_INVALID"
    EMBEDDING_FAILED = "EMBEDDING_FAILED"
    RERANK_FAILED = "RERANK_FAILED"

    # 插件 (6xxx)
    PLUGIN_ERROR = "PLUGIN_ERROR"
    PLUGIN_REJECTED = "PLUGIN_REJECTED"
    PLUGIN_DEPENDENCY_ERROR = "PLUGIN_DEPENDENCY_ERROR"
    PLUGIN_LOAD_ERROR = "PLUGIN_LOAD_ERROR"

    # 租户 (7xxx)
    TENANT_NOT_FOUND = "TENANT_NOT_FOUND"
    TENANT_SLUG_EXISTS = "TENANT_SLUG_EXISTS"
    TENANT_MEMBER_EXISTS = "TENANT_MEMBER_EXISTS"
    TENANT_MEMBER_NOT_FOUND = "TENANT_MEMBER_NOT_FOUND"

    # 资源 (8xxx)
    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
    DOCUMENT_TOO_LARGE = "DOCUMENT_TOO_LARGE"
    API_KEY_NOT_FOUND = "API_KEY_NOT_FOUND"
    API_KEY_INVALID = "API_KEY_INVALID"
    DOCKER_HOST_NOT_FOUND = "DOCKER_HOST_NOT_FOUND"
    NET_AUTH_PENDING = "NET_AUTH_PENDING"
    NET_AUTH_DENIED = "NET_AUTH_DENIED"


class AppException(Exception):
    """应用异常基类。所有业务异常应继承此类。"""

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode | str = ErrorCode.UNKNOWN_ERROR,
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code.value if isinstance(code, ErrorCode) else code
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


# ============================================================
# 通用异常
# ============================================================


class ValidationError(AppException):
    def __init__(self, message: str = "请求参数验证失败", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code=ErrorCode.VALIDATION_ERROR, status_code=422, details=details)


class NotFoundError(AppException):
    def __init__(self, message: str = "资源不存在", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code=ErrorCode.NOT_FOUND, status_code=404, details=details)


class AlreadyExistsError(AppException):
    def __init__(self, message: str = "资源已存在", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code=ErrorCode.ALREADY_EXISTS, status_code=409, details=details)


class ConflictError(AppException):
    def __init__(self, message: str = "资源状态冲突", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code=ErrorCode.CONFLICT, status_code=409, details=details)


class BadRequestError(AppException):
    def __init__(self, message: str = "请求参数错误", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code=ErrorCode.BAD_REQUEST, status_code=400, details=details)


# ============================================================
# 认证授权异常
# ============================================================


class UnauthenticatedError(AppException):
    def __init__(self, message: str = "未认证，请先登录", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code=ErrorCode.UNAUTHENTICATED, status_code=401, details=details)


class AccessDeniedError(AppException):
    def __init__(self, message: str = "访问被拒绝", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code=ErrorCode.ACCESS_DENIED, status_code=403, details=details)


class InvalidCredentialsError(AppException):
    def __init__(self, message: str = "用户名或密码错误", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code=ErrorCode.INVALID_CREDENTIALS, status_code=401, details=details)


class QuotaExceededError(AppException):
    def __init__(self, message: str = "配额已耗尽", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code=ErrorCode.QUOTA_EXCEEDED, status_code=429, details=details)


# ============================================================
# 插件异常（向后兼容：继承 AppException）
# ============================================================


class PluginRejected(AppException):
    def __init__(self, message: str = "操作被插件拒绝", details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code=ErrorCode.PLUGIN_REJECTED, status_code=403, details=details)


class SetupRequired(AppException):
    def __init__(self, message: str = "系统尚未初始化，请先完成设置") -> None:
        super().__init__(message, code=ErrorCode.SETUP_REQUIRED, status_code=403)


class PluginDependencyError(AppException):
    def __init__(self, message: str) -> None:
        super().__init__(message, code=ErrorCode.PLUGIN_DEPENDENCY_ERROR, status_code=500)


class PluginLoadError(AppException):
    def __init__(self, plugin_name: str, reason: str) -> None:
        super().__init__(
            f"插件 {plugin_name} 加载失败: {reason}",
            code=ErrorCode.PLUGIN_LOAD_ERROR,
            status_code=500,
            details={"plugin_name": plugin_name, "reason": reason},
        )
