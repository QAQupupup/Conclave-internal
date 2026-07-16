# Agent 角色相关 DTO + VO
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models import AgentRole


class CreateRoleRequest(BaseModel):
    """创建/更新角色请求"""
    id: str = Field(..., description="英文标识，如 fullstack_engineer")
    display_name: str = Field(..., description="中文名")
    perspective: str = Field("", description="核心视角")
    expertise_domains: list[str] = Field(default_factory=list)
    risk_appetite: str = Field("balanced", description="conservative | balanced | aggressive")
    default_stance: str = Field("")
    evidence_preference: str = Field("balanced")
    model_override: str = Field("")
    background_brief: str = Field("")
    prompt_template: str = Field("")


class GenerateRolesRequest(BaseModel):
    """议题驱动生成角色请求"""
    topic: str = Field(..., description="会议议题")


class GenerateRolesResponse(BaseModel):
    """生成角色响应"""
    roles: list[AgentRole]
    generated_at: str


class UpsertRoleResponse(BaseModel):
    """单个角色 upsert 响应"""
    role: AgentRole
