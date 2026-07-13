# Agent 反馈闭环：会后评估每个 Agent 的判断质量，写回画像供迭代优化
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def evaluate_agents(state: Any) -> dict[str, dict[str, Any]]:
    """评估每个 Agent 在本次会议中的判断质量。

    计算维度:
    - adoption_rate: 该 Agent 的论点被采纳的比例
    - evidence_accuracy: 有证据支撑的论点被验证的比例
    - overall_score: 综合得分 (0.6 * adoption_rate + 0.4 * evidence_accuracy)

    返回值: {role: {"adoption_rate": float, "evidence_accuracy": float, "overall_score": float, "claims_total": int, "claims_adopted": int}}

    此函数必须用 try/except 包裹调用，任何异常都不能影响主流程。
    """
    try:
        claims = getattr(state, "claims", []) or []
        decision_record = getattr(state, "decision_record", None) or {}
        evidence_set = getattr(state, "evidence_set", []) or []
        getattr(state, "messages", []) or []

        # 构建已采纳论点 ID 集合
        adopted_raw = decision_record.get("adopted_claims", []) or []
        adopted_ids: set[str] = set()
        for a in adopted_raw:
            if isinstance(a, dict):
                cid = a.get("id", a.get("claim_id", ""))
                if cid:
                    adopted_ids.add(cid)
            elif isinstance(a, str) and a:
                adopted_ids.add(a)

        # 构建已验证证据集合（evidence_set 中 supports="supports" 的）
        validated_sources: set[str] = set()
        for es in evidence_set:
            for assessment in es.get("assessments", []):
                if assessment.get("supports") == "supports":
                    src = assessment.get("source", "")
                    if src:
                        validated_sources.add(src)

        # 按 agent_role 分组论点
        role_claims: dict[str, list[dict]] = {}
        for claim in claims:
            role = ""
            if isinstance(claim, dict):
                role = claim.get("agent_role", claim.get("role", ""))
            if not role:
                continue
            role_claims.setdefault(role, []).append(claim)

        # 评估每个角色
        evaluations: dict[str, dict[str, Any]] = {}
        for role, rclaims in role_claims.items():
            total = len(rclaims)
            if total == 0:
                continue

            # 采纳率
            adopted_count = 0
            evidence_backed = 0
            evidence_validated = 0

            for c in rclaims:
                c_id = c.get("id", c.get("claim_id", ""))
                if c_id and c_id in adopted_ids:
                    adopted_count += 1

                # 检查论点是否有证据支撑
                e_refs = c.get("evidence_refs", []) or []
                if e_refs:
                    evidence_backed += 1
                    # 检查证据是否被验证
                    for ref in e_refs:
                        if ref in validated_sources:
                            evidence_validated += 1
                            break

            adoption_rate = adopted_count / total if total > 0 else 0.0
            evidence_accuracy = (
                evidence_validated / evidence_backed
                if evidence_backed > 0
                else 0.0
            )
            overall_score = 0.6 * adoption_rate + 0.4 * evidence_accuracy

            evaluations[role] = {
                "adoption_rate": round(adoption_rate, 3),
                "evidence_accuracy": round(evidence_accuracy, 3),
                "overall_score": round(overall_score, 3),
                "claims_total": total,
                "claims_adopted": adopted_count,
                "evidence_backed": evidence_backed,
                "evidence_validated": evidence_validated,
            }

        # 将评估结果写入 state（供 API 返回和前端展示）
        # agent_evaluations 是 MeetingState 的正式字段（Optional[dict]）
        state.agent_evaluations = evaluations

        # 将评估分数注入记忆系统（供后续会议的画像参考）
        _persist_scores_to_memory(state, evaluations)

        logger.info(
            "Agent 评估完成: %d 个角色, 平均得分 %.2f",
            len(evaluations),
            sum(e["overall_score"] for e in evaluations.values()) / max(len(evaluations), 1),
        )
        return evaluations

    except Exception as e:
        logger.warning("evaluate_agents 失败，不影响主流程: %s", e)
        return {}


def _persist_scores_to_memory(state: Any, evaluations: dict[str, dict]) -> None:
    """将评估分数注入记忆系统的 Feature 层，供后续画像更新参考。

    与 trigger_extraction 互补：trigger_extraction 记录发言和提取特征，
    本函数记录判断质量分数。两者共同构成 Agent 成长的数据基础。
    """
    try:
        from app.config import settings
        if not settings.memory_enabled:
            return

        from app.memory.store import memory_store
        meeting_id = getattr(state, "meeting_id", "")

        for role, scores in evaluations.items():
            # 将分数作为特殊 feature 写入记忆
            memory_store.record_raw(
                meeting_id=meeting_id,
                agent_role=role,
                stage="_evaluation",
                content=(
                    f"[会后评估] adoption_rate={scores['adoption_rate']}, "
                    f"evidence_accuracy={scores['evidence_accuracy']}, "
                    f"overall_score={scores['overall_score']}, "
                    f"claims={scores['claims_total']}, "
                    f"adopted={scores['claims_adopted']}"
                ),
                evidence_refs=[],
                adopted=False,
            )
    except Exception as e:
        logger.debug("_persist_scores_to_memory 失败: %s", e)
