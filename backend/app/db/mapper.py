"""Data Mapper：Pydantic Domain ↔ SQLAlchemy ORM 双向转换。

职责：
1. 将 ORM 行转为 Pydantic Domain Model（供业务层消费）
2. 将 Pydantic Domain Model 转为 ORM 参数（供 Repository 写入）
3. schema_version 标记：读取旧版本数据时自动升级

演进策略：
- 当前版本: schema_version=1
- 未来新增字段时，在 _upgrade_payload() 中添加转换逻辑
- 业务代码无需感知版本差异
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.db.models import (
    MeetingModel, MessageModel, EventModel, MeetingTagModel,
    AgentRoleModel, UserPreferenceModel, NetAuthRequestModel,
)

# 当前最新数据格式版本
CURRENT_SCHEMA_VERSION = 1


# ============================================================
# Meeting ↔ MeetingModel
# ============================================================

def meeting_row_to_dict(row: MeetingModel) -> dict[str, Any]:
    """ORM → dict（兼容旧 db.py 的返回格式）"""
    payload = _parse_json(row.payload)
    # 版本升级：如果版本低于当前，走升级链
    payload = _upgrade_payload(payload, row.schema_version)
    return {
        "id": row.id,
        "topic": row.topic,
        "status": row.status,
        "stage": row.stage,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "payload": payload,
        "schema_version": row.schema_version,
    }


def meeting_to_orm_values(meeting_id: str, topic: str, status: str,
                          stage: str, created_at: datetime,
                          payload: dict[str, Any],
                          schema_version: int = CURRENT_SCHEMA_VERSION) -> dict[str, Any]:
    """Domain → ORM values"""
    return {
        "id": meeting_id,
        "topic": topic,
        "status": status,
        "stage": stage,
        "created_at": created_at,
        "payload": json.dumps(payload, ensure_ascii=False, default=str),
        "schema_version": schema_version,
    }


# ============================================================
# Message ↔ MessageModel
# ============================================================

def message_row_to_dict(row: MessageModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "meeting_id": row.meeting_id,
        "agent_role": row.agent_role,
        "stage": row.stage,
        "content": row.content,
        "claim_refs": _parse_json(row.claim_refs),
        "evidence_refs": _parse_json(row.evidence_refs),
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def message_to_orm_values(msg: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": msg["id"],
        "meeting_id": msg["meeting_id"],
        "agent_role": msg["agent_role"],
        "stage": msg["stage"],
        "content": msg["content"],
        "claim_refs": json.dumps(msg.get("claim_refs", []), ensure_ascii=False),
        "evidence_refs": json.dumps(msg.get("evidence_refs", []), ensure_ascii=False),
        "created_at": _parse_datetime(msg.get("created_at")),
    }


# ============================================================
# Event ↔ EventModel
# ============================================================

def event_row_to_dict(row: EventModel) -> dict[str, Any]:
    return {
        "seq": row.seq,
        "meeting_id": row.meeting_id,
        "type": row.type,
        "payload": _parse_json(row.payload),
        "ts": row.ts.isoformat() if row.ts else "",
        "trace_id": row.trace_id,
    }


# ============================================================
# AgentRole ↔ AgentRoleModel
# ============================================================

def agent_role_row_to_dict(row: AgentRoleModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "display_name": row.display_name,
        "perspective": row.perspective,
        "expertise_domains": _parse_json(row.expertise_domains),
        "risk_appetite": row.risk_appetite,
        "default_stance": row.default_stance,
        "evidence_preference": row.evidence_preference,
        "model_override": row.model_override,
        "background_brief": row.background_brief,
        "prompt_template": row.prompt_template,
        "is_builtin": row.is_builtin,
        "is_active": row.is_active,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def agent_role_to_orm_values(role: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": role["id"],
        "display_name": role["display_name"],
        "perspective": role.get("perspective", ""),
        "expertise_domains": json.dumps(role.get("expertise_domains", []), ensure_ascii=False),
        "risk_appetite": role.get("risk_appetite", "balanced"),
        "default_stance": role.get("default_stance", ""),
        "evidence_preference": role.get("evidence_preference", "balanced"),
        "model_override": role.get("model_override", ""),
        "background_brief": role.get("background_brief", ""),
        "prompt_template": role.get("prompt_template", ""),
        "is_builtin": role.get("is_builtin", False),
        "is_active": role.get("is_active", True),
        "created_at": _parse_datetime(role.get("created_at")),
        "updated_at": _parse_datetime(role.get("updated_at")),
    }


# ============================================================
# Tag ↔ MeetingTagModel
# ============================================================

def tag_row_to_dict(row: MeetingTagModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "meeting_id": row.meeting_id,
        "tag": row.tag,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


# ============================================================
# Preference ↔ UserPreferenceModel
# ============================================================

def preference_row_to_dict(row: UserPreferenceModel) -> dict[str, Any]:
    return {
        "user_id": row.user_id,
        "key": row.key,
        "value": row.value,
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


# ============================================================
# NetAuth ↔ NetAuthRequestModel
# ============================================================

def net_auth_row_to_dict(row: NetAuthRequestModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "meeting_id": row.meeting_id,
        "stage": row.stage,
        "code_snippet": row.code_snippet,
        "requested_level": row.requested_level,
        "detected_level": row.detected_level,
        "failure_reason": row.failure_reason,
        "stderr_output": row.stderr_output,
        "status": row.status,
        "review_action": row.review_action,
        "review_comment": row.review_comment,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "expires_at": row.expires_at.isoformat() if row.expires_at else "",
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


# ============================================================
# 辅助函数
# ============================================================

def _parse_json(raw: str | None) -> Any:
    """安全解析 JSON 字符串"""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def _parse_datetime(val: Any) -> datetime:
    """将各种格式转为 datetime"""
    if val is None:
        return datetime.now(timezone.utc)
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val)
        except (ValueError, TypeError):
            return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)


def _upgrade_payload(payload: dict[str, Any], from_version: int) -> dict[str, Any]:
    """根据版本号升级 payload 数据格式。

    升级链：
    - v1: 初始版本，无需升级
    - v2: (未来) 例如新增字段、重命名键等
    """
    current = payload
    # 版本链：逐级升级
    # if from_version < 2:
    #     current = _v1_to_v2(current)
    # if from_version < 3:
    #     current = _v2_to_v3(current)
    return current