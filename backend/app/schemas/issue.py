# 议题相关 DTO + VO（ADR-017 Phase 2）
from __future__ import annotations

from pydantic import BaseModel, Field

# 合法状态（状态机流转由服务层校验，见 services/issue_service.py）
# conflict：ADR-017 D11 合入 main 冲突态，交回用户处置
ISSUE_STATUS_VALUES = ("open", "scheduled", "in_progress", "conflict", "resolved", "wontfix")


class CreateIssueRequest(BaseModel):
    """创建议题请求（ADR-017 D7 两条入口）"""

    title: str = Field(..., min_length=1, max_length=500, description="议题标题")
    body: str | None = Field(None, description="议题详情")
    source: str = Field("user", pattern=r"^(user|meeting)$", description="入口：user 手动 | meeting 会议候选经确认")
    source_meeting_id: str | None = Field(None, max_length=36, description="提出该议题的会议（source=meeting 时必填）")
    priority: int = Field(50, ge=0, le=100, description="优先级 0-100，默认 50")


class UpdateIssueRequest(BaseModel):
    """更新议题请求（字段均可选，只更新传入项）

    - 传 status 时走状态机校验（非法流转返回 409）；
    - 流转到 resolved 必须提供 resolution_artifact_id（或议题已挂）。
    """

    title: str | None = Field(None, min_length=1, max_length=500)
    body: str | None = None
    priority: int | None = Field(None, ge=0, le=100)
    status: str | None = Field(None, description="目标状态（走状态机校验）")
    resolution_artifact_id: str | None = Field(None, max_length=36, description="闭环凭证产物 ID")


class IssueResponse(BaseModel):
    """单条议题"""

    id: str
    tenant_id: int | None = None
    project_id: str
    title: str
    body: str | None = None
    source: str
    source_meeting_id: str | None = None
    status: str = "open"
    priority: int = 50
    assigned_meeting_id: str | None = None
    resolution_artifact_id: str | None = None
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class IssueListResponse(BaseModel):
    """议题分页列表（最新在上）"""

    items: list[IssueResponse]
    total: int


class MergeIssueRequest(BaseModel):
    """议题合入 main 请求（ADR-017 D11，两阶段确认，同 D8 push 护栏哲学）

    - ``confirm=False``（默认）：仅预览——干跑合入并返回 diff 摘要/冲突清单，
      不改变任何状态；
    - ``confirm=True``：正式合入共享克隆 ``default_branch`` 并 push（进入共享
      空间的不可逆操作，必须以显式确认触发）。
    """

    confirm: bool = Field(False, description="false=仅预览（干跑，不落状态）；true=正式合入并推送")
