"""Auth 插件路由：替代原 app/routers/auth.py，增加 Cookie/CSRF 支持。

过渡期兼容策略：
- /auth/login 同时返回 JSON access_token（旧客户端）+ 写 HttpOnly Cookie（新客户端）
- /auth/me 两种认证方式都支持（middleware 已处理，从 ContextVar 读取）
- 新增 /auth/logout /auth/refresh /auth/csrf-token
- 原有 /auth/change-password /auth/users 等端点保持在 app/routers/auth.py（Phase 2 迁移）
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.auth import (
    JWT_EXPIRE_SECONDS,
    REFRESH_TOKEN_EXPIRE_SECONDS,
    authenticate_user,
    create_access_token,
    create_refresh_token,
    verify_jwt,
)
from app.config import settings
from app.context import (
    get_user_id,
    get_user_role,
    get_username,
    set_user_id,
    set_user_role,
    set_username,
)
from app.observability.audit import audit
from app.plugins.builtin.auth.csrf import (
    CSRF_COOKIE_NAME,
    generate_csrf_token,
)
from app.plugins.builtin.auth.middleware import (
    COOKIE_ACCESS_TOKEN,
    COOKIE_REFRESH_TOKEN,
    _client_ip,
)
from app.tenants import get_tenant_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["认证"])

# Cookie 配置
COOKIE_SECURE: bool = settings.cookie_secure
COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"
COOKIE_PATH = "/"


# ---- Schemas ----


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class MeResponse(BaseModel):
    user: dict


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class CsrfResponse(BaseModel):
    csrf_token: str


class UpdateProfileRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=6, max_length=128)


# ---- Helper ----


def _set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
    csrf_token: str,
) -> None:
    """在 response 中设置认证相关 Cookie（HttpOnly + Secure）。"""
    response.set_cookie(
        key=COOKIE_ACCESS_TOKEN,
        value=access_token,
        max_age=JWT_EXPIRE_SECONDS,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path=COOKIE_PATH,
    )
    response.set_cookie(
        key=COOKIE_REFRESH_TOKEN,
        value=refresh_token,
        max_age=REFRESH_TOKEN_EXPIRE_SECONDS,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path=COOKIE_PATH,
    )
    # CSRF cookie 必须可读（非 HttpOnly），供前端 JS 读取后放入 header
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=JWT_EXPIRE_SECONDS,
        httponly=False,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path=COOKIE_PATH,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(key=COOKIE_ACCESS_TOKEN, path=COOKIE_PATH)
    response.delete_cookie(key=COOKIE_REFRESH_TOKEN, path=COOKIE_PATH)
    response.delete_cookie(key=CSRF_COOKIE_NAME, path=COOKIE_PATH)


# ---- Endpoints ----


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request, response: Response) -> LoginResponse:
    """用户登录：同时返回 JSON token 和写 HttpOnly Cookie（过渡期双模式）。"""
    ip = _client_ip(request)

    user = await authenticate_user(req.username, req.password)
    if not user:
        audit(
            "auth.login_failed",
            "failure",
            {"reason": "invalid_credentials"},
            username=req.username,
            ip=ip,
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if user.get("disabled") or not user.get("is_active", True):
        audit(
            "auth.login_failed",
            "failure",
            {"reason": "disabled"},
            username=req.username,
            user_id=user["id"],
            ip=ip,
        )
        raise HTTPException(status_code=403, detail="账号已被禁用")

    user_id = user["id"]
    role = user.get("role", "user")
    username = user["username"]

    access_token = create_access_token(user)
    refresh_token = create_refresh_token(user)
    csrf_token = generate_csrf_token()

    # 设置 ContextVar（本请求后续可用）
    set_user_id(str(user_id))
    set_username(username)
    set_user_role(role)

    # 登录时设置租户上下文：使用用户的默认租户（tenant_id 字段）
    from app.tenants import set_tenant_id as _set_tid

    login_tenant_id = user.get("tenant_id")
    if login_tenant_id:
        _set_tid(int(login_tenant_id))
    else:
        _set_tid(None)

    # 查询租户信息用于返回
    tenant_info: dict | None = None
    tenant_list: list[dict] = []
    if login_tenant_id:
        from app.tenants.service import get_tenant as _get_tenant
        from app.tenants.service import list_user_tenants

        t = await _get_tenant(int(login_tenant_id))
        if t:
            tenant_info = {"id": t.id, "name": t.name, "slug": t.slug, "plan": t.plan}
        tenants = await list_user_tenants(int(user_id))
        from app.plugins.builtin.auth.tenants_router import ROLE_MEMBER, ROLE_OWNER

        tenant_list = [
            {
                "id": tt.id,
                "name": tt.name,
                "slug": tt.slug,
                "role": ROLE_OWNER if tt.owner_id == int(user_id) else ROLE_MEMBER,
                "plan": tt.plan,
            }
            for tt in tenants
        ]

    # 写 HttpOnly Cookie
    _set_auth_cookies(response, access_token, refresh_token, csrf_token)

    audit(
        "auth.login",
        "success",
        {"role": role},
        username=username,
        user_id=str(user_id),
        ip=ip,
    )
    logger.info("用户 %s 登录成功 from=%s role=%s", username, ip, role)

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=JWT_EXPIRE_SECONDS,
        user={
            "id": user_id,
            "username": username,
            "role": role,
            "display_name": user.get("display_name", username),
            "tenant_id": login_tenant_id,
            "tenant": tenant_info,
            "tenants": tenant_list,
        },
    )


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict:
    """用户登出：清除 Cookie，记录审计日志。"""
    user_id = get_user_id() or ""
    username = get_username() or ""
    ip = _client_ip(request)

    _clear_auth_cookies(response)

    # 清除 ContextVar
    set_user_id("")
    set_username("")
    set_user_role("")

    audit("auth.logout", "success", {}, username=username, user_id=user_id, ip=ip)
    logger.info("用户 %s 登出 from=%s", username, ip)
    return {"success": True}


@router.post("/refresh")
async def refresh_token(
    request: Request,
    response: Response,
    body: RefreshRequest | None = None,
) -> dict:
    """刷新 access_token：从 Cookie 或 body 读取 refresh_token。"""
    ip = _client_ip(request)

    # 1. 获取 refresh_token（优先 Cookie，其次 body）
    rt = request.cookies.get(COOKIE_REFRESH_TOKEN)
    if not rt and body and body.refresh_token:
        rt = body.refresh_token
    if not rt:
        raise HTTPException(status_code=401, detail="缺少 refresh_token")

    # 2. 验证 refresh_token
    payload = verify_jwt(rt)
    if not payload:
        raise HTTPException(status_code=401, detail="refresh_token 无效或已过期")
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="无效的 token 类型")

    # refresh token 的 sub 是 user_id（见 create_refresh_token）
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的 token")

    # 3. 查询用户（验证用户仍存在且未禁用）
    from app.auth import _load_users_from_db, _users_cache

    if not _users_cache:
        await _load_users_from_db()
    user = None
    for u in _users_cache.values():
        if str(u.get("id")) == str(user_id):
            user = u
            break
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    if user.get("disabled") or not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="账号已被禁用")

    username = user["username"]

    # 4. 签发新 token
    new_access = create_access_token(user)
    new_refresh = create_refresh_token(user)
    new_csrf = generate_csrf_token()

    # 5. 更新 Cookie（如果原请求来自 Cookie）
    if request.cookies.get(COOKIE_REFRESH_TOKEN):
        _set_auth_cookies(response, new_access, new_refresh, new_csrf)

    audit(
        "auth.refresh",
        "success",
        {},
        username=username,
        user_id=str(user_id),
        ip=ip,
    )

    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
        "expires_in": JWT_EXPIRE_SECONDS,
        "csrf_token": new_csrf,
    }


@router.get("/csrf-token", response_model=CsrfResponse)
async def csrf_token(request: Request, response: Response) -> CsrfResponse:
    """获取 CSRF token：供前端在非安全 HTTP 方法（POST/PUT/DELETE）请求时携带。

    无需认证（登录前也需要获取 CSRF token 来保护登录请求）。
    """
    token = generate_csrf_token()
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=JWT_EXPIRE_SECONDS,
        httponly=False,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path=COOKIE_PATH,
    )
    return CsrfResponse(csrf_token=token)


@router.get("/me", response_model=MeResponse)
async def me(request: Request) -> MeResponse:
    """获取当前用户信息（兼容 Cookie 和 Bearer 两种认证方式）。"""
    user_id = get_user_id()
    username = get_username()
    role = get_user_role()
    tenant_id = get_tenant_id()

    if not user_id or not username:
        raise HTTPException(status_code=401, detail="未登录")

    # 查询用户详情（从缓存）
    from app.auth import _users_cache

    user = _users_cache.get(username)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")

    # 查询当前租户信息
    tenant_info: dict | None = None
    if tenant_id is not None:
        from app.tenants.service import get_tenant

        t = await get_tenant(tenant_id)
        if t:
            tenant_info = {
                "id": t.id,
                "name": t.name,
                "slug": t.slug,
                "plan": t.plan,
            }

    # 查询用户所属租户列表
    from app.tenants.service import list_user_tenants

    tenants = await list_user_tenants(int(user_id))
    from app.plugins.builtin.auth.tenants_router import ROLE_MEMBER as _RM
    from app.plugins.builtin.auth.tenants_router import ROLE_OWNER as _RO

    tenant_list = [
        {"id": t.id, "name": t.name, "slug": t.slug, "role": _RO if t.owner_id == int(user_id) else _RM, "plan": t.plan}
        for t in tenants
    ]

    return MeResponse(
        user={
            "id": user_id,
            "username": username,
            "role": role or user.get("role", "user"),
            "display_name": user.get("display_name", username),
            "tenant_id": tenant_id,
            "tenant": tenant_info,
            "tenants": tenant_list,
        }
    )


@router.put("/profile")
async def update_profile(request: Request, body: UpdateProfileRequest) -> dict:
    """更新当前用户资料（显示名）。"""
    user_id = get_user_id()
    username = get_username()
    if not user_id or not username:
        raise HTTPException(status_code=401, detail="未登录")

    from app.auth import update_display_name as _update_dn

    updated = await _update_dn(username, body.display_name)
    if not updated:
        raise HTTPException(status_code=400, detail="更新失败")

    audit(
        "auth.profile_update", "success", {"display_name": body.display_name}, username=username, user_id=str(user_id)
    )
    return {"success": True, "display_name": updated.get("display_name", body.display_name)}


@router.post("/change-password")
async def change_password_endpoint(request: Request, body: ChangePasswordRequest) -> dict:
    """修改当前用户密码。需验证旧密码。"""
    user_id = get_user_id()
    username = get_username()
    ip = _client_ip(request)
    if not user_id or not username:
        raise HTTPException(status_code=401, detail="未登录")

    from app.auth import change_password as _change_pw

    ok = await _change_pw(username, body.old_password, body.new_password)
    if not ok:
        audit(
            "auth.password_change",
            "failure",
            {"reason": "invalid_old_password_or_policy"},
            username=username,
            user_id=str(user_id),
            ip=ip,
        )
        raise HTTPException(status_code=400, detail="旧密码错误或新密码不符合要求（至少 6 位）")

    audit("auth.password_change", "success", {}, username=username, user_id=str(user_id), ip=ip)
    logger.info("用户 %s 修改密码成功 from=%s", username, ip)
    return {"success": True}
