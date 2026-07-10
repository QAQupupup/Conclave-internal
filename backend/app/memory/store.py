# §2.3 三层记忆存储：进程内单例 + SQLite 持久化层
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.memory.models import FeatureMemory, ProfileMemory, RawMemory

logger = logging.getLogger(__name__)

# [CON-25 修复] 记忆子系统持久化路径
# 默认 <workspace_root>/memory.db（与业务库分离，独立备份）
# env: CONCLAVE_MEMORY_DB_PATH 覆盖
_MEMORY_DB_PATH = os.environ.get(
    "CONCLAVE_MEMORY_DB_PATH",
    str(Path(settings.workspace_root) / "memory.db"),
)
_MEMORY_LOCK = threading.Lock()

# StubLLM 模式规则提炼用的关键词表
# 风险关键词：用于判断 risk_appetite / stance_style
_RISK_HIGH_KEYWORDS: list[str] = [
    "高风险", "危险", "风险", "不可行", "阻塞", "严重", "critical", "high risk",
    "隐患", "漏洞", "威胁",
]
_RISK_LOW_KEYWORDS: list[str] = [
    "低风险", "安全", "可控", "可行", "稳健", "low risk", "无忧", "成熟",
]
# 协作关键词：用于判断 collaboration
_COLLAB_KEYWORDS: list[str] = [
    "建议", "补充", "同意", "认可", "协作", "配合", "协商", "折中", "共识",
]


class MemoryStore:
    """三层记忆存储（进程内单例）

    - _raw: dict[agent_role, list[RawMemory]]  原始发言
    - _features: dict[agent_role, list[FeatureMemory]]  行为特征
    - _profiles: dict[agent_role, ProfileMemory]  稳定画像

    所有方法包在 try/except 中，失败不抛异常只记 log，确保记忆子系统
    的任何异常都不影响主会议流程。
    """

    def __init__(self) -> None:
        self._raw: dict[str, list[RawMemory]] = {}
        self._features: dict[str, list[FeatureMemory]] = {}
        self._profiles: dict[str, ProfileMemory] = {}
        # [CON-25 修复] 启动时从 SQLite 恢复所有持久化记忆
        # 旧版纯内存，重启即丢。改为：
        #   1) 启动时加载：把上一轮沉淀的画像 + 特征 + 原始发言恢复进内存
        #   2) 写入时持久化：每次 update 同步落盘
        #   3) 用独立 sqlite 文件（<workspace_root>/memory.db）便于备份/恢复
        self._init_persistence()
        self._load_from_db()

    def _init_persistence(self) -> None:
        """初始化记忆 SQLite 表结构"""
        try:
            Path(_MEMORY_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
            with _MEMORY_LOCK, sqlite3.connect(_MEMORY_DB_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS raw_memories (
                        id TEXT PRIMARY KEY,
                        agent_role TEXT NOT NULL,
                        meeting_id TEXT NOT NULL,
                        stage TEXT,
                        content TEXT,
                        evidence_refs TEXT,
                        adopted INTEGER,
                        corrected_by TEXT,
                        created_at TEXT
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS feature_memories (
                        id TEXT PRIMARY KEY,
                        agent_role TEXT NOT NULL,
                        feature_type TEXT,
                        feature_value TEXT,
                        confidence REAL,
                        sample_count INTEGER,
                        source_meeting_ids TEXT,
                        extracted_at TEXT
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS profile_memories (
                        agent_role TEXT PRIMARY KEY,
                        default_stance_style TEXT,
                        ambiguity_tolerance REAL,
                        evidence_dependency_level TEXT,
                        collaboration_preference TEXT,
                        escalation_threshold REAL,
                        updated_at TEXT,
                        version INTEGER
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_agent ON raw_memories(agent_role)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_feat_agent ON feature_memories(agent_role)")
        except Exception as e:  # noqa: BLE001
            logger.warning("记忆持久化初始化失败（不影响运行）: %s", e)

    def _load_from_db(self) -> None:
        """启动时从 SQLite 恢复所有记忆"""
        try:
            with _MEMORY_LOCK, sqlite3.connect(_MEMORY_DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                # 画像
                for row in conn.execute("SELECT * FROM profile_memories"):
                    self._profiles[row["agent_role"]] = ProfileMemory(
                        agent_role=row["agent_role"],
                        default_stance_style=row["default_stance_style"] or "balanced",
                        ambiguity_tolerance=row["ambiguity_tolerance"] or 0.5,
                        evidence_dependency_level=row["evidence_dependency_level"] or "medium",
                        collaboration_preference=row["collaboration_preference"] or "collaborative",
                        escalation_threshold=row["escalation_threshold"] or 0.6,
                        updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else datetime.now(timezone.utc),
                        version=row["version"] or 1,
                    )
                # 行为特征
                for row in conn.execute("SELECT * FROM feature_memories"):
                    fm = FeatureMemory(
                        id=row["id"],
                        agent_role=row["agent_role"],
                        feature_type=row["feature_type"] or "",
                        feature_value=row["feature_value"] or "",
                        confidence=row["confidence"] or 0.0,
                        sample_count=row["sample_count"] or 0,
                        source_meeting_ids=json.loads(row["source_meeting_ids"]) if row["source_meeting_ids"] else [],
                        extracted_at=datetime.fromisoformat(row["extracted_at"]) if row["extracted_at"] else datetime.now(timezone.utc),
                    )
                    self._features.setdefault(fm.agent_role, []).append(fm)
                # 原始发言
                for row in conn.execute("SELECT * FROM raw_memories"):
                    rm = RawMemory(
                        id=row["id"],
                        agent_role=row["agent_role"],
                        meeting_id=row["meeting_id"] or "",
                        stage=row["stage"] or "",
                        content=row["content"] or "",
                        evidence_refs=json.loads(row["evidence_refs"]) if row["evidence_refs"] else [],
                        adopted=bool(row["adopted"]),
                        corrected_by=row["corrected_by"],
                        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(timezone.utc),
                    )
                    self._raw.setdefault(rm.agent_role, []).append(rm)
            if self._profiles:
                logger.info("从 SQLite 恢复 %d 个画像, %d 个特征, %d 条原始发言",
                            len(self._profiles), sum(len(v) for v in self._features.values()),
                            sum(len(v) for v in self._raw.values()))
        except Exception as e:  # noqa: BLE001
            logger.warning("记忆加载失败（使用空内存）: %s", e)

    def _persist_raw(self, mem: RawMemory) -> None:
        """[CON-25] 持久化单条原始记忆"""
        try:
            with _MEMORY_LOCK, sqlite3.connect(_MEMORY_DB_PATH) as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO raw_memories
                       (id, agent_role, meeting_id, stage, content, evidence_refs, adopted, corrected_by, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (mem.id, mem.agent_role, mem.meeting_id, mem.stage, mem.content,
                     json.dumps(mem.evidence_refs or []), int(mem.adopted), mem.corrected_by,
                     mem.created_at.isoformat() if mem.created_at else None),
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("原始记忆持久化失败: %s", e)

    def _persist_features(self, features: list[FeatureMemory]) -> None:
        """[CON-25] 持久化行为特征"""
        try:
            with _MEMORY_LOCK, sqlite3.connect(_MEMORY_DB_PATH) as conn:
                conn.executemany(
                    """INSERT OR REPLACE INTO feature_memories
                       (id, agent_role, feature_type, feature_value, confidence, sample_count, source_meeting_ids, extracted_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    [(f.id, f.agent_role, f.feature_type, f.feature_value, f.confidence,
                      f.sample_count, json.dumps(f.source_meeting_ids or []),
                      f.extracted_at.isoformat() if f.extracted_at else None) for f in features],
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("行为特征持久化失败: %s", e)

    def _persist_profile(self, profile: ProfileMemory) -> None:
        """[CON-25] 持久化画像"""
        try:
            with _MEMORY_LOCK, sqlite3.connect(_MEMORY_DB_PATH) as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO profile_memories
                       (agent_role, default_stance_style, ambiguity_tolerance,
                        evidence_dependency_level, collaboration_preference,
                        escalation_threshold, updated_at, version)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (profile.agent_role, profile.default_stance_style, profile.ambiguity_tolerance,
                     profile.evidence_dependency_level, profile.collaboration_preference,
                     profile.escalation_threshold, profile.updated_at.isoformat() if profile.updated_at else None,
                     profile.version),
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("画像持久化失败: %s", e)

    # ---------- 原始发言层 ----------

    def record_raw(
        self,
        meeting_id: str,
        agent_role: str,
        stage: str,
        content: str,
        evidence_refs: list[str] | None = None,
        adopted: bool = False,
        corrected_by: str | None = None,
    ) -> RawMemory:
        """创建一条 RawMemory 并存入内存"""
        try:
            mem = RawMemory(
                id=f"raw-{uuid.uuid4().hex[:8]}",
                agent_role=agent_role,
                meeting_id=meeting_id,
                stage=stage,
                content=content,
                evidence_refs=evidence_refs or [],
                adopted=adopted,
                corrected_by=corrected_by,
                created_at=datetime.now(timezone.utc),
            )
            self._raw.setdefault(agent_role, []).append(mem)
            # [CON-25] 持久化到 SQLite（异步落盘失败不影响内存）
            self._persist_raw(mem)
            return mem
        except Exception as e:  # noqa: BLE001
            logger.warning("record_raw 失败: %s", e)
            return RawMemory(
                id=f"raw-err-{uuid.uuid4().hex[:6]}",
                agent_role=agent_role,
                meeting_id=meeting_id,
                stage=stage,
                content=content,
                evidence_refs=evidence_refs or [],
                adopted=adopted,
                corrected_by=corrected_by,
            )

    def get_raw(self, agent_role: str) -> list[RawMemory]:
        """查询某角色的全部原始发言"""
        return self._raw.get(agent_role, [])

    # ---------- 行为特征层 ----------

    def extract_features(
        self,
        meeting_id: str,
        agent_role: str,
        messages: list[dict[str, Any]],
        decision_record: dict[str, Any] | None = None,
    ) -> list[FeatureMemory]:
        """从多次原始发言中提炼行为特征

        StubLLM 模式下用简单规则提炼（不调 LLM）：
        - 统计 evidence_refs 出现频率 -> evidence_dependency
        - 统计风险关键词 -> risk_appetite / stance_style
        - 统计协作关键词 -> collaboration
        """
        try:
            if not messages:
                return []
            sample_count = len(messages)
            now = datetime.now(timezone.utc)
            confidence = min(1.0, sample_count / 5.0)

            # 统计各项指标
            evidence_count = 0
            risk_high_count = 0
            risk_low_count = 0
            collab_count = 0
            for m in messages:
                content = str(m.get("content", "")).lower()
                ev_refs = m.get("evidence_refs", []) or []
                evidence_count += len(ev_refs)
                for kw in _RISK_HIGH_KEYWORDS:
                    if kw.lower() in content:
                        risk_high_count += 1
                for kw in _RISK_LOW_KEYWORDS:
                    if kw.lower() in content:
                        risk_low_count += 1
                for kw in _COLLAB_KEYWORDS:
                    if kw in content:
                        collab_count += 1

            features: list[FeatureMemory] = []

            # 1. stance_style：基于风险倾向
            if risk_high_count > risk_low_count:
                stance_value = "conservative"
            elif risk_low_count > risk_high_count:
                stance_value = "aggressive"
            else:
                stance_value = "balanced"
            features.append(FeatureMemory(
                id=f"feat-{uuid.uuid4().hex[:8]}",
                agent_role=agent_role,
                feature_type="stance_style",
                feature_value=stance_value,
                confidence=confidence,
                sample_count=sample_count,
                source_meeting_ids=[meeting_id],
                extracted_at=now,
            ))

            # 2. evidence_dependency：基于证据引用密度
            avg_evidence = evidence_count / max(1, sample_count)
            if avg_evidence >= 1.5:
                ev_value = "high"
            elif avg_evidence >= 0.5:
                ev_value = "medium"
            else:
                ev_value = "low"
            features.append(FeatureMemory(
                id=f"feat-{uuid.uuid4().hex[:8]}",
                agent_role=agent_role,
                feature_type="evidence_dependency",
                feature_value=ev_value,
                confidence=confidence,
                sample_count=sample_count,
                source_meeting_ids=[meeting_id],
                extracted_at=now,
            ))

            # 3. risk_appetite：基于风险关键词分布
            if risk_high_count > sample_count * 0.5:
                risk_value = "conservative"
            elif risk_low_count > sample_count * 0.5:
                risk_value = "aggressive"
            else:
                risk_value = "balanced"
            features.append(FeatureMemory(
                id=f"feat-{uuid.uuid4().hex[:8]}",
                agent_role=agent_role,
                feature_type="risk_appetite",
                feature_value=risk_value,
                confidence=confidence,
                sample_count=sample_count,
                source_meeting_ids=[meeting_id],
                extracted_at=now,
            ))

            # 4. collaboration：基于协作关键词密度
            collab_ratio = collab_count / max(1, sample_count)
            if collab_ratio >= 0.5:
                collab_value = "collaborative"
            elif collab_ratio >= 0.2:
                collab_value = "bridging"
            else:
                collab_value = "independent"
            features.append(FeatureMemory(
                id=f"feat-{uuid.uuid4().hex[:8]}",
                agent_role=agent_role,
                feature_type="collaboration",
                feature_value=collab_value,
                confidence=confidence,
                sample_count=sample_count,
                source_meeting_ids=[meeting_id],
                extracted_at=now,
            ))

            self._features.setdefault(agent_role, []).extend(features)
            # [CON-25] 持久化行为特征
            self._persist_features(features)
            return features
        except Exception as e:  # noqa: BLE001
            logger.warning("extract_features 失败: %s", e)
            return []

    def get_features(self, agent_role: str) -> list[FeatureMemory]:
        """查询某角色的全部行为特征"""
        return self._features.get(agent_role, [])

    # ---------- 稳定画像层 ----------

    def get_or_create_profile(self, agent_role: str) -> ProfileMemory:
        """取或创建默认 ProfileMemory

        默认值对齐迭代一行为：balanced / medium / collaborative。
        """
        try:
            if agent_role in self._profiles:
                return self._profiles[agent_role]
            profile = ProfileMemory(
                agent_role=agent_role,
                default_stance_style="balanced",
                ambiguity_tolerance=0.5,
                evidence_dependency_level="medium",
                collaboration_preference="collaborative",
                escalation_threshold=0.6,
                updated_at=datetime.now(timezone.utc),
                version=1,
            )
            self._profiles[agent_role] = profile
            return profile
        except Exception as e:  # noqa: BLE001
            logger.warning("get_or_create_profile 失败: %s", e)
            return ProfileMemory(agent_role=agent_role)

    def update_profile(self, agent_role: str, features: list[FeatureMemory]) -> ProfileMemory:
        """合并特征到画像（加权平均 confidence）

        只有 confidence 达到阈值的特征才会更新画像字段，
        避免低置信度噪声污染稳定画像。
        """
        try:
            profile = self.get_or_create_profile(agent_role)
            if not features:
                return profile

            # 按 feature_type 取 confidence 最高的特征
            latest: dict[str, FeatureMemory] = {}
            for f in features:
                cur = latest.get(f.feature_type)
                if cur is None or f.confidence > cur.confidence:
                    latest[f.feature_type] = f

            # confidence 阈值：低于此值的特征不更新画像
            conf_threshold = 0.4

            if "stance_style" in latest:
                f = latest["stance_style"]
                if f.confidence >= conf_threshold:
                    profile.default_stance_style = f.feature_value

            if "evidence_dependency" in latest:
                f = latest["evidence_dependency"]
                if f.confidence >= conf_threshold:
                    profile.evidence_dependency_level = f.feature_value

            if "risk_appetite" in latest:
                f = latest["risk_appetite"]
                if f.confidence >= conf_threshold:
                    if f.feature_value == "conservative":
                        profile.ambiguity_tolerance = 0.3
                        profile.escalation_threshold = 0.4
                    elif f.feature_value == "aggressive":
                        profile.ambiguity_tolerance = 0.7
                        profile.escalation_threshold = 0.8
                    else:
                        profile.ambiguity_tolerance = 0.5
                        profile.escalation_threshold = 0.6

            if "collaboration" in latest:
                f = latest["collaboration"]
                if f.confidence >= conf_threshold:
                    profile.collaboration_preference = f.feature_value

            profile.updated_at = datetime.now(timezone.utc)
            profile.version += 1
            self._profiles[agent_role] = profile
            # [CON-25] 持久化画像
            self._persist_profile(profile)
            return profile
        except Exception as e:  # noqa: BLE001
            logger.warning("update_profile 失败: %s", e)
            return self.get_or_create_profile(agent_role)

    def get_profile_anchor(self, agent_role: str) -> str:
        """返回画像注入文本，无画像（或仅默认画像）时返回空串

        只有经过 update_profile 沉淀过的画像（version > 1）才注入，
        确保无历史数据时迭代一行为不变。
        """
        try:
            profile = self._profiles.get(agent_role)
            if profile is None or profile.version <= 1:
                return ""
            lines = [
                "【决策偏置（基于历史行为特征）】",
                f"- 默认风格：{profile.default_stance_style}",
                f"- 证据依赖：{profile.evidence_dependency_level}",
                f"- 协作偏好：{profile.collaboration_preference}",
                f"- 升级阈值：{profile.escalation_threshold}",
                f"- 模糊容忍：{profile.ambiguity_tolerance}",
            ]
            return "\n".join(lines)
        except Exception as e:  # noqa: BLE001
            logger.warning("get_profile_anchor 失败: %s", e)
            return ""

    # ---------- 测试辅助 ----------

    def clear(self) -> None:
        """清空所有数据（测试用）"""
        self._raw.clear()
        self._features.clear()
        self._profiles.clear()


# 进程级单例
memory_store = MemoryStore()
