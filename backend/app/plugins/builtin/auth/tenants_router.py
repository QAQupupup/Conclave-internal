"""租户管理 API 路由（挂载在 /api/tenants 下）。

提供：
- GET  /api/tenants              列出当前用户所属租户
- POST /api/tenants              创建新租户（自动成为 owner）
- GET  /api/tenants/{id}/members 列出租户成员
- POST /api/tenants/{id}/switch  切换到指定租户（返回新 JWT）
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.auth import create_access_token, create_refresh_token
from app.context import get_user_id, get_username
from app.plugins.builtin.auth.csrf import (
    generate_csrf_token,
)
from app.plugins.builtin.auth.router import (
    JWT_EXPIRE_SECONDS,
    _set_auth_cookies,
)
from app.tenants import (
    ROLE_MEMBER,
    ROLE_OWNER,
    TenantCreate,
    add_user_to_tenant,
    create_tenant,
    generate_unique_slug,
    get_tenant,
    is_tenant_owner,
    list_tenant_members,
    list_user_tenants,
    user_has_tenant_access,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tenants", tags=["租户管理"])


# ---- Schemas ----


class TenantCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, description="租户名称")
    slug: str | None = Field(None, min_length=2, max_length=64, description="URL slug（可选，自动生成）")


class TenantInfoResponse(BaseModel):
    id: int
    name: str
    slug: str
    plan: str
    role: str  # owner / member
    created_at: str | None = None


class TenantListResponse(BaseModel):
    tenants: list[TenantInfoResponse]
    current_tenant_id: int | None = None


class TenantMemberResponse(BaseModel):
    user_id: int
    username: str
    display_name: str
    email: str | None = None
    role: str
    joined_at: str | None = None


class TenantMemberListResponse(BaseModel):
    members: list[TenantMemberResponse]


class TenantSwitchRequest(BaseModel):
    tenant_id: int = Field(..., description="目标租户 ID")


class TenantSwitchResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    csrf_token: str
    tenant: TenantInfoResponse
    user: dict  # 完整用户信息（含 tenants 列表），与 /auth/login 返回格式一致


class TenantSettingsUpdateRequest(BaseModel):
    """租户级 AI 配置覆盖（仅白名单字段）。"""
    llm_api_key: str | None = Field(None, max_length=512, description="LLM API Key")
    llm_base_url: str | None = Field(None, max_length=512, description="LLM Base URL")
    llm_model: str | None = Field(None, max_length=128, description="LLM 模型名")
    embed_api_key: str | None = Field(None, max_length=512, description="Embedding API Key")
    embed_base_url: str | None = Field(None, max_length=512, description="Embedding Base URL")
    embed_model: str | None = Field(None, max_length=128, description="Embedding 模型名")
    rerank_api_key: str | None = Field(None, max_length=512, description="Reranker API Key")
    rerank_base_url: str | None = Field(None, max_length=512, description="Reranker Base URL")
    rerank_model: str | None = Field(None, max_length=128, description="Reranker 模型名")
    web_search_api_key: str | None = Field(None, max_length=512, description="Web Search API Key")
    web_search_mode: str | None = Field(None, max_length=32, description="Web Search 模式 (stub/tavily/playwright)")


class TenantSettingsResponse(BaseModel):
    settings: dict


# ---- Helper ----


def _require_auth() -> tuple[int, str]:
    """获取当前认证用户，未登录则抛 401。返回 (user_id, username)。"""
    uid_str = get_user_id()
    uname = get_username()
    if not uid_str or not uname:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        return int(uid_str), uname
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="无效的用户标识") from exc


def _tenant_to_response(t, current_user_id: int) -> TenantInfoResponse:
    """将 TenantInfo 转为 API 响应，填充当前用户角色。"""
    role = ROLE_OWNER if t.owner_id == current_user_id else ROLE_MEMBER
    return TenantInfoResponse(
        id=t.id,
        name=t.name,
        slug=t.slug,
        plan=t.plan,
        role=role,
        created_at=t.created_at,
    )


# ---- Endpoints ----


@router.get("", response_model=TenantListResponse)
async def list_my_tenants(request: Request) -> TenantListResponse:
    """列出当前用户所属的全部租户。"""
    from app.tenants.context import get_tenant_id as _ctx_get_tid

    user_id, _ = _require_auth()
    tenants = await list_user_tenants(user_id)
    current_tid = _ctx_get_tid()
    return TenantListResponse(
        tenants=[_tenant_to_response(t, user_id) for t in tenants],
        current_tenant_id=current_tid,
    )


@router.post("", response_model=TenantInfoResponse, status_code=201)
async def create_new_tenant(
    body: TenantCreateRequest,
    request: Request,
    response: Response,
) -> TenantInfoResponse:
    """创建新租户。创建者自动成为 owner 并切换到该租户。"""
    user_id, username = _require_auth()

    # 生成 slug
    slug = body.slug or generate_unique_slug(body.name)

    # 创建租户（owner_id 已设置，不自动改变用户当前 tenant_id；用户可通过 /switch 切换）
    try:
        tenant = await create_tenant(TenantCreate(
            name=body.name,
            slug=slug,
            plan="free",
            owner_id=user_id,
        ))
    except ValueError as e:
        # slug 重复
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        logger.exception("创建租户失败")
        raise HTTPException(status_code=500, detail="创建租户失败") from e

    logger.info("用户 %s 创建租户 %s(id=%d)", username, tenant.name, tenant.id)
    return _tenant_to_response(tenant, user_id)


@router.get("/{tenant_id}/members", response_model=TenantMemberListResponse)
async def get_tenant_members(tenant_id: int, request: Request) -> TenantMemberListResponse:
    """列出租户成员列表。需要是该租户成员。"""
    user_id, _ = _require_auth()

    # 先检查租户是否存在
    tenant = await get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")

    # 验证访问权限（系统租户模式下跳过权限检查）
    from app.tenants import is_system_tenant
    if not is_system_tenant() and not await user_has_tenant_access(user_id, tenant_id):
        raise HTTPException(status_code=403, detail="无权访问该租户")

    members = await list_tenant_members(tenant_id)
    return TenantMemberListResponse(
        members=[
            TenantMemberResponse(
                user_id=m.user_id,
                username=m.username,
                display_name=m.display_name,
                email=m.email,
                role=m.role,
                joined_at=m.joined_at,
            )
            for m in members
        ]
    )


@router.post("/{tenant_id}/switch", response_model=TenantSwitchResponse)
async def switch_tenant(
    tenant_id: int,
    request: Request,
    response: Response,
) -> TenantSwitchResponse:
    """切换到指定租户（路径参数版）：重新签发包含新 tenant_id 的 JWT。"""
    return await _do_switch_tenant(tenant_id, request, response)


@router.post("/switch", response_model=TenantSwitchResponse)
async def switch_tenant_by_body(
    body: TenantSwitchRequest,
    request: Request,
    response: Response,
) -> TenantSwitchResponse:
    """切换到指定租户（Body 版）：重新签发包含新 tenant_id 的 JWT。"""
    return await _do_switch_tenant(body.tenant_id, request, response)


async def _do_switch_tenant(
    tenant_id: int,
    request: Request,
    response: Response,
) -> TenantSwitchResponse:
    """切换租户的核心逻辑：验证权限 → 更新 DB → 重发 JWT + Cookie。"""
    from app.tenants import set_tenant_id as _set_tid

    user_id, username = _require_auth()

    # 先检查租户是否存在
    tenant = await get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")

    # 验证访问权限（系统租户模式下跳过权限检查）
    from app.tenants import is_system_tenant
    if not is_system_tenant() and not await user_has_tenant_access(user_id, tenant_id):
        raise HTTPException(status_code=403, detail="无权访问该租户")

    # 更新用户当前活跃租户（持久化到 DB）
    await add_user_to_tenant(user_id, tenant_id)

    # 更新 ContextVar
    _set_tid(tenant_id)

    # 构建 user dict 用于签发 token（需要 tenant_id）
    from app.auth import _users_cache
    user = _users_cache.get(username)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")

    # 同步更新内存缓存中的 tenant_id，避免 refresh token 使用旧值
    _users_cache[username] = {**user, "tenant_id": tenant_id}
    user_with_tenant = _users_cache[username]

    # 签发新 token
    access_token = create_access_token(user_with_tenant)
    refresh_token = create_refresh_token(user_with_tenant)
    csrf_token = generate_csrf_token()

    # 更新 Cookie
    _set_auth_cookies(response, access_token, refresh_token, csrf_token)

    # 构造返回的 tenants 列表
    tenants = await list_user_tenants(user_id)
    tenant_list = [
        {"id": t.id, "name": t.name, "slug": t.slug, "role": (ROLE_OWNER if t.owner_id == user_id else ROLE_MEMBER), "plan": t.plan}
        for t in tenants
    ]
    user_info = {
        "id": user_id,
        "username": username,
        "role": user.get("role", "user"),
        "display_name": user.get("display_name", username),
        "tenant_id": tenant_id,
        "tenant": {"id": tenant.id, "name": tenant.name, "slug": tenant.slug, "plan": tenant.plan},
        "tenants": tenant_list,
    }

    logger.info("用户 %s 切换到租户 %s(id=%d)", username, tenant.name, tenant.id)

    return TenantSwitchResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=JWT_EXPIRE_SECONDS,
        csrf_token=csrf_token,
        tenant=_tenant_to_response(tenant, user_id),
        user=user_info,
    )


@router.get("/{tenant_id}/settings", response_model=TenantSettingsResponse)
async def get_tenant_settings(tenant_id: int, request: Request) -> TenantSettingsResponse:
    """获取租户级配置覆盖（仅返回白名单字段，脱敏 API Key）。"""
    user_id, _ = _require_auth()

    tenant = await get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")

    from app.tenants import is_system_tenant
    if not is_system_tenant() and not await user_has_tenant_access(user_id, tenant_id):
        raise HTTPException(status_code=403, detail="无权访问该租户")

    from app.tenants.settings_override import OVERRIDABLE_KEYS, _filter_overrides
    current = tenant.settings or {}
    filtered = _filter_overrides(current if isinstance(current, dict) else {})
    # 脱敏：api_key 字段仅显示前后 4 位
    masked: dict = {}
    for k, v in filtered.items():
        if k.endswith("_api_key") and isinstance(v, str) and len(v) > 8:
            masked[k] = v[:4] + "****" + v[-4:]
        else:
            masked[k] = v
    # 确保返回所有白名单字段（未设置的用 None 占位）
    for k in OVERRIDABLE_KEYS:
        masked.setdefault(k, None)
    return TenantSettingsResponse(settings=masked)


@router.patch("/{tenant_id}/settings", response_model=TenantSettingsResponse)
async def update_tenant_settings_endpoint(
    tenant_id: int,
    body: TenantSettingsUpdateRequest,
    request: Request,
) -> TenantSettingsResponse:
    """更新租户级配置覆盖（部分更新，仅 owner 可操作）。"""
    user_id, _ = _require_auth()

    tenant = await get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")

    from app.tenants import is_system_tenant
    if not is_system_tenant() and not await is_tenant_owner(user_id, tenant_id):
        raise HTTPException(status_code=403, detail="仅租户所有者可修改配置")

    patch = body.model_dump(exclude_unset=True, exclude_none=True)
    try:
        from app.tenants.settings_override import update_tenant_settings
        updated = await update_tenant_settings(tenant_id, patch)
    except Exception as e:
        logger.exception("更新租户 settings 失败")
        raise HTTPException(status_code=400, detail=f"更新失败: {e}") from e

    logger.info("用户 %s 更新租户 %d 的 settings, keys=%s", user_id, tenant_id, list(patch.keys()))
    return TenantSettingsResponse(settings=updated)
