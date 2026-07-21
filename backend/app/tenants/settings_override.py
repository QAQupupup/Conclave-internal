"""租户级配置覆盖：从 tenants.settings JSONB 读取并合并到全局 settings。

设计原则：
1. 白名单机制：只允许覆盖一组明确列出的配置项（LLM/Embedding/Reranker/WebSearch），
   禁止租户覆盖 database_url/redis_url/secret_key 等基础设施配置。
2. TTL 缓存：租户配置在进程内缓存 60s，避免每次 LLM 调用都查 DB。
3. 显式失效：update_tenant_settings() 写入成功后调用 invalidate_cache() 立即可见。
4. 优雅降级：DB 查询失败时回退到全局配置，不阻断主流程。
5. 同步安全：提供 sync 读缓存方法（返回空 dict 当未加载），供无法 await 的调用点使用。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 白名单：租户可覆盖的配置键 -> 全局 settings 字段名映射
# ---------------------------------------------------------------------------
OVERRIDABLE_KEYS: dict[str, str] = {
    # LLM
    "llm_api_key": "llm_api_key",
    "llm_base_url": "llm_base_url",
    "llm_model": "llm_model",
    # Embedding
    "embed_api_key": "embed_api_key",
    "embed_base_url": "embed_base_url",
    "embed_model": "embed_model",
    # Reranker
    "rerank_api_key": "rerank_api_key",
    "rerank_base_url": "rerank_base_url",
    "rerank_model": "rerank_model",
    # Web search
    "web_search_api_key": "web_search_api_key",
    "web_search_mode": "web_search_mode",
}

# 缓存 TTL（秒）
_CACHE_TTL = 60.0

# tenant_id -> (expire_at, overrides_dict)
_cache: dict[int, tuple[float, dict[str, Any]]] = {}

# 哨兵：标记一次查询失败，避免高频 DB 重试
_NEGATIVE_CACHE_TTL = 5.0
_cache_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _cache_lock
    if _cache_lock is None:
        try:
            asyncio.get_running_loop()
            # 为当前 loop 新建锁；跨 loop 时自动重建
            _cache_lock = asyncio.Lock()
        except RuntimeError:
            # 无运行 loop，返回一个临时锁（不会被真正使用）
            return asyncio.Lock()
    return _cache_lock


def _filter_overrides(raw: dict[str, Any] | None) -> dict[str, Any]:
    """过滤白名单，只保留允许覆盖的键，并做基本类型校验"""
    if not raw or not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if k not in OVERRIDABLE_KEYS:
            continue
        # 类型校验：字符串字段必须是非空字符串
        if isinstance(v, str):
            if v.strip():
                out[k] = v.strip()
        elif isinstance(v, bool):
            out[k] = v
        # 其他类型（数字等）按需加入，当前白名单都是字符串
    return out


def get_cached_overrides(tenant_id: int | None) -> dict[str, Any]:
    """同步读取缓存；缓存未命中或过期时返回空 dict，不触发 DB 查询。

    用于无法 await 的同步调用点（如某些中间件）。异步调用点应使用 load_tenant_overrides()。
    """
    if tenant_id is None:
        return {}
    entry = _cache.get(tenant_id)
    if entry is None:
        return {}
    expire_at, val = entry
    if time.monotonic() > expire_at:
        return {}
    return val


async def load_tenant_overrides(tenant_id: int | None) -> dict[str, Any]:
    """异步加载租户覆盖配置，带 TTL 缓存。

    优先级：缓存（未过期）> DB 查询 > 全局默认（失败时）。
    """
    if tenant_id is None:
        return {}

    # Fast path：缓存命中且未过期
    entry = _cache.get(tenant_id)
    if entry is not None:
        expire_at, val = entry
        if time.monotonic() <= expire_at:
            return val

    # 慢路径：加锁避免击穿
    lock = _get_lock()
    async with lock:
        # 双检
        entry = _cache.get(tenant_id)
        if entry is not None:
            expire_at, val = entry
            if time.monotonic() <= expire_at:
                return val

        try:
            overrides = await _fetch_from_db(tenant_id)
        except Exception as e:
            logger.warning(
                "加载租户 %s 的 settings 失败，使用全局默认: %s: %s",
                tenant_id,
                type(e).__name__,
                str(e)[:200],
            )
            overrides = {}
            _cache[tenant_id] = (time.monotonic() + _NEGATIVE_CACHE_TTL, {})
            return {}

        filtered = _filter_overrides(overrides)
        _cache[tenant_id] = (time.monotonic() + _CACHE_TTL, filtered)
        return filtered


async def _fetch_from_db(tenant_id: int) -> dict[str, Any]:
    """从 DB 读取 tenants.settings。使用独立 session 以避免循环依赖。"""
    from sqlalchemy import text

    from app.db.engine import async_session_factory

    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT settings FROM tenants WHERE id = :tid"),
            {"tid": tenant_id},
        )
        row = result.fetchone()
        if row is None:
            return {}
        val = row[0] if row else {}
        if isinstance(val, str):
            import json

            try:
                parsed: dict[str, Any] = json.loads(val)
                return parsed
            except Exception:
                return {}
        return val or {}


def invalidate_cache(tenant_id: int | None = None) -> None:
    """失效缓存。tenant_id=None 时清空全部。"""
    if tenant_id is None:
        _cache.clear()
    else:
        _cache.pop(tenant_id, None)


# ---------------------------------------------------------------------------
# 便捷合并函数：给 LLM/Embedding/Reranker 客户端使用
# ---------------------------------------------------------------------------


def resolve_llm_config(
    tenant_id: int | None,
    base_url: str,
    api_key: str,
    model: str,
) -> tuple[str, str, str]:
    """将租户覆盖（若有）合并到默认 LLM 配置。"""
    ov = get_cached_overrides(tenant_id)
    return (
        ov.get("llm_base_url", base_url) or base_url,
        ov.get("llm_api_key", api_key) or api_key,
        ov.get("llm_model", model) or model,
    )


def resolve_embed_config(
    tenant_id: int | None,
    base_url: str,
    api_key: str,
    model: str,
) -> tuple[str, str, str]:
    return (
        (
            ov.get("embed_base_url", base_url) or base_url,
            ov.get("embed_api_key", api_key) or api_key,
            ov.get("embed_model", model) or model,
        )
        if (ov := get_cached_overrides(tenant_id))
        else (base_url, api_key, model)
    )


def resolve_rerank_config(
    tenant_id: int | None,
    base_url: str,
    api_key: str,
    model: str,
) -> tuple[str, str, str]:
    return (
        (
            ov.get("rerank_base_url", base_url) or base_url,
            ov.get("rerank_api_key", api_key) or api_key,
            ov.get("rerank_model", model) or model,
        )
        if (ov := get_cached_overrides(tenant_id))
        else (base_url, api_key, model)
    )


def resolve_web_search_config(
    tenant_id: int | None,
    mode: str,
    api_key: str,
) -> tuple[str, str]:
    ov = get_cached_overrides(tenant_id)
    if not ov:
        return mode, api_key
    return (
        ov.get("web_search_mode", mode) or mode,
        ov.get("web_search_api_key", api_key) or api_key,
    )


# ---------------------------------------------------------------------------
# 写入：供管理 API 调用
# ---------------------------------------------------------------------------


async def update_tenant_settings(tenant_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    """部分更新租户 settings（JSONB merge），成功后失效缓存。

    只允许写入白名单内的键；其他键会被忽略（不影响其他系统字段）。
    """
    filtered = _filter_overrides(patch)

    import json as _json

    from sqlalchemy import text

    from app.db.engine import async_session_factory

    # 读 -> merge -> 写，保证不覆盖其他系统字段（如 quota 等）
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
        current.update(filtered)
        await session.execute(
            text("UPDATE tenants SET settings = CAST(:s AS JSONB) WHERE id = :tid"),
            {"tid": tenant_id, "s": _json.dumps(current, ensure_ascii=False)},
        )

    invalidate_cache(tenant_id)
    # 主动预热缓存
    _cache[tenant_id] = (time.monotonic() + _CACHE_TTL, _filter_overrides(current))
    return _filter_overrides(current)
