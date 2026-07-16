"""领域模型包：统一 re-export 全部 20 个领域类。

支持 `from app.domain import MeetingState` 等便捷导入。
具体定义分布在 4 个子模块中：
- enums: 枚举类型
- message: 发言/证据/决策模型
- meeting: 会议核心模型
- agent_role: 角色模型
"""
from __future__ import annotations

from app.domain.enums import (
    Role,
    ClaimType,
    ConflictType,
    Stage,
    MeetingStatus,
)
from app.domain.message import (
    Message,
    Claim,
    Conflict,
    Evidence,
    EvidenceAssessment,
    Decision,
    DecisionRecord,
    EvidenceSet,
)
from app.domain.meeting import (
    PRD,
    Artifact,
    Meeting,
    BorrowRequest,
    MeetingState,
)
from app.domain.agent_role import (
    AgentRole,
    AgentRoleListResponse,
)

__all__ = [
    # enums
    "Role",
    "ClaimType",
    "ConflictType",
    "Stage",
    "MeetingStatus",
    # message
    "Message",
    "Claim",
    "Conflict",
    "Evidence",
    "EvidenceAssessment",
    "Decision",
    "DecisionRecord",
    "EvidenceSet",
    # meeting
    "PRD",
    "Artifact",
    "Meeting",
    "BorrowRequest",
    "MeetingState",
    # agent_role
    "AgentRole",
    "AgentRoleListResponse",
]
