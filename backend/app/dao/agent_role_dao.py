"""Agent 角色（agent_roles）CRUD。

提供角色列表、单条查询、upsert、删除（内置不可删）与批量按 ID 查询。

[Wave 4] 多租户隔离：
- 内置角色（is_builtin=1）：tenant_id=NULL，全租户可见，不可修改/删除
- 自定义角色（is_builtin=0）：tenant_id=当前租户ID，仅所属租户可见
- 查询：WHERE tenant_id = :tid OR tenant_id IS NULL（显示内置 + 本租户自定义）
- 写操作：仅允许操作本租户的自定义角色
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.engine import RowMapping

from app.db.engine import async_session_factory
from app.tenants.context import get_tenant_id, is_system_tenant


async def list_agent_roles(active_only: bool = False) -> list[dict[str, Any]]:
    """列出所有角色，可选仅活跃角色。

    [Wave 4] 多租户隔离：返回内置角色 + 当前租户的自定义角色。
    """
    if is_system_tenant():
        # 系统租户可看全部
        cond = ""
        params: dict[str, Any] = {}
    else:
        tid = get_tenant_id()
        if tid is None:
            # fail-closed：未设置租户上下文，仅返回内置角色
            cond = "WHERE tenant_id IS NULL"
            params = {}
        else:
            cond = "WHERE (tenant_id = :tid OR tenant_id IS NULL)"
            params = {"tid": tid}

    if active_only:
        if cond:
            cond += " AND is_active = 1"
        else:
            cond = "WHERE is_active = 1"

    async with async_session_factory() as session:
        result = await session.execute(
            text(f"SELECT * FROM agent_roles {cond} ORDER BY is_builtin DESC, display_name ASC"),
            params,
        )
        rows = result.mappings().all()
        return [_row_to_role_dict(r) for r in rows]


async def get_agent_role(role_id: str) -> dict[str, Any] | None:
    """取单个角色。

    [Wave 4] 多租户隔离：内置角色（tenant_id IS NULL）全租户可见，
    自定义角色仅所属租户可见。
    """
    if is_system_tenant():
        cond = ""
        params: dict[str, Any] = {"role_id": role_id}
    else:
        tid = get_tenant_id()
        if tid is None:
            cond = "AND tenant_id IS NULL"
            params = {"role_id": role_id}
        else:
            cond = "AND (tenant_id = :tid OR tenant_id IS NULL)"
            params = {"role_id": role_id, "tid": tid}

    async with async_session_factory() as session:
        result = await session.execute(
            text(f"SELECT * FROM agent_roles WHERE id = :role_id {cond}"),
            params,
        )
        row = result.mappings().first()
        if row is None:
            return None
        return _row_to_role_dict(row)


async def save_agent_role(role: dict[str, Any]) -> None:
    """upsert 角色。

    [Wave 4] 多租户隔离：
    - 内置角色（is_builtin=1）：tenant_id=NULL，由系统初始化写入
    - 自定义角色（is_builtin=0）：tenant_id=当前租户ID
    """
    is_builtin = role.get("is_builtin", 0)
    if is_builtin:
        tenant_id = None  # 内置角色无租户归属
    else:
        from app.tenants.dao import current_tenant_id

        tenant_id = current_tenant_id()

    async with async_session_factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO agent_roles (
                    id, display_name, perspective, expertise_domains,
                    risk_appetite, default_stance, evidence_preference,
                    model_override, background_brief, prompt_template,
                    is_builtin, is_active, tenant_id, created_at, updated_at
                ) VALUES (
                    :id, :display_name, :perspective, :expertise_domains,
                    :risk_appetite, :default_stance, :evidence_preference,
                    :model_override, :background_brief, :prompt_template,
                    :is_builtin, :is_active, :tenant_id, :created_at, :updated_at
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
                    tenant_id=excluded.tenant_id,
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
                "is_builtin": is_builtin,
                "is_active": role.get("is_active", 1),
                "tenant_id": tenant_id,
                "created_at": role.get("created_at", ""),
                "updated_at": role.get("updated_at", ""),
            },
        )
        await session.commit()


async def delete_agent_role(role_id: str) -> bool:
    """删除角色（内置角色不可删除）。

    [Wave 4] 多租户隔离：只能删除当前租户的自定义角色。
    """
    if is_system_tenant():
        cond = ""
        params: dict[str, Any] = {"role_id": role_id}
    else:
        tid = get_tenant_id()
        if tid is None:
            return False  # fail-closed
        cond = "AND tenant_id = :tid AND is_builtin = 0"
        params = {"role_id": role_id, "tid": tid}

    async with async_session_factory() as session:
        # 先检查角色是否存在且属于当前租户
        result = await session.execute(
            text(f"SELECT is_builtin, tenant_id FROM agent_roles WHERE id = :role_id {cond}"),
            params,
        )
        row = result.mappings().first()
        if row is None:
            return False
        if row["is_builtin"]:
            return False
        await session.execute(
            text(f"DELETE FROM agent_roles WHERE id = :role_id {cond}"),
            params,
        )
        await session.commit()
        return True


async def get_agent_roles_by_ids(role_ids: list[str]) -> list[dict[str, Any]]:
    """批量取角色，按输入顺序返回。

    [Wave 4] 多租户隔离：仅返回内置角色 + 当前租户的自定义角色。
    """
    if not role_ids:
        return []
    if is_system_tenant():
        cond = ""
        params: dict[str, Any] = {"role_ids": role_ids}
    else:
        tid = get_tenant_id()
        if tid is None:
            cond = "AND tenant_id IS NULL"
            params = {"role_ids": role_ids}
        else:
            cond = "AND (tenant_id = :tid OR tenant_id IS NULL)"
            params = {"role_ids": role_ids, "tid": tid}

    async with async_session_factory() as session:
        stmt = text(f"SELECT * FROM agent_roles WHERE id IN :role_ids AND is_active = 1 {cond}").bindparams(
            bindparam("role_ids", expanding=True)
        )
        result = await session.execute(stmt, params)
        rows = result.mappings().all()
        role_map = {r["id"]: _row_to_role_dict(r) for r in rows}
        return [role_map[rid] for rid in role_ids if rid in role_map]


def _row_to_role_dict(row: RowMapping) -> dict[str, Any]:
    """将 SQLAlchemy RowMapping 转为字典，解析 JSON 字段"""
    d = dict(row)
    d["expertise_domains"] = json.loads(d["expertise_domains"])
    return d
