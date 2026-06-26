# §2.2 三层记忆数据模型
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class MemoryLayer(str, Enum):
    """记忆层级"""
    RAW = "raw"           # 原始发言（不可变）
    FEATURE = "feature"   # 行为特征（提炼产出）
    PROFILE = "profile"   # 稳定画像（反哺初始化）


class RawMemory(BaseModel):
    """原始发言记录：迭代一已有 SQLite 留底，此处正式建模

    会议结束后从 state.messages 提取，作为特征提炼的原料。
    """
    id: str
    agent_role: str
    meeting_id: str
    stage: str
    content: str
    evidence_refs: list[str] = Field(default_factory=list)
    adopted: bool = False              # 是否被裁决采纳
    corrected_by: str | None = None    # 是否被后续纠正
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FeatureMemory(BaseModel):
    """行为特征：从多次原始发言中 LLM 提炼

    feature_type 取值：stance_style | evidence_dependency | risk_appetite | collaboration
    """
    id: str
    agent_role: str
    feature_type: str          # stance_style | evidence_dependency | risk_appetite | collaboration
    feature_value: str         # "conservative" | "aggressive" | "evidence_heavy" | ...
    confidence: float          # 0-1，基于样本量
    sample_count: int          # 提炼自多少条原始记录
    source_meeting_ids: list[str] = Field(default_factory=list)
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProfileMemory(BaseModel):
    """稳定画像：少量高价值配置项，反哺下次会议初始化

    默认值对齐迭代一行为（balanced / medium / collaborative），
    仅在历史特征沉淀后才注入 agent prompt。
    """
    agent_role: str
    default_stance_style: str = "balanced"       # "conservative" | "balanced" | "aggressive"
    ambiguity_tolerance: float = 0.5             # 0-1
    evidence_dependency_level: str = "medium"    # "low" | "medium" | "high"
    collaboration_preference: str = "collaborative"   # "independent" | "collaborative" | "bridging"
    escalation_threshold: float = 0.6           # 0-1，何时倾向升级/借调
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = 1                             # 乐观锁，version=1 表示默认未更新
