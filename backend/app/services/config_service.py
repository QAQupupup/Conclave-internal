"""多层配置合并服务：6 层优先级合并。

优先级从低到高（后层覆盖前层）：
1. 代码默认值（BaseSettings 字段默认值）
2. 环境变量（BaseSettings 自动读取）
3. 系统级设置（system_settings 表 / 全局 DB 配置）
4. Team 级配置（tenants.settings JSONB，已有）
5. 个人配置（user_settings KV 表，新增）
6. 请求运行时覆盖（API 参数 / CLI args，调用方传入）

白名单机制：
- 各层只允许覆盖白名单内的字段，防止敏感配置（database_url/secret_key 等）被覆盖
- Team 层可设置 locked_fields，锁定的字段个人层无法覆盖

缓存策略：
- Team 配置缓存 60s（复用现有 settings_override 缓存）
- 个人配置缓存 30s（避免高频 DB 查询）
- 系统配置缓存 120s
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, cast

from app.config import settings as _settings
from app.tenants.settings_override import (
    OVERRIDABLE_KEYS,
    get_cached_overrides,
    load_tenant_overrides,
)
from app.tenants.settings_override import (
    invalidate_cache as _invalidate_team_cache,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 白名单定义
# ---------------------------------------------------------------------------

# 个人配置允许覆盖的键（子集于 Team 白名单）
PERSONAL_OVERRIDABLE_KEYS: set[str] = {
    "llm_model",
    "llm_base_url",
    "embed_model",
    "rerank_model",
    "web_search_mode",
    # UI/个人偏好
    "ui_theme",
    "ui_language",
    "default_meeting_template",
    "notification_enabled",
}

# 系统级可覆盖键（基础设施配置，只有 system_admin 可改）
SYSTEM_OVERRIDABLE_KEYS: set[str] = {
    "llm_api_key",
    "llm_base_url",
    "llm_model",
    "llm_provider",
    "embed_api_key",
    "embed_base_url",
    "embed_model",
    "embed_provider",
    "rerank_api_key",
    "rerank_base_url",
    "rerank_model",
    "rerank_provider",
    "web_search_api_key",
    "web_search_mode",
    # 系统级功能开关
    "allow_user_create_tenant",
    "default_team_role",
    "max_meetings_per_user",
    # 阶段模型分配（为会议流水线各阶段指定模型）
    "stage_model_clarify",
    "stage_model_intra_team",
    "stage_model_cross_team",
    "stage_model_evidence_check",
    "stage_model_arbitrate",
    "stage_model_produce",
    # 基础设施配置
    "vector_db_provider",
    "vector_db_url",
    "vector_db_collection",
    "max_agents",
    "max_meeting_duration",
    "enable_public_registration",
    "default_temperature",
}

# Team 权限配置（哪些角色可以发起会议等）
TEAM_PERMISSION_KEYS: set[str] = {
    "can_create_meeting",
    "can_invite_member",
    "can_manage_roles",
    "can_edit_team_settings",
    "can_view_all_meetings",
}

# 默认 Team 权限（角色 -> 权限列表）
DEFAULT_TEAM_PERMISSIONS: dict[str, list[str]] = {
    "owner": ["*"],  # 所有权限
    "maintainer": [
        "can_create_meeting",
        "can_invite_member",
        "can_edit_team_settings",
        "can_view_all_meetings",
    ],
    "member": [
        "can_create_meeting",
        "can_view_all_meetings",
    ],
    "reporter": [
        "can_view_all_meetings",
    ],
    "banned": [],
}

# ---------------------------------------------------------------------------
# 缓存
# ---------------------------------------------------------------------------

_USER_CACHE_TTL = 30.0
_SYS_CACHE_TTL = 120.0
_user_cache: dict[tuple[int, int], tuple[float, dict[str, Any]]] = {}  # (tid, uid) -> (expire, data)
_sys_cache: tuple[float, dict[str, Any]] | None = None


# ---------------------------------------------------------------------------
# 类型转换工具
# ---------------------------------------------------------------------------


def _coerce_value(value: str, value_type: str) -> Any:
    """将字符串值转换为目标类型。"""
    if value_type == "string":
        return value
    if value_type == "int":
        try:
            return int(value)
        except (ValueError, TypeError):
            return value
    if value_type == "float":
        try:
            return float(value)
        except (ValueError, TypeError):
            return value
    if value_type == "bool":
        return value.lower() in ("true", "1", "yes", "on")
    if value_type == "json":
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


# ---------------------------------------------------------------------------
# 各层加载器
# ---------------------------------------------------------------------------


def _get_defaults() -> dict[str, Any]:
    """第 1+2 层：代码默认值 + 环境变量（通过 settings 单例获取）。"""
    s = _settings
    return {
        "llm_api_key": s.llm_api_key,
        "llm_base_url": s.llm_base_url,
        "llm_model": s.llm_model,
        "embed_api_key": s.embed_api_key,
        "embed_base_url": s.embed_base_url,
        "embed_model": s.embed_model,
        "rerank_api_key": s.rerank_api_key,
        "rerank_base_url": s.rerank_base_url,
        "rerank_model": s.rerank_model,
        "web_search_api_key": s.web_search_api_key,
        "web_search_mode": s.web_search_mode,
    }


async def _load_system_settings() -> dict[str, Any]:
    """第 3 层：系统级 DB 配置（admin 可修改的全局默认）。"""
    global _sys_cache
    now = time.monotonic()
    if _sys_cache is not None and _sys_cache[0] > now:
        return _sys_cache[1]

    try:
        from sqlalchemy import text

        from app.db.engine import async_session_factory

        async with async_session_factory() as session:
            result = await session.execute(text("SELECT key, value, value_type FROM system_settings"))
            rows = result.fetchall()
            data: dict[str, Any] = {}
            for row in rows:
                key, value, vtype = row[0], row[1], row[2]
                if key in SYSTEM_OVERRIDABLE_KEYS:
                    data[key] = _coerce_value(value, vtype or "string")
            _sys_cache = (now + _SYS_CACHE_TTL, data)
            return data
    except Exception as e:
        logger.warning("加载系统配置失败，使用环境变量默认: %s: %s", type(e).__name__, str(e)[:200])
        _sys_cache = (now + 10.0, {})
        return {}


async def _load_personal_settings(user_id: int | None) -> dict[str, Any]:
    """第 5 层：个人配置（user_settings KV 表）。"""
    if user_id is None:
        return {}

    # 使用 tenant_id=-1 作为全局缓存 key（个人配置不按租户隔离，但查询时按 user_id）
    cache_key = (-1, user_id)
    now = time.monotonic()
    entry = _user_cache.get(cache_key)
    if entry is not None and entry[0] > now:
        return entry[1]

    try:
        from sqlalchemy import text

        from app.db.engine import async_session_factory

        async with async_session_factory() as session:
            result = await session.execute(
                text("SELECT key, value, value_type FROM user_settings WHERE user_id = :uid"),
                {"uid": user_id},
            )
            rows = result.fetchall()
            data: dict[str, Any] = {}
            for row in rows:
                key, value, vtype = row[0], row[1], row[2]
                if key in PERSONAL_OVERRIDABLE_KEYS:
                    data[key] = _coerce_value(value, vtype or "string")
            _user_cache[cache_key] = (now + _USER_CACHE_TTL, data)
            return data
    except Exception as e:
        logger.warning("加载用户 %s 个人配置失败: %s: %s", user_id, type(e).__name__, str(e)[:200])
        return {}


def load_team_permissions(team_settings: dict[str, Any]) -> dict[str, list[str]]:
    """从 Team settings 中提取权限配置，缺失则用默认值。"""
    perms_raw = team_settings.get("permissions", {})
    if not isinstance(perms_raw, dict):
        return dict(DEFAULT_TEAM_PERMISSIONS)

    result: dict[str, list[str]] = {}
    for role, default_perms in DEFAULT_TEAM_PERMISSIONS.items():
        role_perms = perms_raw.get(role)
        if isinstance(role_perms, list):
            result[role] = role_perms
        else:
            result[role] = list(default_perms)
    return result


def get_locked_fields(team_settings: dict[str, Any]) -> set[str]:
    """从 Team settings 中提取锁定字段（个人无法覆盖）。"""
    locked = team_settings.get("locked_fields", [])
    if isinstance(locked, list):
        return {k for k in locked if k in OVERRIDABLE_KEYS}
    return set()


# ---------------------------------------------------------------------------
# 核心合并逻辑
# ---------------------------------------------------------------------------


async def get_effective_config(
    tenant_id: int | None = None,
    user_id: int | None = None,
    runtime_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """获取 6 层合并后的有效配置。

    Args:
        tenant_id: Team ID（None 表示仅系统级）
        user_id: 用户 ID（None 表示未登录，跳过个人层）
        runtime_overrides: 请求级覆盖（最高优先级）

    Returns:
        合并后的配置字典，包含所有可覆盖字段
    """
    # Layer 1+2: 代码默认值 + 环境变量
    config = _get_defaults()

    # Layer 3: 系统级 DB 配置
    sys_settings = await _load_system_settings()
    _deep_merge(config, sys_settings)

    # Layer 4: Team 级配置
    team_settings: dict[str, Any] = {}
    team_permissions: dict[str, list[str]] = dict(DEFAULT_TEAM_PERMISSIONS)
    locked_fields: set[str] = set()
    if tenant_id is not None:
        team_raw = await load_tenant_overrides(tenant_id)
        team_settings = team_raw if isinstance(team_raw, dict) else {}
        _deep_merge(config, team_settings)
        team_permissions = load_team_permissions(team_settings)
        locked_fields = get_locked_fields(team_settings)

    # Layer 5: 个人配置（排除 Team 锁定的字段）
    if user_id is not None:
        personal = await _load_personal_settings(user_id)
        for k, v in personal.items():
            if k not in locked_fields:
                config[k] = v

    # Layer 6: 请求级覆盖（最高优先级，但仍然受白名单约束）
    if runtime_overrides:
        for k, v in runtime_overrides.items():
            if k in OVERRIDABLE_KEYS or k in SYSTEM_OVERRIDABLE_KEYS:
                config[k] = v

    # 附加元信息
    config["_team_permissions"] = team_permissions
    config["_locked_fields"] = list(locked_fields)

    return config


def get_effective_config_sync(
    tenant_id: int | None = None,
) -> dict[str, Any]:
    """同步版本：只使用缓存数据（Layer 1+2+4），用于无法 await 的上下文。"""
    config = _get_defaults()
    if tenant_id is not None:
        team_overrides = get_cached_overrides(tenant_id)
        _deep_merge(config, team_overrides)
    return config


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    """浅合并 override 到 base（in-place）。空字符串/None 视为未设置。"""
    for k, v in override.items():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        base[k] = v


# ---------------------------------------------------------------------------
# 权限检查：某个角色在 Team 中是否有某权限
# ---------------------------------------------------------------------------


def role_has_permission(role: str, permission: str, team_permissions: dict[str, list[str]] | None = None) -> bool:
    """检查指定角色是否拥有某项权限。

    Args:
        role: Team 角色 (owner/maintainer/member/reporter/banned)
        permission: 权限名 (can_create_meeting 等)
        team_permissions: Team 权限配置（None 则用默认值）
    """
    perms = team_permissions or DEFAULT_TEAM_PERMISSIONS
    role_perms = perms.get(role, [])
    return "*" in role_perms or permission in role_perms


# ---------------------------------------------------------------------------
# 个人配置 CRUD
# ---------------------------------------------------------------------------


async def set_personal_setting(user_id: int, key: str, value: Any, value_type: str = "string") -> None:
    """设置个人配置项。自动类型转换和白名单检查。"""
    if key not in PERSONAL_OVERRIDABLE_KEYS:
        raise ValueError(f"不允许设置配置项: {key}")

    if value_type == "json" and not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    elif not isinstance(value, str):
        value = str(value)

    from datetime import datetime

    from sqlalchemy import text

    from app.db.engine import async_session_factory

    async with async_session_factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO user_settings (user_id, key, value, value_type, updated_at)
                VALUES (:uid, :key, :val, :vtype, :now)
                ON CONFLICT(user_id, key) DO UPDATE SET
                    value = excluded.value,
                    value_type = excluded.value_type,
                    updated_at = excluded.updated_at
                """
            ),
            {
                "uid": user_id,
                "key": key,
                "val": value,
                "vtype": value_type,
                "now": datetime.now(),
            },
        )
        await session.commit()

    # 失效个人缓存
    _invalidate_user_cache(user_id)


async def delete_personal_setting(user_id: int, key: str) -> bool:
    """删除个人配置项，返回是否删除了记录。"""
    from sqlalchemy import CursorResult, text

    from app.db.engine import async_session_factory

    async with async_session_factory() as session:
        result = await session.execute(
            text("DELETE FROM user_settings WHERE user_id = :uid AND key = :key"),
            {"uid": user_id, "key": key},
        )
        await session.commit()
        deleted = cast(CursorResult, result).rowcount > 0

    if deleted:
        _invalidate_user_cache(user_id)
    return deleted


async def get_all_personal_settings(user_id: int) -> dict[str, Any]:
    """获取用户的所有个人配置（类型转换后的 dict）。"""
    from sqlalchemy import text

    from app.db.engine import async_session_factory

    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT key, value, value_type FROM user_settings WHERE user_id = :uid"),
            {"uid": user_id},
        )
        rows = result.fetchall()
        data: dict[str, Any] = {}
        for row in rows:
            key, value, vtype = row[0], row[1], row[2]
            data[key] = _coerce_value(value, vtype or "string")
        return data


# ---------------------------------------------------------------------------
# 系统配置 CRUD（需 system_admin 权限）
# ---------------------------------------------------------------------------


async def set_system_setting(key: str, value: Any, value_type: str = "string") -> None:
    """设置系统级配置项。"""
    if key not in SYSTEM_OVERRIDABLE_KEYS:
        raise ValueError(f"不允许设置系统配置项: {key}")

    if value_type == "json" and not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    elif not isinstance(value, str):
        value = str(value)

    from datetime import datetime

    from sqlalchemy import text

    from app.db.engine import async_session_factory

    async with async_session_factory() as session:
        # 确保 system_settings 表存在（规范定义见 rbac/migrations.py，此处保持兼容）
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS system_settings (
                    key VARCHAR(100) PRIMARY KEY,
                    value TEXT NOT NULL,
                    value_type VARCHAR(20) NOT NULL DEFAULT 'string',
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        # 补加缺失列（兼容不同初始化路径）
        await session.execute(
            text("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW()")
        )
        await session.execute(
            text(
                """
                INSERT INTO system_settings (key, value, value_type, updated_at, created_at)
                VALUES (:key, :val, :vtype, :now, :now)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    value_type = excluded.value_type,
                    updated_at = excluded.updated_at
                """
            ),
            {"key": key, "val": value, "vtype": value_type, "now": datetime.now()},
        )
        await session.commit()

    _invalidate_system_cache()


async def get_all_system_settings() -> dict[str, Any]:
    """获取所有系统配置。"""
    from sqlalchemy import text

    from app.db.engine import async_session_factory

    async with async_session_factory() as session:
        # 确保 system_settings 表存在（规范定义见 rbac/migrations.py，此处保持兼容）
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS system_settings (
                    key VARCHAR(100) PRIMARY KEY,
                    value TEXT NOT NULL,
                    value_type VARCHAR(20) NOT NULL DEFAULT 'string',
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(
            text("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW()")
        )
        result = await session.execute(text("SELECT key, value, value_type FROM system_settings"))
        rows = result.fetchall()
        data: dict[str, Any] = {}
        for row in rows:
            key, value, vtype = row[0], row[1], row[2]
            data[key] = _coerce_value(value, vtype or "string")
        return data


# ---------------------------------------------------------------------------
# Team 权限配置更新
# ---------------------------------------------------------------------------


async def update_team_permissions(tenant_id: int, role_permissions: dict[str, list[str]]) -> dict[str, Any]:
    """更新 Team 的角色权限配置。

    只允许修改 TEAM_PERMISSION_KEYS 内的权限。
    """
    # 验证权限名
    for role, perms in role_permissions.items():
        if role not in DEFAULT_TEAM_PERMISSIONS:
            raise ValueError(f"无效角色: {role}")
        for p in perms:
            if p != "*" and p not in TEAM_PERMISSION_KEYS:
                raise ValueError(f"无效权限: {p}")

    # 读取现有 settings 并 merge
    import json as _json

    from sqlalchemy import text

    from app.db.engine import async_session_factory

    async with async_session_factory() as session, session.begin():
        result = await session.execute(
            text("SELECT settings FROM tenants WHERE id = :tid FOR UPDATE"),
            {"tid": tenant_id},
        )
        row = result.fetchone()
        if row is None:
            from app.core.exceptions import NotFoundError

            raise NotFoundError(f"租户 {tenant_id} 不存在")
        current = row[0] or {}
        if isinstance(current, str):
            try:
                current = _json.loads(current)
            except Exception:
                current = {}
        if not isinstance(current, dict):
            current = {}
        current["permissions"] = role_permissions
        await session.execute(
            text("UPDATE tenants SET settings = CAST(:s AS JSONB) WHERE id = :tid"),
            {"tid": tenant_id, "s": _json.dumps(current, ensure_ascii=False)},
        )

    _invalidate_team_cache(tenant_id)
    return role_permissions


async def update_team_locked_fields(tenant_id: int, locked_fields: list[str]) -> list[str]:
    """设置 Team 锁定字段（个人无法覆盖这些字段）。"""
    valid_fields = [f for f in locked_fields if f in OVERRIDABLE_KEYS]

    import json as _json

    from sqlalchemy import text

    from app.db.engine import async_session_factory

    async with async_session_factory() as session, session.begin():
        result = await session.execute(
            text("SELECT settings FROM tenants WHERE id = :tid FOR UPDATE"),
            {"tid": tenant_id},
        )
        row = result.fetchone()
        if row is None:
            from app.core.exceptions import NotFoundError

            raise NotFoundError(f"租户 {tenant_id} 不存在")
        current = row[0] or {}
        if isinstance(current, str):
            try:
                current = _json.loads(current)
            except Exception:
                current = {}
        if not isinstance(current, dict):
            current = {}
        current["locked_fields"] = valid_fields
        await session.execute(
            text("UPDATE tenants SET settings = CAST(:s AS JSONB) WHERE id = :tid"),
            {"tid": tenant_id, "s": _json.dumps(current, ensure_ascii=False)},
        )

    _invalidate_team_cache(tenant_id)
    return valid_fields


# ---------------------------------------------------------------------------
# 缓存失效
# ---------------------------------------------------------------------------


def _invalidate_user_cache(user_id: int) -> None:
    """失效指定用户的个人配置缓存。"""
    keys_to_remove = [k for k in _user_cache if k[1] == user_id]
    for k in keys_to_remove:
        _user_cache.pop(k, None)


def _invalidate_system_cache() -> None:
    """失效系统配置缓存。"""
    global _sys_cache
    _sys_cache = None


def get_cached_system_settings() -> dict[str, Any]:
    """同步读取系统配置缓存（供无法 await 的调用点使用，如 LLM 客户端 _resolve_config）。

    缓存由 _load_system_settings() 异步填充（TTL 120s）。
    缓存未命中或过期时返回空 dict，调用方应回退到 settings 默认值。
    """
    if _sys_cache is None:
        return {}
    expire_ts, data = _sys_cache
    if time.monotonic() > expire_ts:
        return {}
    return data


async def refresh_system_cache() -> dict[str, Any]:
    """强制刷新系统配置缓存并返回最新数据。供 API 路由在更新配置后调用。"""
    _invalidate_system_cache()
    return await _load_system_settings()


def invalidate_config_cache(tenant_id: int | None = None, user_id: int | None = None) -> None:
    """统一缓存失效入口。"""
    if tenant_id is not None:
        _invalidate_team_cache(tenant_id)
    if user_id is not None:
        _invalidate_user_cache(user_id)
    if tenant_id is None and user_id is None:
        _invalidate_team_cache()
        _user_cache.clear()
        _invalidate_system_cache()
