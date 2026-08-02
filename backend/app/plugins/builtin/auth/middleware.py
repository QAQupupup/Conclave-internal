"""认证 + CSRF 中间件（Auth 插件）。

功能：
- 从 HttpOnly Cookie（新）或 Authorization Bearer header（旧）提取 JWT
- Dev Token 支持（开发模式）
- 测试模式跳过认证（APP_ENV=test + CONCLAVE_TEST_DISABLE_AUTH=1）
- 速率限制（复用 app.middleware._check_rate_limit）
- CSRF double-submit cookie 保护（仅对 Cookie 认证的写操作）
- 公共路径白名单（/health, /auth/login, /auth/csrf-token, /setup/* 等）
"""

from __future__ import annotations

import logging

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.context import set_domain, set_request_id, set_user_id, set_user_role, set_user_roles, set_username
from app.db.engine import async_session_factory
from app.db.models import TenantMemberModel, UserModel
from app.observability.audit import audit
from app.plugins.builtin.auth.csrf import (
    check_csrf,
)
from app.public_paths import PUBLIC_PATHS as _PUBLIC_PATHS
from app.rbac.enforcer import SYSTEM_DOMAIN, team_domain
from app.tenants import set_tenant_id

logger = logging.getLogger(__name__)


# ---- RBAC 上下文加载（每个请求一次） ----


async def _load_rbac_context(uid: int, tenant_id: int | None) -> tuple[str, str, tuple[str, ...], bool]:
    """根据用户 ID 和租户 ID 加载 RBAC 上下文。

    返回: (system_role, domain, roles_tuple, is_banned)

    规则：
    - system_owner / system_admin 用户在 system domain 下
    - 其他用户在 team domain (t{tid}) 下，需查 tenant_members
    - 被封禁用户 (is_banned=True) 返回 is_banned=True
    - 不在 tenant_members 中的普通用户视为无权限访问该 Team
    """
    if uid is None:
        return "user", SYSTEM_DOMAIN, ("user",), False

    async with async_session_factory() as session:
        # 查用户系统角色
        u_result = await session.execute(select(UserModel.role, UserModel.is_active).where(UserModel.id == uid))
        u_row = u_result.first()
        if not u_row:
            return "user", SYSTEM_DOMAIN, ("user",), True  # 用户不存在，视为封禁
        system_role = u_row[0] or "user"
        is_active = u_row[1] if u_row[1] is not None else True

        if not is_active:
            return system_role, SYSTEM_DOMAIN, (system_role,), True

        # 系统级角色
        if system_role in ("system_owner", "system_admin", "admin"):
            # 兼容旧 role='admin'
            normalized = "system_admin" if system_role == "admin" else system_role
            return normalized, SYSTEM_DOMAIN, (normalized,), False

        # 普通用户：查 tenant_members
        if tenant_id is not None:
            tm_result = await session.execute(
                select(TenantMemberModel.role, TenantMemberModel.is_banned).where(
                    TenantMemberModel.tenant_id == tenant_id,
                    TenantMemberModel.user_id == uid,
                )
            )
            tm_row = tm_result.first()
            if not tm_row:
                # 用户不在该 Team 中
                return system_role, team_domain(tenant_id), (), False
            team_role = tm_row[0] or "member"
            is_banned = bool(tm_row[1])
            return system_role, team_domain(tenant_id), (team_role,), is_banned

        # 无 tenant_id 时，默认在 system domain 但无特殊角色
        return system_role, SYSTEM_DOMAIN, ("user",), False


# Cookie 名（与前端约定）
COOKIE_ACCESS_TOKEN = "conclave_access_token"
COOKIE_REFRESH_TOKEN = "conclave_refresh_token"

# 公共路径（集中定义在 app/public_paths.py，已在文件顶部导入）


def _client_ip(request: Request) -> str:
    """从 request 中提取客户端 IP（优先 X-Forwarded-For）。"""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _normalize_path(path: str) -> str:
    """规范化路径用于白名单匹配（去除末尾斜杠、小写）。"""
    p = path.rstrip("/")
    if not p:
        p = "/"
    return p.lower()


def _is_public_path(path: str) -> bool:
    norm = _normalize_path(path)
    for p in _PUBLIC_PATHS:
        if norm == p:
            return True
        # 前缀匹配：子路径也公开
        if norm.startswith(p + "/"):
            return True
    return False


def _should_check_csrf(request: Request, is_cookie_auth: bool) -> bool:
    """是否需要 CSRF 检查：Cookie 认证 + 非安全 HTTP 方法。"""
    if not is_cookie_auth:
        return False
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return False
    return not _is_public_path(request.url.path)


def setup_auth_middleware(app, plugin=None) -> None:
    """注册认证中间件到 FastAPI app（使用 @app.middleware 装饰器，与旧 middleware 一致）。"""

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next) -> Response:
        import hmac
        import os
        import uuid

        # 生成 request_id
        req_id = request.headers.get("x-request-id", str(uuid.uuid4())[:12])
        set_request_id(req_id)

        path = request.url.path
        method = request.method
        ip = _client_ip(request)

        # 测试模式：跳过认证与限流，注入默认管理员（与 init_auth 创建的 admin 用户一致）
        if os.environ.get("APP_ENV") == "test" and os.environ.get("CONCLAVE_TEST_DISABLE_AUTH") == "1":
            request.state.auth_user = {
                "username": "admin",
                "role": "system_owner",
                "system_role": "system_owner",
                "uid": 1,
                "domain": SYSTEM_DOMAIN,
                "roles": ("system_owner", "system_admin"),
            }
            set_user_id("1")
            set_username("admin")
            set_user_role("system_owner")
            set_user_roles(("system_owner", "system_admin"))
            set_domain(SYSTEM_DOMAIN)
            set_tenant_id(None)
            from app.tenants.context import set_system_tenant as _set_sys

            _set_sys(True)
            return await call_next(request)  # type: ignore[no-any-return]

        # OPTIONS 预检直接放行
        if method == "OPTIONS":
            return await call_next(request)  # type: ignore[no-any-return]

        # WebSocket 端点单独处理
        if path.startswith("/ws"):
            return await call_next(request)  # type: ignore[no-any-return]

        # 公共路径放行（清除 ContextVar 避免污染）
        if _is_public_path(path):
            set_user_id("")
            set_username("")
            set_user_role("")
            set_tenant_id(None)
            from app.tenants.context import set_system_tenant as _set_sys

            _set_sys(False)
            request.state.auth_user = None
            return await call_next(request)  # type: ignore[no-any-return]

        # 延迟 import 避免循环引用
        from app.auth import verify_jwt
        from app.middleware import _DEV_TOKEN, _RATE_BLOCK_SECONDS, _check_rate_limit

        # 速率限制
        ok, reason = _check_rate_limit(ip, is_failed_attempt=False)
        if not ok:
            audit("auth.rate_limited", "failure", {"path": path, "reason": reason}, ip=ip)
            return JSONResponse(
                status_code=429,
                content={"detail": f"请求过于频繁：{reason}"},
                headers={"Retry-After": str(_RATE_BLOCK_SECONDS)},
            )

        # 1. 提取 token（优先 Cookie，其次 Authorization header，最后 dev token）
        token = None
        is_cookie_auth = False

        cookie_token = request.cookies.get(COOKIE_ACCESS_TOKEN)
        if cookie_token:
            token = cookie_token
            is_cookie_auth = True

        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
            is_cookie_auth = False
        elif auth_header.lower().startswith("token "):
            token = auth_header[6:].strip()
            is_cookie_auth = False

        using_dev_token = False
        dev_token_header = request.headers.get("x-dev-token", "")
        dev_token_query = request.query_params.get("dev_token", "")
        dev_token = dev_token_header or dev_token_query
        if dev_token and not token and hmac.compare_digest(dev_token.encode("utf-8"), _DEV_TOKEN.encode("utf-8")):
            using_dev_token = True
            set_user_id("dev")
            set_username("dev")
            set_user_role("system_admin")
            set_user_roles(("system_admin",))
            set_domain(SYSTEM_DOMAIN)
            set_tenant_id(None)
            from app.tenants.context import set_system_tenant as _set_sys2

            _set_sys2(True)
            request.state.auth_user = {
                "username": "dev",
                "role": "system_admin",
                "system_role": "system_admin",
                "uid": None,
                "domain": SYSTEM_DOMAIN,
                "roles": ("system_admin",),
            }

        # 2. CSRF 检查（Cookie 认证的写操作）
        if _should_check_csrf(request, is_cookie_auth) and not check_csrf(request):
            audit("auth.csrf_failed", "failure", {"path": path, "method": method}, ip=ip)
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF 验证失败，请刷新页面重试"},
            )

        # 3. 验证 token
        if not using_dev_token:
            if not token:
                _check_rate_limit(ip, is_failed_attempt=True)
                return JSONResponse(
                    status_code=401,
                    content={"detail": "未授权：请先登录"},
                    headers={"WWW-Authenticate": "Bearer"},
                )

            claims = verify_jwt(token)
            if not claims:
                _check_rate_limit(ip, is_failed_attempt=True)
                audit("auth.invalid_token", "failure", {"path": path}, ip=ip)
                return JSONResponse(
                    status_code=401,
                    content={"detail": "token 无效或已过期"},
                    headers={"WWW-Authenticate": "Bearer"},
                )

            if claims.get("type") == "refresh":
                return JSONResponse(
                    status_code=401,
                    content={"detail": "不能使用 refresh token 访问 API"},
                )

            # 设置 ContextVar 和 request.state.auth_user
            username = claims.get("sub", "")
            uid = claims.get("uid")
            _role = claims.get("role", "user")
            tenant_id = claims.get("tenant_id")
            uid_str = str(uid) if uid is not None else username
            _tid = tenant_id if isinstance(tenant_id, int) else (int(tenant_id) if tenant_id else None)

            # 加载 RBAC 上下文（从 DB 查最新角色/封禁状态）
            _uid_int = uid if isinstance(uid, int) else (int(uid) if uid and str(uid).isdigit() else None)
            _sys_role, _dom, _roles, _banned = await _load_rbac_context(_uid_int or 0, _tid)

            if _banned:
                audit("auth.banned", "failure", {"username": username, "tenant_id": _tid}, ip=ip)
                return JSONResponse(
                    status_code=403,
                    content={"detail": "账号已被封禁，请联系管理员"},
                )

            # 对于非系统管理员但无 Team 角色的用户，在访问 Team API 时会被 Casbin 拒绝，
            # 这里不直接拒绝（因为可能访问的是 /api/user/* 等个人路径）

            set_user_id(uid_str)
            set_username(username)
            # 使用从 DB 查到的最新角色，而不是 JWT 中的（支持热更新）
            set_user_role(_sys_role)
            set_user_roles(_roles)
            set_domain(_dom)
            set_tenant_id(_tid)
            from app.tenants.context import set_system_tenant as _set_sys3

            _set_sys3(_dom == SYSTEM_DOMAIN)
            # 预热租户配置覆盖缓存（fire-and-forget，不阻塞请求）
            if _tid is not None and _dom != SYSTEM_DOMAIN:
                try:
                    import asyncio as _asyncio

                    from app.tenants.settings_override import load_tenant_overrides as _load_ov

                    _warmup_task = _asyncio.create_task(_load_ov(_tid))
                    _warmup_task.add_done_callback(lambda _t: None)  # 防止 GC 回收
                except Exception:
                    pass
            # auth_user 包含完整 claims + RBAC 上下文
            auth_user = dict(claims)
            auth_user["username"] = username
            auth_user["uid"] = uid_str
            auth_user["uid_int"] = _uid_int
            auth_user["tenant_id"] = _tid
            auth_user["system_role"] = _sys_role
            auth_user["domain"] = _dom
            auth_user["roles"] = _roles
            auth_user["role"] = _roles[0] if _roles else _sys_role
            request.state.auth_user = auth_user

        # 4. 放行
        response: Response = await call_next(request)  # type: ignore[assignment]

        # 5. 安全响应头
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        return response

    logger.info("Auth 中间件已注册（Cookie + Bearer 双模式）")
