"""Agent 角色（agent_roles）CRUD。

提供角色列表、单条查询、upsert、删除（内置不可删）与批量按 ID 查询。
已迁移到 SQLAlchemy ORM：显式 select / pg_insert upsert / delete，
不使用手写 SQL 字符串和 relationship（见 docs/sql-development-rules.md）。

[Wave 4] 多租户隔离：
- 内置角色（is_builtin=TRUE）：tenant_id=NULL，全租户可见，不可修改/删除
- 自定义角色（is_builtin=FALSE）：tenant_id=当前租户ID，仅所属租户可见
- 查询：tenant_id = :tid OR tenant_id IS NULL（显示内置 + 本租户自定义）
- 写操作：仅允许操作本租户的自定义角色
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.base import utcnow
from app.db.engine import async_session_factory
from app.db.models import AgentRoleModel
from app.tenants.context import get_tenant_id, is_system_tenant
from app.tenants.dao import current_tenant_id


def _iso(v: Any) -> Any:
    """datetime → ISO 字符串（保持历史 TEXT 返回契约）。"""
    return v.isoformat() if isinstance(v, datetime) else v


def _parse_dt(v: Any) -> datetime:
    """ISO 字符串 / datetime → tz-aware datetime；非法或空值回退 utcnow。"""
    if isinstance(v, datetime):
        return v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            dt = datetime.fromisoformat(v)
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return utcnow()


def _role_scope() -> list[Any]:
    """内置角色（tenant_id IS NULL）全租户可见 + 当前租户自定义角色可见。"""
    if is_system_tenant():
        return []
    tid = get_tenant_id()
    if tid is None:
        return [AgentRoleModel.tenant_id.is_(None)]
    return [or_(AgentRoleModel.tenant_id == tid, AgentRoleModel.tenant_id.is_(None))]


def _role_to_dict(m: AgentRoleModel) -> dict[str, Any]:
    """ORM 实例 → dict（字段与原 raw SQL RETURN + json.loads 保持一致）。"""
    return {
        "id": m.id,
        "display_name": m.display_name,
        "perspective": m.perspective,
        "expertise_domains": json.loads(m.expertise_domains or "[]"),
        "risk_appetite": m.risk_appetite,
        "default_stance": m.default_stance,
        "evidence_preference": m.evidence_preference,
        "model_override": m.model_override,
        "background_brief": m.background_brief,
        "prompt_template": m.prompt_template,
        "is_builtin": m.is_builtin,
        "is_active": m.is_active,
        "tenant_id": m.tenant_id,
        "created_at": _iso(m.created_at),
        "updated_at": _iso(m.updated_at),
    }


async def list_agent_roles(active_only: bool = False) -> list[dict[str, Any]]:
    """列出所有角色，可选仅活跃角色。

    [Wave 4] 多租户隔离：返回内置角色 + 当前租户的自定义角色。
    """
    conds = _role_scope()
    if active_only:
        conds.append(AgentRoleModel.is_active.is_(True))

    stmt = select(AgentRoleModel)
    if conds:
        stmt = stmt.where(*conds)
    stmt = stmt.order_by(AgentRoleModel.is_builtin.desc(), AgentRoleModel.display_name.asc())

    async with async_session_factory() as session:
        result = await session.execute(stmt)
        return [_role_to_dict(r) for r in result.scalars().all()]


async def get_agent_role(role_id: str) -> dict[str, Any] | None:
    """取单个角色。

    [Wave 4] 多租户隔离：内置角色（tenant_id IS NULL）全租户可见，
    自定义角色仅所属租户可见。
    """
    conds = [AgentRoleModel.id == role_id, *_role_scope()]
    async with async_session_factory() as session:
        result = await session.execute(select(AgentRoleModel).where(*conds))
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return _role_to_dict(row)


async def save_agent_role(role: dict[str, Any]) -> None:
    """upsert 角色。

    [Wave 4] 多租户隔离：
    - 内置角色（is_builtin=TRUE）：tenant_id=NULL，由系统初始化写入
    - 自定义角色（is_builtin=FALSE）：tenant_id=当前租户ID
    """
    is_builtin = bool(role.get("is_builtin", 0))
    # 内置角色无租户归属；自定义角色归属当前租户
    tenant_id = None if is_builtin else current_tenant_id()

    insert_stmt = pg_insert(AgentRoleModel).values(
        id=role["id"],
        display_name=role["display_name"],
        perspective=role.get("perspective", ""),
        expertise_domains=json.dumps(role.get("expertise_domains", []), ensure_ascii=False),
        risk_appetite=role.get("risk_appetite", "balanced"),
        default_stance=role.get("default_stance", ""),
        evidence_preference=role.get("evidence_preference", "balanced"),
        model_override=role.get("model_override", ""),
        background_brief=role.get("background_brief", ""),
        prompt_template=role.get("prompt_template", ""),
        is_builtin=is_builtin,
        is_active=bool(role.get("is_active", 1)),
        tenant_id=tenant_id,
        created_at=_parse_dt(role.get("created_at")),
        updated_at=_parse_dt(role.get("updated_at")),
    )
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            "display_name": insert_stmt.excluded.display_name,
            "perspective": insert_stmt.excluded.perspective,
            "expertise_domains": insert_stmt.excluded.expertise_domains,
            "risk_appetite": insert_stmt.excluded.risk_appetite,
            "default_stance": insert_stmt.excluded.default_stance,
            "evidence_preference": insert_stmt.excluded.evidence_preference,
            "model_override": insert_stmt.excluded.model_override,
            "background_brief": insert_stmt.excluded.background_brief,
            "prompt_template": insert_stmt.excluded.prompt_template,
            "is_active": insert_stmt.excluded.is_active,
            "tenant_id": insert_stmt.excluded.tenant_id,
            "updated_at": insert_stmt.excluded.updated_at,
        },
    )
    async with async_session_factory() as session:
        await session.execute(stmt)
        await session.commit()


async def delete_agent_role(role_id: str) -> bool:
    """删除角色（内置角色不可删除）。

    [Wave 4] 多租户隔离：只能删除当前租户的自定义角色。
    """
    if is_system_tenant():
        conds: list[Any] = []
    else:
        tid = get_tenant_id()
        if tid is None:
            return False  # fail-closed
        conds = [AgentRoleModel.tenant_id == tid, AgentRoleModel.is_builtin.is_(False)]

    async with async_session_factory() as session:
        where = [AgentRoleModel.id == role_id, *conds]
        # 先检查角色是否存在且属于当前租户/非内置
        result = await session.execute(select(AgentRoleModel.is_builtin).where(*where))
        is_builtin = result.scalar_one_or_none()
        if is_builtin is None:
            return False
        if is_builtin:
            return False
        await session.execute(delete(AgentRoleModel).where(*where))
        await session.commit()
        return True


async def get_agent_roles_by_ids(role_ids: list[str]) -> list[dict[str, Any]]:
    """批量取角色，按输入顺序返回。

    [Wave 4] 多租户隔离：仅返回内置角色 + 当前租户的自定义角色。
    """
    if not role_ids:
        return []

    conds = [AgentRoleModel.id.in_(role_ids), AgentRoleModel.is_active.is_(True), *_role_scope()]
    async with async_session_factory() as session:
        result = await session.execute(select(AgentRoleModel).where(*conds))
        role_map = {r.id: _role_to_dict(r) for r in result.scalars().all()}
        return [role_map[rid] for rid in role_ids if rid in role_map]
