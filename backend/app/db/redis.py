"""Redis 客户端管理。

提供 lifespan 初始化 + FastAPI Depends 注入。
"""
from __future__ import annotations

import redis.asyncio as aioredis
from fastapi import FastAPI, Request

from app.config import settings

_redis: aioredis.Redis | None = None


async def init_redis(app: FastAPI) -> None:
    """在 lifespan 启动阶段初始化 Redis 连接池。"""
    global _redis
    try:
        _redis = await aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
            socket_keepalive=True,
            socket_connect_timeout=5,
            retry_on_timeout=True,
        )
        await _redis.ping()
        app.state.redis = _redis
    except Exception:
        # Redis 不可用时降级：不阻塞启动
        _redis = None
        app.state.redis = None


async def close_redis(app: FastAPI) -> None:
    """在 lifespan 关闭阶段释放 Redis 连接。"""
    global _redis
    if _redis:
        await _redis.close()
        _redis = None


async def get_redis(request: Request) -> aioredis.Redis | None:
    """FastAPI 依赖注入：获取 Redis 客户端（可能为 None，调用方需处理）。"""
    return request.app.state.redis