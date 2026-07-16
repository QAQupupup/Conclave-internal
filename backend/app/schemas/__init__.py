# DTO + VO 层：请求/响应数据模型
# 从 routers/ 内嵌的 Pydantic 模型提取，按业务域分文件
# __init__.py 做 re-export，保证 from app.schemas import XxxDTO 可用

from app.schemas.meeting import (
    CreateMeetingRequest,
    CreateMeetingResponse,
    ControlRequest,
    RunResponse,
    BatchDeleteRequest,
    AddTagRequest,
    InjectReferenceRequest,
    InterventionRequest,
    SetModelRequest,
    SaveApiKeyRequest,
)
from app.schemas.auth import LoginRequest, LoginResponse, MeResponse
from app.schemas.agent_role import (
    CreateRoleRequest,
    GenerateRolesRequest,
    GenerateRolesResponse,
    UpsertRoleResponse,
)
from app.schemas.regression import BaselineRequest, BaselineSummary
from app.schemas.captcha import GuardModeRequest, ResolveRequest
from app.schemas.net_auth import ReviewRequest, AuthRequestSummary
from app.schemas.preferences import PreferenceValue
from app.schemas.workspace import FileWriteRequest, CodeRunRequest, CommandRequest
from app.schemas.common import ApiResponse, PaginatedResponse

__all__ = [
    # meeting
    "CreateMeetingRequest", "CreateMeetingResponse", "ControlRequest",
    "RunResponse", "BatchDeleteRequest", "AddTagRequest",
    "InjectReferenceRequest", "InterventionRequest",
    "SetModelRequest", "SaveApiKeyRequest",
    # auth
    "LoginRequest", "LoginResponse", "MeResponse",
    # agent_role
    "CreateRoleRequest", "GenerateRolesRequest", "GenerateRolesResponse", "UpsertRoleResponse",
    # regression
    "BaselineRequest", "BaselineSummary",
    # captcha
    "GuardModeRequest", "ResolveRequest",
    # net_auth
    "ReviewRequest", "AuthRequestSummary",
    # preferences
    "PreferenceValue",
    # workspace
    "FileWriteRequest", "CodeRunRequest", "CommandRequest",
    # common
    "ApiResponse", "PaginatedResponse",
]
