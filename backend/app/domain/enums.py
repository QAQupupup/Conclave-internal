"""领域枚举类型：会议角色、论点类型、冲突类型、状态机阶段、会议运行状态。

从 app/models.py 迁移而来，原样保留，仅调整文件位置。
"""
from __future__ import annotations

from enum import Enum


# ---------- 枚举 ----------

class Role(str, Enum):
    """会议角色"""
    MODERATOR = "moderator"
    PRODUCT_ARCHITECT = "product_architect"
    ENGINEER = "engineer"
    SECURITY_EXPERT = "security_expert"
    DATA_ENGINEER = "data_engineer"
    UX_DESIGNER = "ux_designer"
    MARKETING_EXPERT = "marketing_expert"


class ClaimType(str, Enum):
    """论点类型"""
    FACT = "fact"
    ASSUMPTION = "assumption"
    CONSTRAINT = "constraint"


class ConflictType(str, Enum):
    """冲突类型"""
    FACTUAL = "factual"
    PREFERENCE = "preference"
    SCOPE = "scope"


class Stage(str, Enum):
    """状态机六阶段"""
    CLARIFY = "clarify"
    INTRA_TEAM = "intra_team"
    CROSS_TEAM = "cross_team"
    EVIDENCE_CHECK = "evidence_check"
    ARBITRATE = "arbitrate"
    PRODUCE = "produce"


class MeetingStatus(str, Enum):
    """会议运行状态"""
    RUNNING = "running"
    PAUSED = "paused"
    ABORTED = "aborted"
    DONE = "done"
    FAILED = "failed"  # [AUDIT-FIX P0-2/P0-4] 新增：节点异常或超时时的终态
