"""会议访问控制守卫

提供统一的会议所有权/参与权限校验，防止越权访问。
权限模型：
- admin 角色：可访问所有会议
- owner（创建者）：可完全控制自己创建的会议
- participant（通过 WS 加入的参与者）：可查看会议状态和接收消息，但不能控制/删除
- 其他用户：拒绝访问
"""

from __future__ import annotations

from fastapi import HTTPException, Request


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
    """判断是否为管理员"""
    return role == "admin"


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
