"""会议访问控制守卫

提供统一的会议所有权/参与权限校验，防止越权访问。
权限模型：
- admin 角色：可访问所有会议
- owner（创建者）：可完全控制自己创建的会议
- participant（通过 WS 加入的参与者）：可查看会议状态和接收消息，但不能控制/删除
- 其他用户：拒绝访问

删除权限额外规则（assert_can_delete_meeting）：
- system_owner / system_admin：可删除任何会议
- 会议创建者（owner_username 匹配）：可删除自己创建的会议
- Team owner / maintainer：可删除所属团队内的任何会议
- Team member / reporter：不可删除（即使是自己创建的，需由 owner/maintainer 管控）
"""

from __future__ import annotations

from fastapi import HTTPException, Request

# 可删除会议的团队角色（权重 >= 70）
_DELETE_ALLOWED_TEAM_ROLES = frozenset({"owner", "maintainer"})


def get_current_user(request: Request) -> tuple[str | None, str, str | None]:
    """从 request.state 获取当前用户信息。
    返回 (uid, username, role) 三元组。未认证返回 (None, "anonymous", None)。
    """
    auth_user = getattr(request.state, "auth_user", None)
    if not auth_user:
        return (None, "anonymous", None)
    uid = str(auth_user.get("uid", "") or "") or None
    username = auth_user.get("username", "anonymous")
    role = auth_user.get("role", "") or None
    return (uid, username, role)


def is_admin(role: str | None) -> bool:
    """判断是否为管理员

    支持三种管理员角色标识：
    - system_owner: 系统所有者
    - system_admin: 系统管理员（数据库 users.role 的实际值）
    - admin: 兼容 dev token 和旧数据
    """
    return role in ("system_owner", "system_admin", "admin")


def assert_meeting_access(
    request: Request,
    meeting_state,
    *,
    require_owner: bool = False,
    require_write: bool = False,
) -> tuple[str, str]:
    """校验当前用户是否有权访问指定会议。

    Args:
        request: FastAPI Request 对象
        meeting_state: MeetingState 对象（必须含 owner_username / participants 字段）
        require_owner: 是否需要 owner 权限（delete/run/control 等操作）
        require_write: 是否需要写权限（intervene 等操作）

    Returns:
        (username, uid) 元组

    Raises:
        HTTPException 403: 无权限
        HTTPException 401: 未认证
    """
    uid, username, role = get_current_user(request)

    # 未认证用户
    if not username or username == "anonymous":
        raise HTTPException(status_code=401, detail="未认证，请先登录")

    # admin 角色拥有完全权限（含 dev token 自动授予的 admin 角色）
    if is_admin(role):
        return (username, uid or "")

    # 获取会议 owner 信息（兼容旧数据：owner_username 为 None 时视为无主会议）
    owner = getattr(meeting_state, "owner_username", None)
    participants = getattr(meeting_state, "participants", []) or []

    if require_owner:
        # 需要 owner 权限：只有 owner 和 admin 可以
        if owner is None:
            # 旧数据无 owner，允许访问（数据迁移过渡期）
            return (username, uid or "")
        if username == owner:
            return (username, uid or "")
        raise HTTPException(status_code=403, detail=f"无权操作此会议（仅创建者 {owner} 可执行此操作）")

    if require_write:
        # 需要写权限：owner、admin、参与者均可
        if owner is None or username == owner or username in participants:
            return (username, uid or "")
        raise HTTPException(status_code=403, detail="无权在此会议中发言")

    # 只读访问：owner、admin、参与者
    if owner is None or username == owner or username in participants:
        return (username, uid or "")
    raise HTTPException(status_code=403, detail="无权访问此会议")


def filter_meetings_by_owner(request: Request, meetings: list[dict]) -> list[dict]:
    """根据当前用户过滤会议列表（非 admin 只看自己创建的会议）。"""
    _uid, username, role = get_current_user(request)
    if is_admin(role) or not username or username == "anonymous":
        return meetings
    return [m for m in meetings if m.get("owner_username") == username or m.get("owner_username") is None]


async def assert_can_delete_meeting(
    request: Request,
    meeting: dict,
) -> tuple[str, str]:
    """校验当前用户是否有权删除指定会议。

    删除权限层级（从高到低）：
    1. system_owner / system_admin / admin → 始终允许
    2. 会议创建者（owner_username == username）→ 允许
    3. Team owner / maintainer（会议所属团队的管理角色）→ 允许
    4. 其他 → 403 拒绝

    Args:
        request: FastAPI Request 对象
        meeting: 会议记录 dict（来自 DAO get_meeting，含 owner_username / tenant_id）

    Returns:
        (username, uid) 元组

    Raises:
        HTTPException 401: 未认证
        HTTPException 403: 无删除权限
    """
    uid, username, role = get_current_user(request)

    # 未认证用户
    if not username or username == "anonymous":
        raise HTTPException(status_code=401, detail="未认证，请先登录")

    # 1. 系统管理员始终允许
    if is_admin(role):
        return (username, uid or "")

    owner_username = meeting.get("owner_username")
    tenant_id = meeting.get("tenant_id")

    # 2. 会议创建者允许
    if owner_username is not None and username == owner_username:
        return (username, uid or "")

    # 3. 旧数据无 owner，允许访问（数据迁移过渡期）
    if owner_username is None:
        return (username, uid or "")

    # 4. 检查团队角色（owner / maintainer 可删除团队内任何会议）
    if tenant_id is not None and uid:
        try:
            from app.rbac.policies import get_user_roles_in_team

            team_roles = await get_user_roles_in_team(uid, tenant_id)
            if any(r in _DELETE_ALLOWED_TEAM_ROLES for r in team_roles):
                return (username, uid or "")
        except Exception:
            pass  # RBAC 查询失败时不阻断，降级到拒绝

    # 5. 拒绝
    raise HTTPException(
        status_code=403,
        detail="无权删除此会议（仅创建者、Team owner 或 maintainer 可删除）",
    )
