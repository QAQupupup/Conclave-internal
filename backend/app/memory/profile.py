# §2.4 画像注入 + §2.3 提炼触发：会议结束后自动提取特征并更新画像
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def inject_profile(prompt: str, agent_role: str) -> str:
    """从 memory_store 取画像锚点，拼到 prompt 前面

    无画像时原样返回 prompt（迭代一行为不变）。
    """
    try:
        from app.memory.store import memory_store

        anchor = memory_store.get_profile_anchor(agent_role)
        if anchor:
            return f"{anchor}\n\n{prompt}"
        return prompt
    except Exception as e:  # noqa: BLE001
        logger.warning("inject_profile 失败: %s", e)
        return prompt


async def trigger_extraction(state: Any) -> None:
    """会议结束后触发记忆提取

    遍历 state.messages，按 agent_role 分组：
    1. 对每条发言调 store.record_raw 写入原始记忆
    2. 对正式 Role 的 agent 调 extract_features + update_profile 沉淀画像
    3. 借调角色（不在 Role 枚举中）的发言只记录到 RawMemory，不沉淀画像

    此函数必须用 try/except 包裹，任何异常都不能影响主流程。
    当 settings.memory_enabled=False 时直接返回。
    """
    try:
        from app.config import settings

        if not settings.memory_enabled:
            return

        from app.memory.store import memory_store
        from app.models import Role

        meeting_id = getattr(state, "meeting_id", "")
        messages = getattr(state, "messages", []) or []
        decision_record = getattr(state, "decision_record", None) or {}
        adopted_claims = set(decision_record.get("adopted_claims", []) or [])

        # 正式角色集合（借调角色不在其中）
        role_values = {r.value for r in Role}

        # 按 agent_role 分组消息
        groups: dict[str, list[dict[str, Any]]] = {}
        for msg in messages:
            role = msg.get("agent_role", "")
            if not role:
                continue
            groups.setdefault(role, []).append(msg)

        for agent_role, msgs in groups.items():
            # 1. 记录原始发言（所有角色都记录，包括借调角色）
            for msg in msgs:
                claim_refs = msg.get("claim_refs", []) or []
                evidence_refs = msg.get("evidence_refs", []) or []
                adopted = any(c in adopted_claims for c in claim_refs)
                await memory_store.record_raw(
                    meeting_id=meeting_id,
                    agent_role=agent_role,
                    stage=msg.get("stage", ""),
                    content=msg.get("content", ""),
                    evidence_refs=evidence_refs,
                    adopted=adopted,
                )

            # 2. 只有正式 Role 的 agent 才沉淀画像（临时借调不沉淀人格）
            if agent_role not in role_values:
                logger.debug("借调角色 %s 发言已记录但不沉淀画像", agent_role)
                continue

            features = await memory_store.extract_features(
                meeting_id=meeting_id,
                agent_role=agent_role,
                messages=msgs,
                decision_record=decision_record,
            )
            if features:
                await memory_store.update_profile(agent_role, features)
    except Exception as e:  # noqa: BLE001
        logger.warning("trigger_extraction 失败，不影响主流程: %s", e)