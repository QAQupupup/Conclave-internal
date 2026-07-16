"""Agent 角色模型：AgentRole, AgentRoleListResponse。

从 app/models.py 迁移而来，原样保留，仅调整文件位置。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------- Agent 角色模型 ----------

class AgentRole(BaseModel):
    """Agent 角色定义：可从数据库加载、API 返回、LLM 生成"""
    id: str                                    # 英文标识，如 "fullstack_engineer"
    display_name: str                          # 中文名
    perspective: str = ""                      # 核心视角
    expertise_domains: list[str] = Field(default_factory=list)
    risk_appetite: str = "balanced"            # conservative | balanced | aggressive
    default_stance: str = ""                   # 默认立场
    evidence_preference: str = "balanced"      # 证据偏好
    model_override: str = ""                   # 留空则用全局 LLM
    background_brief: str = ""                 # 一句话背景
    prompt_template: str = ""                  # 完整 prompt 模板
    is_builtin: bool = False
    is_active: bool = True
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "AgentRole":
        return cls(
            id=row["id"],
            display_name=row["display_name"],
            perspective=row.get("perspective", ""),
            expertise_domains=row.get("expertise_domains", []),
            risk_appetite=row.get("risk_appetite", "balanced"),
            default_stance=row.get("default_stance", ""),
            evidence_preference=row.get("evidence_preference", "balanced"),
            model_override=row.get("model_override", ""),
            background_brief=row.get("background_brief", ""),
            prompt_template=row.get("prompt_template", ""),
            is_builtin=bool(row.get("is_builtin", False)),
            is_active=bool(row.get("is_active", True)),
            created_at=row.get("created_at", ""),
            updated_at=row.get("updated_at", ""),
        )


class AgentRoleListResponse(BaseModel):
    """角色列表响应"""
    roles: list[AgentRole]
    total: int
