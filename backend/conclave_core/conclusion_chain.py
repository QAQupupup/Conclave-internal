# 第2层：结论锁定链 —— 记录每阶段锁定结论，供后续引用和一致性校验
# 对 stub 和 real 路径都生效，保证两条路径行为一致
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ConsistencyResult(BaseModel):
    """一致性检查结果"""

    is_consistent: bool
    violations: list[str] = Field(default_factory=list)


class LockedConclusion(BaseModel):
    """一个被锁定的阶段结论"""

    conclusion_id: str  # 如 "locked-clarify-abc123"
    stage: str  # 来源阶段
    content: dict[str, Any]  # 结论内容（阶段输出 dict）
    content_hash: str  # 内容 hash（sha256 前12位），用于后续校验引用
    locked_at: str  # ISO 时间


class ConclusionChain(BaseModel):
    """结论锁定链：记录每阶段锁定结论，供后续引用和一致性校验"""

    meeting_id: str = ""
    conclusions: list[LockedConclusion] = Field(default_factory=list)
