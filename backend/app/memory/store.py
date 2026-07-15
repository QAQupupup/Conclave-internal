# §2.3 三层记忆存储：进程内单例 + PostgreSQL 持久化
#
# 迁移说明：原使用 raw sqlite3 + threading.Lock，存在以下问题：
#   - threading.Lock 阻塞 asyncio 事件循环
#   - 每次写入新建 sqlite3.connect()，无连接复用
#   - 多 worker 场景 SQLITE_BUSY 静默丢数据
# 现已迁移至 PostgreSQL（复用 async_session_factory），去掉所有锁。
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.memory.models import FeatureMemory, ProfileMemory, RawMemory

logger = logging.getLogger(__name__)

# StubLLM 模式规则提炼用的关键词表
_RISK_HIGH_KEYWORDS: list[str] = [
    "高风险", "危险", "风险", "不可行", "阻塞", "严重", "critical", "high risk",
    "隐患", "漏洞", "威胁",
]
_RISK_LOW_KEYWORDS: list[str] = [
    "低风险", "安全", "可控", "可行", "稳健", "low risk", "无忧", "成熟",
]
_COLLAB_KEYWORDS: list[str] = [
    "建议", "补充", "同意", "认可", "协作", "配合", "协商", "折中", "共识",
]


class MemoryStore:
    """三层记忆存储（进程内单例 + PostgreSQL 持久化）

    - _raw: dict[agent_role, list[RawMemory]]  原始发言
    - _features: dict[agent_role, list[FeatureMemory]]  行为特征
    - _profiles: dict[agent_role, ProfileMemory]  稳定画像

    所有方法包在 try/except 中，失败不抛异常只记 log，确保记忆子系统
    的任何异常都不影响主会议流程。
    """

    _MAX_HISTORY_PER_MEETING = 1000

    def __init__(self) -> None:
        self._raw: dict[str, list[RawMemory]] = {}
        self._features: dict[str, list[FeatureMemory]] = {}
        self._profiles: dict[str, ProfileMemory] = {}
        self._initialized: bool = False

    # ---------- 异步初始化 ----------

    async def init(self) -> None:
        """异步初始化：创建表 + 从 PG 恢复记忆。幂等，多次调用安全。"""
        if self._initialized:
            return
        try:
            from app.db.engine import async_session_factory
            from app.db.models import RawMemoryModel, FeatureMemoryModel, ProfileMemoryModel

            async with async_session_factory() as session:
                async with session.bind.begin() as conn:
                    await conn.run_sync(RawMemoryModel.metadata.create_all)
                await self._load_profiles(session)
                await self._load_features(session)
                await self._load_raw(session)

            self._initialized = True
            logger.info(
                "记忆子系统初始化完成: %d 画像, %d 特征, %d 原始发言",
                len(self._profiles),
                sum(len(v) for v in self._features.values()),
                sum(len(v) for v in self._raw.values()),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("记忆初始化失败（使用空内存）: %s", e)

    async def _load_profiles(self, session) -> None:
        from app.db.models import ProfileMemoryModel
        result = await session.execute(select(ProfileMemoryModel))
        for row in result.scalars():
            self._profiles[row.agent_role] = ProfileMemory(
                agent_role=row.agent_role,
                default_stance_style=row.default_stance_style or "balanced",
                ambiguity_tolerance=row.ambiguity_tolerance or 0.5,
                evidence_dependency_level=row.evidence_dependency_level or "medium",
                collaboration_preference=row.collaboration_preference or "collaborative",
                escalation_threshold=row.escalation_threshold or 0.6,
                updated_at=row.updated_at or datetime.now(timezone.utc),
                version=row.version or 1,
            )

    async def _load_features(self, session) -> None:
        from app.db.models import FeatureMemoryModel
        result = await session.execute(select(FeatureMemoryModel))
        for row in result.scalars():
            fm = FeatureMemory(
                id=row.id,
                agent_role=row.agent_role,
                feature_type=row.feature_type or "",
                feature_value=row.feature_value or "",
                confidence=row.confidence or 0.0,
                sample_count=row.sample_count or 0,
                source_meeting_ids=json.loads(row.source_meeting_ids) if row.source_meeting_ids else [],
                extracted_at=row.extracted_at or datetime.now(timezone.utc),
            )
            self._features.setdefault(fm.agent_role, []).append(fm)

    async def _load_raw(self, session) -> None:
        from app.db.models import RawMemoryModel
        from sqlalchemy import desc
        # 仅加载最近的记录，每个agent最多加载 _MAX_HISTORY_PER_MEETING * 10 条（跨会议）
        # 防止全量加载导致内存暴涨
        result = await session.execute(
            select(RawMemoryModel).order_by(desc(RawMemoryModel.created_at)).limit(5000)
        )
        for row in result.scalars():
            rm = RawMemory(
                id=row.id,
                agent_role=row.agent_role,
                meeting_id=row.meeting_id or "",
                stage=row.stage or "",
                content=row.content or "",
                evidence_refs=json.loads(row.evidence_refs) if row.evidence_refs else [],
                adopted=bool(row.adopted),
                corrected_by=row.corrected_by,
                created_at=row.created_at or datetime.now(timezone.utc),
            )
            self._raw.setdefault(rm.agent_role, []).append(rm)
        # 按时间正序排列
        for role in self._raw:
            self._raw[role].sort(key=lambda x: x.created_at)

    # ---------- 原始发言层 ----------

    async def record_raw(
        self,
        meeting_id: str,
        agent_role: str,
        stage: str,
        content: str,
        evidence_refs: list[str] | None = None,
        adopted: bool = False,
        corrected_by: str | None = None,
    ) -> RawMemory:
        """创建一条 RawMemory 并存入内存 + PG"""
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
            # 内存保护：每agent最多保留 _MAX_RAW_PER_AGENT 条
            _MAX_RAW_PER_AGENT = self._MAX_HISTORY_PER_MEETING * 5  # 5000条/agent
            if len(self._raw[agent_role]) > _MAX_RAW_PER_AGENT:
                self._raw[agent_role] = self._raw[agent_role][-_MAX_RAW_PER_AGENT:]
            await self._persist_raw(mem)
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

    async def _persist_raw(self, mem: RawMemory) -> None:
        try:
            from app.db.engine import async_session_factory
            from app.db.models import RawMemoryModel
            async with async_session_factory() as session:
                stmt = pg_insert(RawMemoryModel).values(
                    id=mem.id,
                    agent_role=mem.agent_role,
                    meeting_id=mem.meeting_id,
                    stage=mem.stage,
                    content=mem.content,
                    evidence_refs=json.dumps(mem.evidence_refs or []),
                    adopted=mem.adopted,
                    corrected_by=mem.corrected_by,
                    created_at=mem.created_at,
                ).on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "content": mem.content,
                        "evidence_refs": json.dumps(mem.evidence_refs or []),
                        "adopted": mem.adopted,
                        "corrected_by": mem.corrected_by,
                    },
                )
                await session.execute(stmt)
                await session.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("原始记忆持久化失败: %s", e)

    def get_raw(self, agent_role: str) -> list[RawMemory]:
        """查询某角色的全部原始发言（纯内存，无 IO）"""
        return self._raw.get(agent_role, [])

    # ---------- 行为特征层 ----------

    async def extract_features(
        self,
        meeting_id: str,
        agent_role: str,
        messages: list[dict[str, Any]],
        decision_record: dict[str, Any] | None = None,
    ) -> list[FeatureMemory]:
        """从多次原始发言中提炼行为特征（StubLLM 模式用简单规则）

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

            # 1. stance_style
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

            # 2. evidence_dependency
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

            # 3. risk_appetite
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

            # 4. collaboration
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
            await self._persist_features(features)
            return features
        except Exception as e:  # noqa: BLE001
            logger.warning("extract_features 失败: %s", e)
            return []

    async def _persist_features(self, features: list[FeatureMemory]) -> None:
        try:
            from app.db.engine import async_session_factory
            from app.db.models import FeatureMemoryModel
            async with async_session_factory() as session:
                for f in features:
                    stmt = pg_insert(FeatureMemoryModel).values(
                        id=f.id,
                        agent_role=f.agent_role,
                        feature_type=f.feature_type,
                        feature_value=f.feature_value,
                        confidence=f.confidence,
                        sample_count=f.sample_count,
                        source_meeting_ids=json.dumps(f.source_meeting_ids or []),
                        extracted_at=f.extracted_at,
                    ).on_conflict_do_update(
                        index_elements=["id"],
                        set_={
                            "feature_value": f.feature_value,
                            "confidence": f.confidence,
                            "sample_count": f.sample_count,
                            "source_meeting_ids": json.dumps(f.source_meeting_ids or []),
                        },
                    )
                    await session.execute(stmt)
                await session.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("行为特征持久化失败: %s", e)

    def get_features(self, agent_role: str) -> list[FeatureMemory]:
        """查询某角色的全部行为特征（纯内存）"""
        return self._features.get(agent_role, [])

    # ---------- 稳定画像层 ----------

    def get_or_create_profile(self, agent_role: str) -> ProfileMemory:
        """取或创建默认 ProfileMemory（纯内存）"""
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

    async def update_profile(self, agent_role: str, features: list[FeatureMemory]) -> ProfileMemory:
        """合并特征到画像（加权平均 confidence），高于阈值的特征才更新"""
        try:
            profile = self.get_or_create_profile(agent_role)
            if not features:
                return profile

            latest: dict[str, FeatureMemory] = {}
            for f in features:
                cur = latest.get(f.feature_type)
                if cur is None or f.confidence > cur.confidence:
                    latest[f.feature_type] = f

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
            await self._persist_profile(profile)
            return profile
        except Exception as e:  # noqa: BLE001
            logger.warning("update_profile 失败: %s", e)
            return self.get_or_create_profile(agent_role)

    async def _persist_profile(self, profile: ProfileMemory) -> None:
        try:
            from app.db.engine import async_session_factory
            from app.db.models import ProfileMemoryModel
            async with async_session_factory() as session:
                stmt = pg_insert(ProfileMemoryModel).values(
                    agent_role=profile.agent_role,
                    default_stance_style=profile.default_stance_style,
                    ambiguity_tolerance=profile.ambiguity_tolerance,
                    evidence_dependency_level=profile.evidence_dependency_level,
                    collaboration_preference=profile.collaboration_preference,
                    escalation_threshold=profile.escalation_threshold,
                    updated_at=profile.updated_at,
                    version=profile.version,
                ).on_conflict_do_update(
                    index_elements=["agent_role"],
                    set_={
                        "default_stance_style": profile.default_stance_style,
                        "ambiguity_tolerance": profile.ambiguity_tolerance,
                        "evidence_dependency_level": profile.evidence_dependency_level,
                        "collaboration_preference": profile.collaboration_preference,
                        "escalation_threshold": profile.escalation_threshold,
                        "updated_at": profile.updated_at,
                        "version": profile.version,
                    },
                )
                await session.execute(stmt)
                await session.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("画像持久化失败: %s", e)

    def get_profile_anchor(self, agent_role: str) -> str:
        """返回画像注入文本（纯内存，无 IO）。version <= 1 时返回空串。"""
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

    async def clear(self) -> None:
        """清空所有数据（内存 + PG），仅测试用"""
        self._raw.clear()
        self._features.clear()
        self._profiles.clear()
        try:
            from app.db.engine import async_session_factory
            from app.db.models import RawMemoryModel, FeatureMemoryModel, ProfileMemoryModel
            async with async_session_factory() as session:
                await session.execute(delete(RawMemoryModel))
                await session.execute(delete(FeatureMemoryModel))
                await session.execute(delete(ProfileMemoryModel))
                await session.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("记忆清理失败: %s", e)


# 进程级单例
memory_store = MemoryStore()