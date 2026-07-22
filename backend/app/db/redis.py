"""Redis 客户端管理。

提供 lifespan 初始化 + 循环感知的客户端获取。

遵循 AGENTS.md §4.1：模块级单例必须循环感知——检测到循环已关闭/切换时
自动丢弃旧连接，返回 None 让调用方降级，避免 "attached to a different loop"。
"""

from __future__ import annotations

import asyncio
import contextlib
import threading

import redis.asyncio as aioredis
from fastapi import FastAPI, Request

from app.config import settings

_redis: aioredis.Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


def _is_usable(client: aioredis.Redis | None, loop: asyncio.AbstractEventLoop | None) -> bool:
    """判断缓存的 Redis 客户端是否在当前循环下可用。"""
    if client is None or loop is None:
        return False
    if loop.is_closed():
        return False
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        # 没有运行中的循环——同步调用方，不能使用异步 Redis 客户端
        return False
    return current_loop is loop


async def init_redis(app: FastAPI) -> None:
    """在 lifespan 启动阶段初始化 Redis 连接池。"""
    global _redis, _redis_loop
    try:
        loop = asyncio.get_running_loop()
        client = await aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
            socket_keepalive=True,
            socket_connect_timeout=5,
            retry_on_timeout=True,
        )
        await client.ping()
        with _lock:
            _redis = client
            _redis_loop = loop
        app.state.redis = client
    except Exception:
        # Redis 不可用时降级：不阻塞启动
        with _lock:
            _redis = None
            _redis_loop = None
        app.state.redis = None


async def close_redis(app: FastAPI) -> None:
    """在 lifespan 关闭阶段释放 Redis 连接。"""
    global _redis, _redis_loop
    client_to_close = None
    with _lock:
        if _redis is not None:
            client_to_close = _redis
            _redis = None
            _redis_loop = None
    app.state.redis = None
    if client_to_close is not None:
        with contextlib.suppress(Exception):
            await client_to_close.close()


async def get_redis(request: Request) -> aioredis.Redis | None:
    """FastAPI 依赖注入：获取 Redis 客户端（可能为 None，调用方需处理）。"""
    return _safe_get_client()


def _safe_get_client() -> aioredis.Redis | None:
    """循环感知地获取 Redis 客户端。

    若当前线程没有运行中的事件循环，或缓存的客户端绑定到不同/已关闭循环，
    返回 None（调用方应静默降级），避免 "attached to a different loop" 错误。
    """
    global _redis, _redis_loop
    with _lock:
        if _is_usable(_redis, _redis_loop):
            return _redis
        # 客户端不可用（循环已关闭/切换）：丢弃引用，返回 None 让调用方降级
        if _redis is not None:
            # 只清除引用，不尝试跨循环 close（会抛 RuntimeError）
            _redis = None
            _redis_loop = None
        return None


def get_redis_client() -> aioredis.Redis | None:
    """获取 Redis 客户端（模块级访问，不经过 FastAPI Depends）。

    用于事件总线等非请求场景访问 Redis。可能返回 None（Redis 不可用或循环不匹配时），
    调用方必须处理 None 的情况（静默降级为纯内存模式）。
    """
    return _safe_get_client()
