"""配置管理 API：系统配置、Team 配置、个人配置、API Key 管理。

端点：
- GET  /api/config/effective              获取当前生效的合并配置
- GET  /api/config/personal               获取个人配置
- PUT  /api/config/personal/{key}         设置个人配置项
- DELETE /api/config/personal/{key}       删除个人配置项
- GET  /api/config/team/{tid}             获取 Team 配置（含权限设置）
- PUT  /api/config/team/{tid}             更新 Team 配置白名单字段
- PUT  /api/config/team/{tid}/permissions 更新 Team 角色权限
- PUT  /api/config/team/{tid}/locked      更新 Team 锁定字段
- GET  /api/config/system                 获取系统配置（仅管理员）
- PUT  /api/config/system/{key}           设置系统配置项（仅管理员）

API Key 管理：
- GET  /api/keys?scope=personal|team|all  列出 API Key
- POST /api/keys                          保存 API Key
- DELETE /api/keys/{provider}/{name}      删除 API Key
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.observability.audit import audit
from app.rbac.enforcer import SYSTEM_DOMAIN
from app.services import config_service, key_store
from app.services.config_service import (
    DEFAULT_TEAM_PERMISSIONS,
    PERSONAL_OVERRIDABLE_KEYS,
    SYSTEM_OVERRIDABLE_KEYS,
    TEAM_PERMISSION_KEYS,
)
from app.tenants.settings_override import OVERRIDABLE_KEYS, update_tenant_settings

router = APIRouter(prefix="/api", tags=["config"])


def _get_auth(request: Request) -> dict[str, Any]:
    auth_user: dict[str, Any] | None = getattr(request.state, "auth_user", None)
    if not auth_user:
        raise HTTPException(status_code=401, detail="未登录")
    return auth_user


def _get_uid_int(auth_user: dict[str, Any]) -> int:
    uid = auth_user.get("uid_int")
    if uid is None:
        uid_str = str(auth_user.get("uid", 0))
        try:
            uid = int(uid_str)
        except (ValueError, TypeError):
            raise HTTPException(status_code=401, detail="无效用户") from None
    return int(uid)


def _is_system_admin(auth_user: dict[str, Any]) -> bool:
    return auth_user.get("system_role") in ("system_owner", "system_admin", "admin")


# ---------------------------------------------------------------------------
# 有效配置（合并后）
# ---------------------------------------------------------------------------


@router.get("/config/effective")
async def get_effective_config(request: Request) -> dict[str, Any]:
    """获取当前上下文的合并后有效配置（用于前端展示）。"""
    auth = _get_auth(request)
    uid = _get_uid_int(auth)
    tid = auth.get("tenant_id")
    tid_int = int(tid) if tid else None

    config = await config_service.get_effective_config(tenant_id=tid_int, user_id=uid)

    # 不返回敏感字段给前端（api_key 只返回是否配置状态）
    safe = {}
    sensitive_keys = {"llm_api_key", "embed_api_key", "rerank_api_key", "web_search_api_key"}
    for k, v in config.items():
        if k.startswith("_"):
            safe[k] = v
        elif k in sensitive_keys:
            safe[k] = "configured" if v else ""
        else:
            safe[k] = v
    return safe


# ---------------------------------------------------------------------------
# 个人配置
# ---------------------------------------------------------------------------


@router.get("/config/personal")
async def get_personal_config(request: Request) -> dict[str, Any]:
    """获取当前用户的所有个人配置。"""
    auth = _get_auth(request)
    uid = _get_uid_int(auth)
    settings = await config_service.get_all_personal_settings(uid)
    return {"settings": settings, "overridable_keys": list(PERSONAL_OVERRIDABLE_KEYS)}


@router.put("/config/personal/{key}")
async def set_personal_config(key: str, request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """设置个人配置项。"""
    auth = _get_auth(request)
    uid = _get_uid_int(auth)

    if key not in PERSONAL_OVERRIDABLE_KEYS:
        raise HTTPException(status_code=400, detail=f"不允许设置配置项: {key}")

    value = body.get("value")
    value_type = body.get("value_type", "string")
    if value is None:
        raise HTTPException(status_code=400, detail="需要 value")

    try:
        await config_service.set_personal_setting(uid, key, value, value_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    audit("config.personal.updated", "success", {"key": key}, user_id=uid)
    return {"key": key, "updated": True}


@router.delete("/config/personal/{key}")
async def delete_personal_config(key: str, request: Request) -> dict[str, Any]:
    """删除个人配置项。"""
    auth = _get_auth(request)
    uid = _get_uid_int(auth)
    deleted = await config_service.delete_personal_setting(uid, key)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"配置项 '{key}' 不存在")
    return {"deleted": key}


# ---------------------------------------------------------------------------
# Team 配置
# ---------------------------------------------------------------------------


@router.get("/config/team/{tid}")
async def get_team_config(tid: int, request: Request) -> dict[str, Any]:
    """获取 Team 配置。需要是 Team 成员。"""
    auth = _get_auth(request)
    my_role = _get_team_role(auth, tid)
    if not _is_system_admin(auth) and not my_role:
        raise HTTPException(status_code=403, detail="无权查看该 Team 配置")

    team = await _get_team_or_404(tid)
    team_settings = team.get("settings", {})
    if not isinstance(team_settings, dict):
        team_settings = {}

    permissions = config_service.load_team_permissions(team_settings)
    locked_fields = config_service.get_locked_fields(team_settings)

    # 过滤敏感字段
    safe_settings = {}
    for k, v in team_settings.items():
        if k in ("llm_api_key", "embed_api_key", "rerank_api_key", "web_search_api_key"):
            safe_settings[k] = "configured" if v else ""
        elif k in ("permissions", "locked_fields"):
            continue
        else:
            safe_settings[k] = v

    return {
        "team_id": tid,
        "settings": safe_settings,
        "permissions": permissions,
        "locked_fields": list(locked_fields),
        "default_permissions": DEFAULT_TEAM_PERMISSIONS,
        "available_permissions": list(TEAM_PERMISSION_KEYS),
        "overridable_keys": list(OVERRIDABLE_KEYS.keys()),
        "can_edit": my_role in ("owner", "maintainer") or _is_system_admin(auth),
    }


@router.put("/config/team/{tid}")
async def update_team_config(tid: int, request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """更新 Team 配置（白名单字段）。需要 owner/maintainer。"""
    auth = _get_auth(request)
    uid = _get_uid_int(auth)
    my_role = _get_team_role(auth, tid)

    if my_role not in ("owner", "maintainer") and not _is_system_admin(auth):
        raise HTTPException(status_code=403, detail="需要 owner 或 maintainer 权限")

    patch = body.get("settings", body)
    if not isinstance(patch, dict):
        raise HTTPException(status_code=400, detail="无效的配置格式")

    try:
        result = await update_tenant_settings(tid, patch)
    except Exception as e:
        if "NotFound" in type(e).__name__:
            raise HTTPException(status_code=404, detail=str(e)) from e
        raise HTTPException(status_code=400, detail=str(e)) from e

    audit("config.team.updated", "success", {"team_id": tid}, user_id=uid)
    return {"updated": True, "settings": result}


@router.put("/config/team/{tid}/permissions")
async def update_team_permissions(tid: int, request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """更新 Team 角色权限配置。仅 owner。"""
    auth = _get_auth(request)
    uid = _get_uid_int(auth)
    my_role = _get_team_role(auth, tid)

    if my_role != "owner" and not _is_system_admin(auth):
        raise HTTPException(status_code=403, detail="仅 Team owner 可修改权限配置")

    perms = body.get("permissions", body)
    if not isinstance(perms, dict):
        raise HTTPException(status_code=400, detail="permissions 必须是对象")

    try:
        result = await config_service.update_team_permissions(tid, perms)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    audit("config.team.permissions_updated", "success", {"team_id": tid}, user_id=uid)
    return {"permissions": result}


@router.put("/config/team/{tid}/locked")
async def update_team_locked_fields(tid: int, request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """设置 Team 锁定字段（个人无法覆盖）。仅 owner。"""
    auth = _get_auth(request)
    uid = _get_uid_int(auth)
    my_role = _get_team_role(auth, tid)

    if my_role != "owner" and not _is_system_admin(auth):
        raise HTTPException(status_code=403, detail="仅 Team owner 可设置锁定字段")

    fields = body.get("locked_fields", [])
    if not isinstance(fields, list):
        raise HTTPException(status_code=400, detail="locked_fields 必须是数组")

    try:
        result = await config_service.update_team_locked_fields(tid, fields)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    audit("config.team.locked_updated", "success", {"team_id": tid, "fields": result}, user_id=uid)
    return {"locked_fields": result}


# ---------------------------------------------------------------------------
# 系统配置（仅管理员）
# ---------------------------------------------------------------------------


@router.get("/config/system")
async def get_system_config(request: Request) -> dict[str, Any]:
    """获取系统配置。仅系统管理员。"""
    auth = _get_auth(request)
    if not _is_system_admin(auth):
        raise HTTPException(status_code=403, detail="需要系统管理员权限")

    # 使用带缓存的 _load_system_settings，顺带为 LLM 客户端的
    # get_cached_system_settings() 同步读取填充缓存
    settings = await config_service._load_system_settings()
    return {
        "settings": settings,
        "overridable_keys": list(SYSTEM_OVERRIDABLE_KEYS),
    }


@router.put("/config/system/{key}")
async def set_system_config(key: str, request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """设置系统配置项。仅系统管理员。"""
    auth = _get_auth(request)
    uid = _get_uid_int(auth)
    if not _is_system_admin(auth):
        raise HTTPException(status_code=403, detail="需要系统管理员权限")

    if key not in SYSTEM_OVERRIDABLE_KEYS:
        raise HTTPException(status_code=400, detail=f"不允许设置系统配置项: {key}")

    value = body.get("value")
    value_type = body.get("value_type", "string")
    if value is None:
        raise HTTPException(status_code=400, detail="需要 value")

    try:
        await config_service.set_system_setting(key, value, value_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # 刷新系统配置缓存，使 LLM/Embedding 客户端立即读到新配置
    await config_service.refresh_system_cache()
    audit("config.system.updated", "success", {"key": key}, user_id=uid)
    return {"key": key, "updated": True}


# ---------------------------------------------------------------------------
# API Key 管理
# ---------------------------------------------------------------------------


@router.get("/keys")
async def list_api_keys(
    request: Request,
    scope: str = Query("all"),
) -> dict[str, Any]:
    """列出 API Key。scope=personal/team/system/all。"""
    auth = _get_auth(request)
    uid = _get_uid_int(auth)

    if scope == "system" and not _is_system_admin(auth):
        raise HTTPException(status_code=403, detail="需要系统管理员权限查看系统 Key")

    keys = await key_store.list_api_keys(scope=scope, user_id=uid)
    return {"items": keys}


@router.post("/keys")
async def save_api_key(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """保存 API Key。

    api_key 可选：为空时仅更新 is_default/base_url（用于一键切换默认 Key）。
    新建 Key 时 api_key 必填（由 key_store.save_api_key 校验）。
    """
    auth = _get_auth(request)
    uid = _get_uid_int(auth)

    provider = (body.get("provider") or "").strip()
    name = (body.get("name") or "default").strip()
    api_key = (body.get("api_key") or "").strip()
    base_url = (body.get("base_url") or "").strip()
    is_default = bool(body.get("is_default", False))
    scope = (body.get("scope") or "team").strip()

    if not provider:
        raise HTTPException(status_code=400, detail="需要 provider")

    # 权限检查
    user_id_param = None
    if scope == "personal":
        user_id_param = uid
    elif scope == "system":
        if not _is_system_admin(auth):
            raise HTTPException(status_code=403, detail="需要系统管理员权限设置系统 Key")
    elif scope == "team":
        my_role = _get_team_role(auth, auth.get("tenant_id"))
        if my_role not in ("owner", "maintainer") and not _is_system_admin(auth):
            raise HTTPException(status_code=403, detail="需要 owner/maintainer 设置 Team Key")
    else:
        raise HTTPException(status_code=400, detail="无效 scope")

    try:
        result = await key_store.save_api_key(
            provider=provider,
            api_key=api_key,
            name=name,
            base_url=base_url,
            is_default=is_default,
            user_id=user_id_param,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # 系统级默认 Key 同步到 system_config，使 LLM/Embedding 客户端可通过
    # get_cached_system_settings() 读到（打通 key_store → system_config → LLM 链路）
    if scope == "system" and is_default:
        try:
            sys_settings = await config_service.get_all_system_settings()
            llm_provider = sys_settings.get("llm_provider", "")
            embed_provider = sys_settings.get("embed_provider", "")
            rerank_provider = sys_settings.get("rerank_provider", "")

            # 获取实际 Key 明文（api_key 为空时从 key_store 解密读取）
            actual_key = api_key
            if not actual_key:
                actual_key = await key_store.get_api_key(provider, name)

            if actual_key:
                if provider == llm_provider:
                    await config_service.set_system_setting("llm_api_key", actual_key)
                    if base_url:
                        await config_service.set_system_setting("llm_base_url", base_url)
                if provider == embed_provider:
                    await config_service.set_system_setting("embed_api_key", actual_key)
                    if base_url:
                        await config_service.set_system_setting("embed_base_url", base_url)
                if provider == rerank_provider:
                    await config_service.set_system_setting("rerank_api_key", actual_key)
                    if base_url:
                        await config_service.set_system_setting("rerank_base_url", base_url)

            # 强制刷新系统配置缓存，使 LLM 客户端立即生效
            await config_service.refresh_system_cache()
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning("同步 Key 到系统配置失败: %s", str(e)[:200])

    audit(
        "api_key.saved",
        "success",
        {"provider": provider, "name": name, "scope": scope},
        user_id=uid,
    )
    return result


@router.delete("/keys/{provider}/{name}")
async def delete_api_key(
    provider: str,
    name: str,
    request: Request,
    scope: str = Query("team"),
) -> dict[str, Any]:
    """删除 API Key。"""
    auth = _get_auth(request)
    uid = _get_uid_int(auth)

    user_id_param = None
    if scope == "personal":
        user_id_param = uid
    elif scope == "system":
        if not _is_system_admin(auth):
            raise HTTPException(status_code=403, detail="需要系统管理员权限")
    elif scope == "team":
        my_role = _get_team_role(auth, auth.get("tenant_id"))
        if my_role not in ("owner", "maintainer") and not _is_system_admin(auth):
            raise HTTPException(status_code=403, detail="需要 owner/maintainer 删除 Team Key")
    else:
        raise HTTPException(status_code=400, detail="无效 scope")

    deleted = await key_store.delete_api_key(provider, name, user_id=user_id_param)
    if not deleted:
        raise HTTPException(status_code=404, detail="Key 不存在")
    audit("api_key.deleted", "success", {"provider": provider, "name": name, "scope": scope}, user_id=uid)
    return {"deleted": True}


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _get_team_role(auth_user: dict[str, Any], tid: int | None) -> str:
    """获取当前用户在 Team 中的角色。"""
    if tid is None:
        return ""
    roles = auth_user.get("roles", ())
    if auth_user.get("domain") == SYSTEM_DOMAIN:
        sys_role = auth_user.get("system_role", "")
        if sys_role == "system_owner":
            return "owner"
        if sys_role in ("system_admin", "admin"):
            return "maintainer"
    return roles[0] if roles else ""


async def _get_team_or_404(tid: int) -> dict[str, Any]:
    from app.services.team_service import get_team

    team = await get_team(tid)
    if not team:
        raise HTTPException(status_code=404, detail="Team 不存在")
    return team
