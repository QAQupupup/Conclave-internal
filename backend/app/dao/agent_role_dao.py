"""Agent 角色（agent_roles）CRUD。

提供角色列表、单条查询、upsert、删除（内置不可删）与批量按 ID 查询。
原迁移自 app/db_legacy.py，逻辑未做任何修改。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.engine import RowMapping

from app.db.engine import async_session_factory


async def list_agent_roles(active_only: bool = False) -> list[dict[str, Any]]:
    """列出所有角色，可选仅活跃角色"""
    async with async_session_factory() as session:
        if active_only:
            result = await session.execute(
                text("SELECT * FROM agent_roles WHERE is_active = 1 ORDER BY is_builtin DESC, display_name ASC")
            )
        else:
            result = await session.execute(text("SELECT * FROM agent_roles ORDER BY is_builtin DESC, display_name ASC"))
        rows = result.mappings().all()
        return [_row_to_role_dict(r) for r in rows]


async def get_agent_role(role_id: str) -> dict[str, Any] | None:
    """取单个角色"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT * FROM agent_roles WHERE id = :role_id"),
            {"role_id": role_id},
        )
        row = result.mappings().first()
        if row is None:
            return None
        return _row_to_role_dict(row)


async def save_agent_role(role: dict[str, Any]) -> None:
    """upsert 角色"""
    async with async_session_factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO agent_roles (
                    id, display_name, perspective, expertise_domains,
                    risk_appetite, default_stance, evidence_preference,
                    model_override, background_brief, prompt_template,
                    is_builtin, is_active, created_at, updated_at
                ) VALUES (
                    :id, :display_name, :perspective, :expertise_domains,
                    :risk_appetite, :default_stance, :evidence_preference,
                    :model_override, :background_brief, :prompt_template,
                    :is_builtin, :is_active, :created_at, :updated_at
                )
                ON CONFLICT(id) DO UPDATE SET
                    display_name=excluded.display_name,
                    perspective=excluded.perspective,
                    expertise_domains=excluded.expertise_domains,
                    risk_appetite=excluded.risk_appetite,
                    default_stance=excluded.default_stance,
                    evidence_preference=excluded.evidence_preference,
                    model_override=excluded.model_override,
                    background_brief=excluded.background_brief,
                    prompt_template=excluded.prompt_template,
                    is_active=excluded.is_active,
                    updated_at=excluded.updated_at
                """
            ),
            {
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
                "is_builtin": role.get("is_builtin", 0),
                "is_active": role.get("is_active", 1),
                "created_at": role.get("created_at", ""),
                "updated_at": role.get("updated_at", ""),
            },
        )
        await session.commit()


async def delete_agent_role(role_id: str) -> bool:
    """删除角色（内置角色不可删除）"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT is_builtin FROM agent_roles WHERE id = :role_id"),
            {"role_id": role_id},
        )
        row = result.mappings().first()
        if row is None:
            return False
        if row["is_builtin"]:
            return False
        await session.execute(
            text("DELETE FROM agent_roles WHERE id = :role_id"),
            {"role_id": role_id},
        )
        await session.commit()
        return True


async def get_agent_roles_by_ids(role_ids: list[str]) -> list[dict[str, Any]]:
    """批量取角色，按输入顺序返回"""
    if not role_ids:
        return []
    async with async_session_factory() as session:
        stmt = text("SELECT * FROM agent_roles WHERE id IN :role_ids AND is_active = 1").bindparams(
            bindparam("role_ids", expanding=True)
        )
        result = await session.execute(stmt, {"role_ids": role_ids})
        rows = result.mappings().all()
        role_map = {r["id"]: _row_to_role_dict(r) for r in rows}
        return [role_map[rid] for rid in role_ids if rid in role_map]


def _row_to_role_dict(row: RowMapping) -> dict[str, Any]:
    """将 SQLAlchemy RowMapping 转为字典，解析 JSON 字段"""
    d = dict(row)
    d["expertise_domains"] = json.loads(d["expertise_domains"])
    return d
