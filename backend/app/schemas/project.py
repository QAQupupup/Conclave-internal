# 项目相关 DTO + VO（ADR-017 Phase 2）
from __future__ import annotations

from pydantic import BaseModel, Field

# slug 规范：小写字母开头，仅含小写字母/数字/-/_（人类可读 namespace 标识）
SLUG_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,99}$"


class CreateProjectRequest(BaseModel):
    """创建项目请求"""

    slug: str = Field(..., pattern=SLUG_PATTERN, description="namespace 标识，租户内唯一，可后续改名")
    name: str = Field(..., min_length=1, max_length=200, description="项目显示名")
    repo_url: str | None = Field(None, max_length=500, description="绑定仓库（可空：纯文档型项目）")
    default_branch: str = Field("main", max_length=200, description="默认分支")
    description: str | None = Field(None, description="项目描述")


class UpdateProjectRequest(BaseModel):
    """更新项目请求（字段均可选，只更新传入项）"""

    slug: str | None = Field(None, pattern=SLUG_PATTERN)
    name: str | None = Field(None, min_length=1, max_length=200)
    repo_url: str | None = Field(None, max_length=500)
    default_branch: str | None = Field(None, max_length=200)
    description: str | None = None


class ProjectResponse(BaseModel):
    """单个项目"""

    id: str
    tenant_id: int | None = None
    slug: str
    name: str
    repo_url: str | None = None
    default_branch: str = "main"
    description: str | None = None
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    # 列表页附带的议题总数（详情接口返回 issue_stats 分组统计）
    issue_total: int | None = None


class ProjectListResponse(BaseModel):
    """项目分页列表（最新在上）"""

    items: list[ProjectResponse]
    total: int


class ProjectDetailResponse(ProjectResponse):
    """项目详情（含议题状态分组统计）"""

    # {"total": N, "open": n1, "in_progress": n2, ...}
    issue_stats: dict[str, int] = Field(default_factory=dict)
