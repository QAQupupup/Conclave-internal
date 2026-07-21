# DTO + VO 层：请求/响应数据模型
# 从 routers/ 内嵌的 Pydantic 模型提取，按业务域分文件
# __init__.py 做 re-export，保证 from app.schemas import XxxDTO 可用

from app.schemas.agent_role import (
    CreateRoleRequest,
    GenerateRolesRequest,
    GenerateRolesResponse,
    UpsertRoleResponse,
)
from app.schemas.auth import LoginRequest, LoginResponse, MeResponse
from app.schemas.captcha import GuardModeRequest, ResolveRequest
from app.schemas.common import ApiResponse, PaginatedResponse
from app.schemas.meeting import (
    AddTagRequest,
    BatchDeleteRequest,
    ControlRequest,
    CreateMeetingRequest,
    CreateMeetingResponse,
    InjectReferenceRequest,
    InterventionRequest,
    RunResponse,
    SaveApiKeyRequest,
    SetModelRequest,
)
from app.schemas.net_auth import AuthRequestSummary, ReviewRequest
from app.schemas.preferences import PreferenceValue
from app.schemas.regression import BaselineRequest, BaselineSummary
from app.schemas.workspace import CodeRunRequest, CommandRequest, FileWriteRequest

__all__ = [
    "AddTagRequest",
    # common
    "ApiResponse",
    "AuthRequestSummary",
    # regression
    "BaselineRequest",
    "BaselineSummary",
    "BatchDeleteRequest",
    "CodeRunRequest",
    "CommandRequest",
    "ControlRequest",
    # meeting
    "CreateMeetingRequest",
    "CreateMeetingResponse",
    # agent_role
    "CreateRoleRequest",
    # workspace
    "FileWriteRequest",
    "GenerateRolesRequest",
    "GenerateRolesResponse",
    # captcha
    "GuardModeRequest",
    "InjectReferenceRequest",
    "InterventionRequest",
    # auth
    "LoginRequest",
    "LoginResponse",
    "MeResponse",
    "PaginatedResponse",
    # preferences
    "PreferenceValue",
    "ResolveRequest",
    # net_auth
    "ReviewRequest",
    "RunResponse",
    "SaveApiKeyRequest",
    "SetModelRequest",
    "UpsertRoleResponse",
]
