# §2.3 三层记忆存储：进程内单例，会议结束触发提炼，下次会议注入画像
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.memory.models import FeatureMemory, ProfileMemory, RawMemory

logger = logging.getLogger(__name__)

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
