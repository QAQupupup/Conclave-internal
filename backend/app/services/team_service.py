"""Team（租户）服务层：成员管理、角色变更、封禁、邀请、分页列表、模糊搜索。

核心规则：
- 角色权重：owner(100) > maintainer(70) > member(30) > reporter(10) > banned(0)
- 只能管理比自己角色低的用户
- owner 只能有一个，且不能被降级/移除（必须先转让 owner）
- system_admin 在 system domain 有所有权限，但在 team domain 需显式角色
- 封禁用户立即生效（从 Casbin 移除角色）
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select

from app.db.engine import async_session_factory
from app.db.models import TenantMemberModel, TenantModel, UserModel
from app.observability.audit import audit
from app.rbac.policies import (
    ROLE_BANNED,
    ROLE_MAINTAINER,
    ROLE_MEMBER,
    ROLE_OWNER,
    ROLE_REPORTER,
    TEAM_ROLE_WEIGHT,
    add_user_to_team_role,
    cleanup_tenant_policies,
    remove_user_from_team,
    role_can_manage,
    seed_team_policies,
)

logger = logging.getLogger(__name__)


class TeamServiceError(Exception):
    """Team 服务基础异常"""

    def __init__(self, message: str, code: str = "team_error"):
        self.message = message
        self.code = code
        super().__init__(message)


class PermissionDeniedError(TeamServiceError):
    def __init__(self, message: str = "权限不足"):
        super().__init__(message, "permission_denied")


class NotFoundError(TeamServiceError):
    def __init__(self, message: str = "资源不存在"):
        super().__init__(message, "not_found")


class ValidationError(TeamServiceError):
    def __init__(self, message: str = "参数错误"):
        super().__init__(message, "validation_error")


class ConflictError(TeamServiceError):
    def __init__(self, message: str = "操作冲突"):
        super().__init__(message, "conflict")


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _user_to_dict(u: UserModel, tm: TenantMemberModel | None = None) -> dict[str, Any]:
    """将 UserModel + 可选的 TenantMemberModel 转换为 API 返回 dict。"""
    d: dict[str, Any] = {
        "user_id": u.id,
        "username": u.username,
        "display_name": u.display_name or u.username,
        "email": u.email,
        "is_active": u.is_active if u.is_active is not None else True,
        "avatar_url": None,  # 预留
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }
    if tm is not None:
        d["membership_id"] = tm.id
        d["role"] = tm.role
        d["is_banned"] = tm.is_banned
        d["joined_at"] = tm.joined_at.isoformat() if tm.joined_at else None
    return d


# ---------------------------------------------------------------------------
# Team CRUD
# ---------------------------------------------------------------------------


async def create_team(
    name: str,
    owner_id: int,
    slug: str | None = None,
    description: str = "",
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """创建新 Team，并将创建者设为 owner。"""
    if not name or not name.strip():
        raise ValidationError("Team 名称不能为空")

    slug_clean = slug or name.strip().lower().replace(" ", "-")

    async with async_session_factory() as session, session.begin():
        # 检查 slug 唯一性
        existing = await session.execute(select(TenantModel).where(TenantModel.slug == slug_clean))
        if existing.scalar_one_or_none():
            raise ConflictError(f"Team 标识 '{slug_clean}' 已存在")

        # 创建租户
        tenant = TenantModel(
            name=name.strip(),
            slug=slug_clean,
            description=description.strip() if description else "",
            owner_id=owner_id,
            settings=settings or {},
        )
        session.add(tenant)
        await session.flush()  # 获取 tenant.id

        # 创建 owner 成员记录
        member = TenantMemberModel(
            tenant_id=tenant.id,
            user_id=owner_id,
            role=ROLE_OWNER,
            is_banned=False,
            joined_at=datetime.now(),
        )
        session.add(member)

        await session.commit()

        # 刷新以获取最终数据
        await session.refresh(tenant)

    # 初始化 Casbin Team 策略
    await seed_team_policies(tenant.id)
    await add_user_to_team_role(str(owner_id), tenant.id, ROLE_OWNER)

    audit("team.created", "success", {"team_id": tenant.id, "name": name}, user_id=owner_id)

    return {
        "id": tenant.id,
        "name": tenant.name,
        "slug": tenant.slug,
        "description": tenant.description,
        "owner_id": tenant.owner_id,
        "settings": tenant.settings if isinstance(tenant.settings, dict) else {},
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
    }


async def get_team(team_id: int) -> dict[str, Any] | None:
    """获取 Team 详情。"""
    async with async_session_factory() as session:
        result = await session.execute(select(TenantModel).where(TenantModel.id == team_id))
        t = result.scalar_one_or_none()
        if not t:
            return None

        # 统计成员数
        count_result = await session.execute(
            select(func.count())
            .select_from(TenantMemberModel)
            .where(
                TenantMemberModel.tenant_id == team_id,
                TenantMemberModel.is_banned.is_(False),
            )
        )
        member_count = count_result.scalar() or 0

        # 获取 owner 信息
        owner_result = await session.execute(select(UserModel).where(UserModel.id == t.owner_id))
        owner = owner_result.scalar_one_or_none()

    return {
        "id": t.id,
        "name": t.name,
        "slug": t.slug,
        "description": t.description,
        "owner_id": t.owner_id,
        "owner_name": owner.display_name or owner.username if owner else "",
        "member_count": member_count,
        "settings": t.settings if isinstance(t.settings, dict) else {},
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


async def list_user_teams(user_id: int) -> list[dict[str, Any]]:
    """列出用户所在的所有 Team（未封禁）。"""
    async with async_session_factory() as session:
        result = await session.execute(
            select(TenantModel, TenantMemberModel)
            .join(TenantMemberModel, TenantMemberModel.tenant_id == TenantModel.id)
            .where(
                TenantMemberModel.user_id == user_id,
                TenantMemberModel.is_banned.is_(False),
            )
            .order_by(TenantMemberModel.joined_at.desc())
        )
        rows = result.all()

    teams = []
    for t, tm in rows:
        teams.append(
            {
                "id": t.id,
                "name": t.name,
                "slug": t.slug,
                "role": tm.role,
                "is_owner": t.owner_id == user_id,
                "joined_at": tm.joined_at.isoformat() if tm.joined_at else None,
            }
        )
    return teams


async def update_team(
    team_id: int,
    operator_id: int,
    operator_role: str,
    name: str | None = None,
    description: str | None = None,
    settings_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """更新 Team 信息。需要 owner 或 maintainer 权限（且角色比被管对象高）。"""
    _require_role_at_least(operator_role, ROLE_MAINTAINER)

    async with async_session_factory() as session, session.begin():
        result = await session.execute(select(TenantModel).where(TenantModel.id == team_id))
        t = result.scalar_one_or_none()
        if not t:
            raise NotFoundError(f"Team {team_id} 不存在")

        if name is not None:
            t.name = name.strip()
        if description is not None:
            t.description = description.strip()
        if settings_patch:
            current = t.settings if isinstance(t.settings, dict) else {}
            current.update(settings_patch)
            t.settings = current

        await session.commit()

    audit("team.updated", "success", {"team_id": team_id}, user_id=operator_id)

    team = await get_team(team_id)
    return team or {}


async def delete_team(team_id: int, operator_id: int, operator_role: str) -> bool:
    """删除 Team。只有 owner 可以删除。"""
    if operator_role != ROLE_OWNER:
        raise PermissionDeniedError("只有 Team 所有者可以删除 Team")

    async with async_session_factory() as session, session.begin():
        result = await session.execute(select(TenantModel).where(TenantModel.id == team_id))
        t = result.scalar_one_or_none()
        if not t:
            raise NotFoundError(f"Team {team_id} 不存在")
        if t.owner_id != operator_id:
            raise PermissionDeniedError("只有 Team 所有者可以删除 Team")

        await session.delete(t)
        await session.commit()

    # 清理 Casbin 策略
    await cleanup_tenant_policies(team_id)

    audit("team.deleted", "success", {"team_id": team_id}, user_id=operator_id)
    return True


# ---------------------------------------------------------------------------
# 成员管理
# ---------------------------------------------------------------------------


async def list_members(
    team_id: int,
    page: int = 1,
    page_size: int = 10,
    search: str = "",
    role_filter: str | None = None,
    include_banned: bool = False,
) -> dict[str, Any]:
    """分页获取 Team 成员列表，支持模糊搜索和角色过滤。

    Args:
        team_id: Team ID
        page: 页码（从 1 开始）
        page_size: 每页条数（默认 10，最大 100）
        search: 模糊搜索 username/display_name/email
        role_filter: 按角色过滤 (owner/maintainer/member/reporter/banned)
        include_banned: 是否包含被封禁的成员
    """
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    offset = (page - 1) * page_size

    async with async_session_factory() as session:
        # 构建查询
        query = (
            select(UserModel, TenantMemberModel)
            .join(TenantMemberModel, TenantMemberModel.user_id == UserModel.id)
            .where(TenantMemberModel.tenant_id == team_id)
        )

        count_query = (
            select(func.count())
            .select_from(TenantMemberModel)
            .join(UserModel, UserModel.id == TenantMemberModel.user_id)
            .where(TenantMemberModel.tenant_id == team_id)
        )

        if not include_banned:
            query = query.where(TenantMemberModel.is_banned.is_(False))
            count_query = count_query.where(TenantMemberModel.is_banned.is_(False))
        elif role_filter == ROLE_BANNED:
            query = query.where(TenantMemberModel.is_banned.is_(True))
            count_query = count_query.where(TenantMemberModel.is_banned.is_(True))

        if role_filter and role_filter != ROLE_BANNED:
            query = query.where(TenantMemberModel.role == role_filter)
            count_query = count_query.where(TenantMemberModel.role == role_filter)

        if search:
            like = f"%{search}%"
            search_cond = or_(
                UserModel.username.ilike(like),
                UserModel.display_name.ilike(like),
                UserModel.email.ilike(like),
            )
            query = query.where(search_cond)
            count_query = count_query.where(search_cond)

        # 总数
        total_result = await session.execute(count_query)
        total = total_result.scalar() or 0

        # 分页数据
        query = (
            query.order_by(
                # 按角色权重排序（owner 在前），再按加入时间
                TenantMemberModel.role.desc(),
                TenantMemberModel.joined_at.asc(),
            )
            .offset(offset)
            .limit(page_size)
        )
        result = await session.execute(query)
        rows = result.all()

    members = [_user_to_dict(u, tm) for u, tm in rows]

    return {
        "items": members,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
    }


async def add_member(
    team_id: int,
    operator_id: int,
    operator_role: str,
    username: str,
    role: str = ROLE_MEMBER,
) -> dict[str, Any]:
    """邀请/添加成员到 Team。operator 必须有足够权限。"""
    # 权限检查：至少 maintainer 才能加人，且只能加比自己角色低的
    _require_role_at_least(operator_role, ROLE_MAINTAINER)
    if role not in TEAM_ROLE_WEIGHT:
        raise ValidationError(f"无效角色: {role}")
    if role == ROLE_OWNER:
        raise ValidationError("不能直接将成员设为 owner，请使用转让功能")
    if not role_can_manage(operator_role, role):
        raise PermissionDeniedError(f"无权设置角色 '{role}'，只能设置比自己低的角色")

    async with async_session_factory() as session, session.begin():
        # 查找用户
        u_result = await session.execute(
            select(UserModel).where(
                or_(
                    UserModel.username == username,
                    UserModel.email == username,
                )
            )
        )
        user = u_result.scalar_one_or_none()
        if not user:
            raise NotFoundError(f"用户 '{username}' 不存在")
        if user.is_active is False:
            raise ValidationError(f"用户 '{username}' 已被停用")

        # 检查是否已在 Team 中
        tm_result = await session.execute(
            select(TenantMemberModel).where(
                TenantMemberModel.tenant_id == team_id,
                TenantMemberModel.user_id == user.id,
            )
        )
        existing = tm_result.scalar_one_or_none()
        if existing:
            if existing.is_banned:
                # 解封：角色改为指定角色
                existing.is_banned = False
                existing.role = role
                existing.invited_by = operator_id
            else:
                raise ConflictError(f"用户 '{username}' 已在 Team 中")
        else:
            member = TenantMemberModel(
                tenant_id=team_id,
                user_id=user.id,
                role=role,
                is_banned=False,
                invited_by=operator_id,
                joined_at=datetime.now(),
            )
            session.add(member)

        await session.commit()

    # 同步 Casbin（add_user_to_team_role 内部会先移除所有旧角色再添加新角色）
    await add_user_to_team_role(user.id, team_id, role)

    audit(
        "team.member_added",
        "success",
        {"team_id": team_id, "target_user": user.username, "role": role},
        user_id=operator_id,
    )

    return {"user_id": user.id, "username": user.username, "role": role}


async def remove_member(
    team_id: int,
    operator_id: int,
    operator_role: str,
    target_user_id: int,
) -> bool:
    """从 Team 中移除成员。operator 必须有足够权限。不能移除 owner。"""
    async with async_session_factory() as session, session.begin():
        # 获取目标成员信息
        tm_result = await session.execute(
            select(TenantMemberModel, UserModel)
            .join(UserModel, UserModel.id == TenantMemberModel.user_id)
            .where(
                TenantMemberModel.tenant_id == team_id,
                TenantMemberModel.user_id == target_user_id,
            )
        )
        row = tm_result.first()
        if not row:
            raise NotFoundError("成员不存在")
        tm, _target_user = row

        # owner 不能被移除
        if tm.role == ROLE_OWNER:
            raise PermissionDeniedError("不能移除 Team 所有者，请先转让所有权")

        # 权限检查：只能移除比自己角色低的
        if operator_id != target_user_id and not role_can_manage(operator_role, tm.role):  # 允许自己退出
            raise PermissionDeniedError("无权移除该成员")

        # 检查 operator 不能移除自己（owner 不能离开自己的 team）
        if operator_id == target_user_id and tm.role == ROLE_OWNER:
            raise ValidationError("所有者不能退出自己的 Team，请先转让所有权或删除 Team")

        await session.delete(tm)
        await session.commit()

    # 从 Casbin 移除所有该用户在该 Team 的角色
    await remove_user_from_team(str(target_user_id), team_id)

    audit(
        "team.member_removed",
        "success",
        {"team_id": team_id, "target_user_id": target_user_id},
        user_id=operator_id,
    )
    return True


async def change_member_role(
    team_id: int,
    operator_id: int,
    operator_role: str,
    target_user_id: int,
    new_role: str,
) -> dict[str, Any]:
    """修改成员角色。operator 必须比目标角色高，且新角色比自己低。"""
    if new_role not in TEAM_ROLE_WEIGHT:
        raise ValidationError(f"无效角色: {new_role}")

    # owner 转让走单独接口
    if new_role == ROLE_OWNER:
        raise ValidationError("不能直接设为 owner，请使用所有权转让接口")

    async with async_session_factory() as session, session.begin():
        tm_result = await session.execute(
            select(TenantMemberModel).where(
                TenantMemberModel.tenant_id == team_id,
                TenantMemberModel.user_id == target_user_id,
            )
        )
        tm = tm_result.scalar_one_or_none()
        if not tm:
            raise NotFoundError("成员不存在")

        old_role = tm.role
        if old_role == ROLE_OWNER:
            raise PermissionDeniedError("不能修改 owner 角色，请使用所有权转让")

        # 权限检查：operator 必须能管理 old_role 和 new_role
        if not role_can_manage(operator_role, old_role):
            raise PermissionDeniedError("无权修改该成员的角色")
        if not role_can_manage(operator_role, new_role):
            raise PermissionDeniedError(f"无权设置角色 '{new_role}'")

        # 如果是解封（old_role was banned implicitly），清除 banned 标记
        if tm.is_banned and new_role != ROLE_BANNED:
            tm.is_banned = False

        tm.role = new_role
        await session.commit()

    # 更新 Casbin（add_user_to_team_role 内部会移除所有旧角色再添加新角色）
    await add_user_to_team_role(target_user_id, team_id, new_role)

    audit(
        "team.member_role_changed",
        "success",
        {"team_id": team_id, "target_user_id": target_user_id, "old_role": old_role, "new_role": new_role},
        user_id=operator_id,
    )

    return {"user_id": target_user_id, "old_role": old_role, "new_role": new_role}


async def ban_member(
    team_id: int,
    operator_id: int,
    operator_role: str,
    target_user_id: int,
    reason: str = "",
) -> bool:
    """封禁成员。被封禁用户无法访问 Team 资源，但不删除成员记录（方便解封）。"""
    _require_role_at_least(operator_role, ROLE_MAINTAINER)

    async with async_session_factory() as session, session.begin():
        tm_result = await session.execute(
            select(TenantMemberModel).where(
                TenantMemberModel.tenant_id == team_id,
                TenantMemberModel.user_id == target_user_id,
            )
        )
        tm = tm_result.scalar_one_or_none()
        if not tm:
            raise NotFoundError("成员不存在")

        if tm.role == ROLE_OWNER:
            raise PermissionDeniedError("不能封禁 Team 所有者")

        if not role_can_manage(operator_role, tm.role):
            raise PermissionDeniedError("无权封禁该成员")

        old_role = tm.role
        tm.is_banned = True
        tm.role = ROLE_BANNED
        await session.commit()

    # 更新 Casbin：add_user_to_team_role 会移除所有旧角色再添加 banned
    await add_user_to_team_role(target_user_id, team_id, ROLE_BANNED)

    audit(
        "team.member_banned",
        "success",
        {"team_id": team_id, "target_user_id": target_user_id, "reason": reason, "old_role": old_role},
        user_id=operator_id,
    )
    return True


async def unban_member(
    team_id: int,
    operator_id: int,
    operator_role: str,
    target_user_id: int,
    new_role: str = ROLE_MEMBER,
) -> bool:
    """解封成员，恢复为指定角色。"""
    _require_role_at_least(operator_role, ROLE_MAINTAINER)

    if new_role not in (ROLE_MEMBER, ROLE_REPORTER, ROLE_MAINTAINER):
        raise ValidationError("解封后只能设为 member/reporter/maintainer")
    if not role_can_manage(operator_role, new_role):
        raise PermissionDeniedError("无权设置该解封角色")

    async with async_session_factory() as session, session.begin():
        tm_result = await session.execute(
            select(TenantMemberModel).where(
                TenantMemberModel.tenant_id == team_id,
                TenantMemberModel.user_id == target_user_id,
            )
        )
        tm = tm_result.scalar_one_or_none()
        if not tm:
            raise NotFoundError("成员不存在")
        if not tm.is_banned:
            raise ValidationError("该成员未被封禁")

        tm.is_banned = False
        tm.role = new_role
        await session.commit()

    # 更新 Casbin：add_user_to_team_role 会移除 banned 再添加新角色
    await add_user_to_team_role(target_user_id, team_id, new_role)

    audit(
        "team.member_unbanned",
        "success",
        {"team_id": team_id, "target_user_id": target_user_id, "new_role": new_role},
        user_id=operator_id,
    )
    return True


async def transfer_ownership(
    team_id: int,
    operator_id: int,
    target_user_id: int,
) -> bool:
    """转让 Team 所有权。只有当前 owner 可以转让。"""
    async with async_session_factory() as session, session.begin():
        t_result = await session.execute(select(TenantModel).where(TenantModel.id == team_id))
        t = t_result.scalar_one_or_none()
        if not t:
            raise NotFoundError(f"Team {team_id} 不存在")
        if t.owner_id != operator_id:
            raise PermissionDeniedError("只有 Team 所有者可以转让所有权")
        if target_user_id == operator_id:
            raise ValidationError("不能转让给自己")

        # 目标用户必须是 Team 成员
        tm_target = await session.execute(
            select(TenantMemberModel).where(
                TenantMemberModel.tenant_id == team_id,
                TenantMemberModel.user_id == target_user_id,
                TenantMemberModel.is_banned.is_(False),
            )
        )
        target_tm = tm_target.scalar_one_or_none()
        if not target_tm:
            raise NotFoundError("目标用户必须是 Team 成员且未被封禁")

        # 更新 owner
        old_owner_id = t.owner_id
        t.owner_id = target_user_id

        # 更新成员角色
        # 旧 owner 变为 maintainer
        tm_old_result = await session.execute(
            select(TenantMemberModel).where(
                TenantMemberModel.tenant_id == team_id,
                TenantMemberModel.user_id == old_owner_id,
            )
        )
        old_tm = tm_old_result.scalar_one_or_none()
        if old_tm:
            old_tm.role = ROLE_MAINTAINER
        # 新 owner
        target_tm.role = ROLE_OWNER

        await session.commit()

    # 更新 Casbin：旧 owner 降级为 maintainer，新用户提升为 owner
    await add_user_to_team_role(old_owner_id, team_id, ROLE_MAINTAINER)
    await add_user_to_team_role(target_user_id, team_id, ROLE_OWNER)

    audit(
        "team.ownership_transferred",
        "success",
        {"team_id": team_id, "old_owner": old_owner_id, "new_owner": target_user_id},
        user_id=operator_id,
    )
    return True


# ---------------------------------------------------------------------------
# 用户搜索（用于邀请成员的 autocomplete）
# ---------------------------------------------------------------------------


async def search_users(
    keyword: str,
    team_id: int | None = None,
    exclude_team_members: bool = True,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """搜索用户（模糊匹配 username/display_name/email）。

    Args:
        keyword: 搜索关键词（至少 1 个字符）
        team_id: 如果指定，可选择排除已在 Team 中的成员
        exclude_team_members: 是否排除已在 Team 中的成员
        limit: 返回数量上限（默认 10，最大 50）
    """
    if not keyword or not keyword.strip():
        return []
    limit = min(max(1, limit), 50)
    like = f"%{keyword.strip()}%"

    async with async_session_factory() as session:
        query = select(UserModel).where(
            UserModel.is_active.is_(True),
            or_(
                UserModel.username.ilike(like),
                UserModel.display_name.ilike(like),
                UserModel.email.ilike(like),
            ),
        )

        if team_id is not None and exclude_team_members:
            # 排除已在 Team 中的用户
            subq = select(TenantMemberModel.user_id).where(TenantMemberModel.tenant_id == team_id)
            query = query.where(UserModel.id.notin_(subq))

        query = query.order_by(UserModel.username.asc()).limit(limit)
        result = await session.execute(query)
        users = result.scalars().all()

    return [_user_to_dict(u) for u in users]


# ---------------------------------------------------------------------------
# 权限辅助
# ---------------------------------------------------------------------------


def _require_role_at_least(current_role: str, required_role: str) -> None:
    """检查当前角色是否达到所需角色的权重。不满足则抛 PermissionDeniedError。"""
    current_weight = TEAM_ROLE_WEIGHT.get(current_role, 0)
    required_weight = TEAM_ROLE_WEIGHT.get(required_role, 0)
    if current_weight < required_weight:
        raise PermissionDeniedError(f"需要 '{required_role}' 或更高角色权限")


async def get_user_role_in_team(user_id: int, team_id: int) -> str | None:
    """获取用户在指定 Team 中的角色，未加入返回 None，被封禁返回 'banned'。"""
    async with async_session_factory() as session:
        result = await session.execute(
            select(TenantMemberModel.role, TenantMemberModel.is_banned).where(
                TenantMemberModel.tenant_id == team_id,
                TenantMemberModel.user_id == user_id,
            )
        )
        row = result.first()
        if not row:
            return None
        role: str | None = row[0]
        is_banned: bool = row[1]
        if is_banned:
            return ROLE_BANNED
        return role
