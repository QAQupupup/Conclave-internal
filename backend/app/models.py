"""兼容 shim：所有领域模型已迁移到 app.domain 子模块。

保留此文件是为了向后兼容 `from app.models import xxx` 的调用。
新代码应直接使用 `from app.domain import xxx`。
"""

from __future__ import annotations

from app.domain.agent_role import AgentRole, AgentRoleListResponse
from app.domain.enums import ClaimType, ConflictType, MeetingStatus, Role, Stage
from app.domain.meeting import (
    PRD,
    Artifact,
    BorrowRequest,
    Meeting,
    MeetingState,
)
from app.domain.message import (
    Claim,
    Conflict,
    Decision,
    DecisionRecord,
    Evidence,
    EvidenceAssessment,
    EvidenceSet,
    Message,
)

__all__ = [
    "PRD",
    "AgentRole",
    "AgentRoleListResponse",
    "Artifact",
    "BorrowRequest",
    "Claim",
    "ClaimType",
    "Conflict",
    "ConflictType",
    "Decision",
    "DecisionRecord",
    "Evidence",
    "EvidenceAssessment",
    "EvidenceSet",
    "Meeting",
    "MeetingState",
    "MeetingStatus",
    "Message",
    "Role",
    "Stage",
]
