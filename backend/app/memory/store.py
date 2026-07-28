# §2.3 三层记忆存储：进程内单例 + PostgreSQL 持久化
#
# 迁移说明：原使用 raw sqlite3 + threading.Lock，存在以下问题：
#   - threading.Lock 阻塞 asyncio 事件循环
#   - 每次写入新建 sqlite3.connect()，无连接复用
#   - 多 worker 场景 SQLITE_BUSY 静默丢数据
# 现已迁移至 PostgreSQL（复用 async_session_factory），去掉所有锁。
#
# [Wave 5] 多租户隔离：
#   - 内存字典 key 从 agent_role 改为 (tenant_id, agent_role) 复合键
#   - 所有 DB 查询/写入附加 tenant_id 过滤/填充
#   - 查询时 fail-closed：无租户上下文返回空，防止跨租户数据泄露
#   - ProfileMemoryModel 主键迁移：agent_role → UUID id（见 init() 迁移逻辑）
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.memory.models import FeatureMemory, ProfileMemory, RawMemory
from app.tenants.context import get_tenant_id, is_system_tenant

logger = logging.getLogger(__name__)

# StubLLM 模式规则提炼用的关键词表
_RISK_HIGH_KEYWORDS: list[str] = [
    "高风险",
    "危险",
    "风险",
    "不可行",
    "阻塞",
    "严重",
    "critical",
    "high risk",
    "隐患",
    "漏洞",
    "威胁",
]
_RISK_LOW_KEYWORDS: list[str] = [
    "低风险",
    "安全",
    "可控",
    "可行",
    "稳健",
    "low risk",
    "无忧",
    "成熟",
]
_COLLAB_KEYWORDS: list[str] = [
    "建议",
    "补充",
    "同意",
    "认可",
    "协作",
    "配合",
    "协商",
    "折中",
    "共识",
]

# 复合键类型：(tenant_id, agent_role)
_MemKey = tuple[int | None, str]


class MemoryStore:
    """三层记忆存储（进程内单例 + PostgreSQL 持久化）

    [Wave 5] 多租户隔离：
    - _raw: dict[(tenant_id, agent_role), list[RawMemory]]
    - _features: dict[(tenant_id, agent_role), list[FeatureMemory]]
    - _profiles: dict[(tenant_id, agent_role), ProfileMemory]

    所有方法包在 try/except 中，失败不抛异常只记 log，确保记忆子系统
    的任何异常都不影响主会议流程。
    """

    _MAX_HISTORY_PER_MEETING = 1000

    def __init__(self) -> None:
        self._raw: dict[_MemKey, list[RawMemory]] = {}
        self._features: dict[_MemKey, list[FeatureMemory]] = {}
        self._profiles: dict[_MemKey, ProfileMemory] = {}
        self._initialized: bool = False

    # ---------- 租户上下文辅助 ----------

    @staticmethod
    def _ctx_tenant_id() -> int | None:
        """获取当前租户 ID（用于写入和内存键）。

        系统租户返回 None（写入系统级数据）。
        普通租户返回其 tenant_id。
        无上下文时返回 None（调用方需自行处理 fail-closed）。
        """
        if is_system_tenant():
            return None
        return get_tenant_id()

    def _read_key(self, agent_role: str) -> _MemKey | None:
        """构建读取用的内存键。无租户上下文时返回 None（fail-closed）。"""
        if is_system_tenant():
            return (None, agent_role)
        tid = get_tenant_id()
        if tid is None:
            return None  # fail-closed
        return (tid, agent_role)

    # ---------- 异步初始化 ----------

    async def init(self) -> None:
        """异步初始化：迁移旧表 + 创建表 + 从 PG 恢复记忆。幂等，多次调用安全。"""
        if self._initialized:
            return
        try:
            from app.db.engine import async_session_factory
            from app.db.models import RawMemoryModel

            # [Wave 5] 迁移 profile_memories 旧主键（agent_role → UUID id）
            await self._migrate_profile_memories_pk()

            async with async_session_factory() as session:
                async with session.bind.begin() as conn:
                    await conn.run_sync(RawMemoryModel.metadata.create_all)  # type: ignore[union-attr]
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
        except Exception as e:
            logger.warning("记忆初始化失败（使用空内存）: %s", e)

    async def _migrate_profile_memories_pk(self) -> None:
        """[Wave 5] 迁移 profile_memories 表主键。

        旧表以 agent_role 为主键，新表以 UUID id 为主键。
        检测到旧表（无 id 列）时 DROP TABLE，由 create_all 重建。
        profile 数据是可重建的缓存，丢失不影响系统功能。
        """
        try:
            from app.db.engine import async_session_factory

            async with async_session_factory() as session:
                # 检查 profile_memories 表是否存在且有 id 列
                result = await session.execute(
                    text(
                        """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'profile_memories'
                    ORDER BY ordinal_position
                    """
                    )
                )
                columns = {row[0] for row in result.fetchall()}

                if columns and "id" not in columns:
                    # 旧表：有数据但无 id 列，需要 DROP 重建
                    logger.info("检测到 profile_memories 旧表结构（agent_role 主键），执行迁移: DROP + CREATE")
                    await session.execute(text("DROP TABLE IF EXISTS profile_memories"))
                    await session.commit()
                elif columns and "id" in columns:
                    # 新表：已有 id 列，无需迁移
                    pass
                else:
                    # 表不存在：create_all 会创建
                    pass
        except Exception as e:
            logger.warning("profile_memories 主键迁移检查失败（忽略）: %s", e)

    async def _load_profiles(self, session) -> None:
        from app.db.models import ProfileMemoryModel

        result = await session.execute(select(ProfileMemoryModel))
        for row in result.scalars():
            key: _MemKey = (row.tenant_id, row.agent_role)
            self._profiles[key] = ProfileMemory(
                agent_role=row.agent_role,
                default_stance_style=row.default_stance_style or "balanced",
                ambiguity_tolerance=row.ambiguity_tolerance or 0.5,
                evidence_dependency_level=row.evidence_dependency_level or "medium",
                collaboration_preference=row.collaboration_preference or "collaborative",
                escalation_threshold=row.escalation_threshold or 0.6,
                updated_at=row.updated_at or datetime.now(timezone.utc),
                version=row.version or 1,
                tenant_id=row.tenant_id,
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
                tenant_id=row.tenant_id,
            )
            key: _MemKey = (row.tenant_id, fm.agent_role)
            self._features.setdefault(key, []).append(fm)

    async def _load_raw(self, session) -> None:
        from sqlalchemy import desc

        from app.db.models import RawMemoryModel

        # 仅加载最近的记录，每个agent最多加载 _MAX_HISTORY_PER_MEETING * 10 条（跨会议）
        # 防止全量加载导致内存暴涨
        result = await session.execute(select(RawMemoryModel).order_by(desc(RawMemoryModel.created_at)).limit(5000))
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
                tenant_id=row.tenant_id,
            )
            key: _MemKey = (row.tenant_id, rm.agent_role)
            self._raw.setdefault(key, []).append(rm)
        # 按时间正序排列
        for key in self._raw:
            self._raw[key].sort(key=lambda x: x.created_at)

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
        """创建一条 RawMemory 并存入内存 + PG

        [Wave 5] tenant_id 从当前上下文获取，自动隔离。
        """
        try:
            tid = self._ctx_tenant_id()
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
                tenant_id=tid,
            )
            key: _MemKey = (tid, agent_role)
            self._raw.setdefault(key, []).append(mem)
            # 内存保护：每 agent 最多保留 _MAX_RAW_PER_AGENT 条
            _MAX_RAW_PER_AGENT = self._MAX_HISTORY_PER_MEETING * 5  # 5000条/agent
            if len(self._raw[key]) > _MAX_RAW_PER_AGENT:
                self._raw[key] = self._raw[key][-_MAX_RAW_PER_AGENT:]
            await self._persist_raw(mem)
            return mem
        except Exception as e:
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
                stmt = (
                    pg_insert(RawMemoryModel)
                    .values(
                        id=mem.id,
                        agent_role=mem.agent_role,
                        meeting_id=mem.meeting_id,
                        stage=mem.stage,
                        content=mem.content,
                        evidence_refs=json.dumps(mem.evidence_refs or []),
                        adopted=mem.adopted,
                        corrected_by=mem.corrected_by,
                        created_at=mem.created_at,
                        tenant_id=mem.tenant_id,
                    )
                    .on_conflict_do_update(
                        index_elements=["id"],
                        set_={
                            "content": mem.content,
                            "evidence_refs": json.dumps(mem.evidence_refs or []),
                            "adopted": mem.adopted,
                            "corrected_by": mem.corrected_by,
                        },
                    )
                )
                await session.execute(stmt)
                await session.commit()
        except Exception as e:
            logger.warning("原始记忆持久化失败: %s", e)

    def get_raw(self, agent_role: str) -> list[RawMemory]:
        """查询某角色的全部原始发言（纯内存，无 IO）

        [Wave 5] 按当前租户上下文隔离，无上下文时 fail-closed 返回空。
        """
        key = self._read_key(agent_role)
        if key is None:
            return []
        return self._raw.get(key, [])

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

        [Wave 5] tenant_id 从当前上下文获取，自动隔离。
        """
        try:
            if not messages:
                return []
            tid = self._ctx_tenant_id()
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
            features.append(
                FeatureMemory(
                    id=f"feat-{uuid.uuid4().hex[:8]}",
                    agent_role=agent_role,
                    feature_type="stance_style",
                    feature_value=stance_value,
                    confidence=confidence,
                    sample_count=sample_count,
                    source_meeting_ids=[meeting_id],
                    extracted_at=now,
                    tenant_id=tid,
                )
            )

            # 2. evidence_dependency
            avg_evidence = evidence_count / max(1, sample_count)
            if avg_evidence >= 1.5:
                ev_value = "high"
            elif avg_evidence >= 0.5:
                ev_value = "medium"
            else:
                ev_value = "low"
            features.append(
                FeatureMemory(
                    id=f"feat-{uuid.uuid4().hex[:8]}",
                    agent_role=agent_role,
                    feature_type="evidence_dependency",
                    feature_value=ev_value,
                    confidence=confidence,
                    sample_count=sample_count,
                    source_meeting_ids=[meeting_id],
                    extracted_at=now,
                    tenant_id=tid,
                )
            )

            # 3. risk_appetite
            if risk_high_count > sample_count * 0.5:
                risk_value = "conservative"
            elif risk_low_count > sample_count * 0.5:
                risk_value = "aggressive"
            else:
                risk_value = "balanced"
            features.append(
                FeatureMemory(
                    id=f"feat-{uuid.uuid4().hex[:8]}",
                    agent_role=agent_role,
                    feature_type="risk_appetite",
                    feature_value=risk_value,
                    confidence=confidence,
                    sample_count=sample_count,
                    source_meeting_ids=[meeting_id],
                    extracted_at=now,
                    tenant_id=tid,
                )
            )

            # 4. collaboration
            collab_ratio = collab_count / max(1, sample_count)
            if collab_ratio >= 0.5:
                collab_value = "collaborative"
            elif collab_ratio >= 0.2:
                collab_value = "bridging"
            else:
                collab_value = "independent"
            features.append(
                FeatureMemory(
                    id=f"feat-{uuid.uuid4().hex[:8]}",
                    agent_role=agent_role,
                    feature_type="collaboration",
                    feature_value=collab_value,
                    confidence=confidence,
                    sample_count=sample_count,
                    source_meeting_ids=[meeting_id],
                    extracted_at=now,
                    tenant_id=tid,
                )
            )

            key: _MemKey = (tid, agent_role)
            self._features.setdefault(key, []).extend(features)
            await self._persist_features(features)
            return features
        except Exception as e:
            logger.warning("extract_features 失败: %s", e)
            return []

    async def _persist_features(self, features: list[FeatureMemory]) -> None:
        try:
            from app.db.engine import async_session_factory
            from app.db.models import FeatureMemoryModel

            async with async_session_factory() as session:
                for f in features:
                    stmt = (
                        pg_insert(FeatureMemoryModel)
                        .values(
                            id=f.id,
                            agent_role=f.agent_role,
                            feature_type=f.feature_type,
                            feature_value=f.feature_value,
                            confidence=f.confidence,
                            sample_count=f.sample_count,
                            source_meeting_ids=json.dumps(f.source_meeting_ids or []),
                            extracted_at=f.extracted_at,
                            tenant_id=f.tenant_id,
                        )
                        .on_conflict_do_update(
                            index_elements=["id"],
                            set_={
                                "feature_value": f.feature_value,
                                "confidence": f.confidence,
                                "sample_count": f.sample_count,
                                "source_meeting_ids": json.dumps(f.source_meeting_ids or []),
                            },
                        )
                    )
                    await session.execute(stmt)
                await session.commit()
        except Exception as e:
            logger.warning("行为特征持久化失败: %s", e)

    def get_features(self, agent_role: str) -> list[FeatureMemory]:
        """查询某角色的全部行为特征（纯内存）

        [Wave 5] 按当前租户上下文隔离，无上下文时 fail-closed 返回空。
        """
        key = self._read_key(agent_role)
        if key is None:
            return []
        return self._features.get(key, [])

    # ---------- 稳定画像层 ----------

    def get_or_create_profile(self, agent_role: str) -> ProfileMemory:
        """取或创建默认 ProfileMemory（纯内存）

        [Wave 5] 按当前租户上下文隔离。
        """
        try:
            tid = self._ctx_tenant_id()
            key: _MemKey = (tid, agent_role)
            if key in self._profiles:
                return self._profiles[key]
            profile = ProfileMemory(
                agent_role=agent_role,
                default_stance_style="balanced",
                ambiguity_tolerance=0.5,
                evidence_dependency_level="medium",
                collaboration_preference="collaborative",
                escalation_threshold=0.6,
                updated_at=datetime.now(timezone.utc),
                version=1,
                tenant_id=tid,
            )
            self._profiles[key] = profile
            return profile
        except Exception as e:
            logger.warning("get_or_create_profile 失败: %s", e)
            return ProfileMemory(agent_role=agent_role)

    async def update_profile(self, agent_role: str, features: list[FeatureMemory]) -> ProfileMemory:
        """合并特征到画像（加权平均 confidence），高于阈值的特征才更新

        [Wave 5] 按当前租户上下文隔离。
        """
        try:
            tid = self._ctx_tenant_id()
            key: _MemKey = (tid, agent_role)
            profile = self._profiles.get(key)
            if profile is None:
                profile = ProfileMemory(
                    agent_role=agent_role,
                    default_stance_style="balanced",
                    ambiguity_tolerance=0.5,
                    evidence_dependency_level="medium",
                    collaboration_preference="collaborative",
                    escalation_threshold=0.6,
                    updated_at=datetime.now(timezone.utc),
                    version=1,
                    tenant_id=tid,
                )
                self._profiles[key] = profile

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
            profile.tenant_id = tid
            self._profiles[key] = profile
            await self._persist_profile(profile)
            return profile
        except Exception as e:
            logger.warning("update_profile 失败: %s", e)
            return self.get_or_create_profile(agent_role)

    async def _persist_profile(self, profile: ProfileMemory) -> None:
        """[Wave 5] 画像持久化：手动 query-then-update-or-insert。

        ProfileMemoryModel 主键已从 agent_role 改为 UUID id，
        on_conflict_do_update 无法按 (tenant_id, agent_role) 检测冲突，
        改为先查后更/插。
        """
        try:
            from app.db.engine import async_session_factory
            from app.db.models import ProfileMemoryModel

            async with async_session_factory() as session:
                # 按 (tenant_id, agent_role) 查询现有记录
                result = await session.execute(
                    select(ProfileMemoryModel).where(
                        ProfileMemoryModel.agent_role == profile.agent_role,
                        ProfileMemoryModel.tenant_id.is_(profile.tenant_id)
                        if profile.tenant_id is None
                        else ProfileMemoryModel.tenant_id == profile.tenant_id,
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    # 更新现有记录
                    existing.default_stance_style = profile.default_stance_style
                    existing.ambiguity_tolerance = profile.ambiguity_tolerance
                    existing.evidence_dependency_level = profile.evidence_dependency_level
                    existing.collaboration_preference = profile.collaboration_preference
                    existing.escalation_threshold = profile.escalation_threshold
                    existing.updated_at = profile.updated_at
                    existing.version = profile.version
                else:
                    # 插入新记录
                    record = ProfileMemoryModel(
                        agent_role=profile.agent_role,
                        default_stance_style=profile.default_stance_style,
                        ambiguity_tolerance=profile.ambiguity_tolerance,
                        evidence_dependency_level=profile.evidence_dependency_level,
                        collaboration_preference=profile.collaboration_preference,
                        escalation_threshold=profile.escalation_threshold,
                        updated_at=profile.updated_at,
                        version=profile.version,
                        tenant_id=profile.tenant_id,
                    )
                    session.add(record)

                await session.commit()
        except Exception as e:
            logger.warning("画像持久化失败: %s", e)

    def get_profile_anchor(self, agent_role: str) -> str:
        """返回画像注入文本（纯内存，无 IO）。version <= 1 时返回空串。

        [Wave 5] 按当前租户上下文隔离，无上下文时 fail-closed 返回空。
        """
        try:
            key = self._read_key(agent_role)
            if key is None:
                return ""
            profile = self._profiles.get(key)
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
        except Exception as e:
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
            from app.db.models import FeatureMemoryModel, ProfileMemoryModel, RawMemoryModel

            async with async_session_factory() as session:
                await session.execute(delete(RawMemoryModel))
                await session.execute(delete(FeatureMemoryModel))
                await session.execute(delete(ProfileMemoryModel))
                await session.commit()
        except Exception as e:
            logger.warning("记忆清理失败: %s", e)


# 进程级单例
memory_store = MemoryStore()
