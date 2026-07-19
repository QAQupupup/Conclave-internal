"""领域模型包：统一 re-export 全部 20 个领域类。

支持 `from app.domain import MeetingState` 等便捷导入。
具体定义分布在 4 个子模块中：
- enums: 枚举类型
- message: 发言/证据/决策模型
- meeting: 会议核心模型
- agent_role: 角色模型
"""

from __future__ import annotations

from app.domain.agent_role import (
    AgentRole,
    AgentRoleListResponse,
)
from app.domain.enums import (
    ClaimType,
    ConflictType,
    MeetingStatus,
    Role,
    Stage,
)
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
    # meeting
    "PRD",
    # agent_role
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
    # message
    "Message",
    # enums
    "Role",
    "Stage",
]
