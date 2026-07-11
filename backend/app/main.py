# FastAPI 入口：挂载 routers，CORS，lifespan
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db_legacy import init_db
from app.logging_config import setup_logging
from app.middleware import setup_trace_middleware
from app.db.redis import init_redis, close_redis
from app.db.engine import async_session_factory
from app.db.base import Base
from sqlalchemy import text
from app.net_auth import init_auth_table
from app.routers import agent_roles as agent_roles_router
from app.routers import documents as documents_router
from app.routers import meetings as meetings_router
from app.routers import metrics as metrics_router
from app.routers import net_auth as net_auth_router
from app.routers import preferences as preferences_router
from app.routers import regression as regression_router
from app.routers import workspace as workspace_router
from app.routers import ws as ws_router

# 应用启动时初始化日志系统
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库 + 崩溃恢复 + 后台指标采集"""
    # 旧 SQLite 兼容层（逐步移除）
    init_db()
    init_auth_table()

    # 新 PostgreSQL 表结构初始化（SQLAlchemy ORM）
    from app.config import settings
    if settings.db_mode == "postgresql":
        async with async_session_factory() as session:
            async with session.bind.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

    # 日志：当前持久化后端
    import logging as _logging
    _logger = _logging.getLogger("lifespan")
    _logger.info("db_backend=%s | db_mode=%s", settings.db_backend, settings.db_mode)

    # Redis 初始化（不可用时降级，不阻塞启动）
    await init_redis(app)

    # 崩溃恢复：把上次未完成的 RUNNING 会议标记为 PAUSED
    from app.orchestrator.runner import recover_crashed_meetings
    recovered = recover_crashed_meetings()
    if recovered:
        import logging
        logging.getLogger("lifespan").info("崩溃恢复：%d 个会议标记为 PAUSED", len(recovered))
    # 启动后台指标采集
    from app.observability.metrics_store import get_metrics_store
    get_metrics_store().start()

    # 沙箱预热：启动时检测 Docker 可用性 + 预拉取镜像
    # 不阻塞启动（作为后台任务），镜像拉取可能耗时较长
    from app.sandbox import warmup_sandbox
    import asyncio
    asyncio.create_task(warmup_sandbox())

    yield
    # 停止后台指标采集
    await get_metrics_store().stop()
    # 关闭 Redis
    await close_redis(app)


def create_app() -> FastAPI:
    """构造 FastAPI 应用"""
    app = FastAPI(
        title="Conclave",
        description="会议型多智能体系统后端（迭代二）",
        version="0.2.0",
        lifespan=lifespan,
    )
    # CORS：开发期全放开，生产环境应限制 origins
    _cors_origins_raw = os.environ.get("CONCLAVE_CORS_ORIGINS", "")
    _cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()] or ["*"]
    # CORS 规范禁止 allow_origins=["*"] + allow_credentials=True
    # 当 origins 为通配 * 时不允许 credentials；指定了具体源时才允许
    _allow_credentials = _cors_origins != ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # API 认证中间件：基于 token 的认证
    from app.middleware import setup_auth_middleware
    setup_auth_middleware(app)
    # 请求追踪中间件：分配 request_id，注入日志
    setup_trace_middleware(app)
    # 挂载路由
    app.include_router(agent_roles_router.router)
    app.include_router(meetings_router.router)
    app.include_router(documents_router.router)
    app.include_router(metrics_router.router)
    app.include_router(workspace_router.router)
    app.include_router(ws_router.router)
    app.include_router(regression_router.router)
    app.include_router(net_auth_router.router)
    app.include_router(preferences_router.router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, Any]:
        """健康检查：检查关键依赖可用性"""
        checks: dict[str, str] = {}

        # SQLite 检查（旧兼容层）
        try:
            from app.db_legacy import _connect
            conn = _connect()
            conn.execute("SELECT 1")
            conn.close()
            checks["sqlite"] = "ok"
        except Exception as e:
            checks["sqlite"] = f"error: {e}"

        # PostgreSQL 检查
        try:
            from app.config import settings
            if settings.db_mode == "postgresql":
                async with async_session_factory() as session:
                    await session.execute(text("SELECT 1"))
                checks["postgresql"] = "ok"
            else:
                checks["postgresql"] = "disabled"
        except Exception as e:
            checks["postgresql"] = f"error: {e}"

        # Redis 检查
        try:
            import redis.asyncio as aioredis
            r = await aioredis.from_url(settings.redis_url, socket_connect_timeout=3)
            await r.ping()
            await r.close()
            checks["redis"] = "ok"
        except Exception as e:
            checks["redis"] = f"error: {type(e).__name__}"

        # Qdrant 检查
        try:
            import httpx
            async with httpx.AsyncClient(timeout=3) as client:
                qdrant_url = os.environ.get("CONCLAVE_QDRANT_URL", os.environ.get("QDRANT_URL", "http://qdrant:6333"))
                resp = await client.get(f"{qdrant_url}/healthz")
                checks["qdrant"] = "ok" if resp.status_code == 200 else f"error: {resp.status_code}"
        except Exception as e:
            checks["qdrant"] = f"error: {type(e).__name__}"

        # Docker 检查（async 避免阻塞事件循环）
        try:
            import asyncio as _aio
            proc = await _aio.create_subprocess_exec(
                "docker", "info",
                stdout=_aio.subprocess.DEVNULL,
                stderr=_aio.subprocess.DEVNULL,
            )
            await _aio.wait_for(proc.wait(), timeout=3)
            checks["docker"] = "ok" if proc.returncode == 0 else "error: docker unavailable"
        except Exception as e:
            checks["docker"] = f"error: {type(e).__name__}"

        # LLM 熔断器状态
        try:
            from app.agents.llm import get_circuit_breaker
            cb = get_circuit_breaker()
            checks["llm_circuit"] = cb.state
        except Exception:
            checks["llm_circuit"] = "unknown"

        # half_open 表示正在尝试恢复，视为可用
        _healthy_vals = {"ok", "closed", "half_open"}
        all_ok = all(v in _healthy_vals for v in checks.values())
        return {"status": "ok" if all_ok else "degraded", "checks": checks}

    @app.on_event("shutdown")
    async def _shutdown_event() -> None:
        """应用关闭时清理资源"""
        try:
            from app.tools.playwright_search import close_playwright_search
            await close_playwright_search()
        except Exception:
            pass
        try:
            from app.tools.browser_tool import close_browser_tool
            await close_browser_tool()
        except Exception:
            pass

    @app.get("/debug/auth-info", tags=["debug"])
    async def debug_auth_info() -> dict[str, Any]:
        """[CON-03 修复] 公开的认证信息查询端点（仅返回 dev token，给前端自动发现用）。

        安全考虑：
        - 仅当 CONCLAVE_API_TOKEN 未设置（dev 模式）才返回明文 token
        - 生产环境（设置了 env token）只返回认证状态，不泄露 token
        - 前端用此 token 自动填充 Authorization header
        """
        from app.middleware import _API_TOKEN, _DEV_TOKEN, get_dev_token_info

        info = get_dev_token_info()
        # 仅 dev 模式返回明文 token
        if not _API_TOKEN:
            info["token"] = _DEV_TOKEN
            info["note"] = "dev 模式自动发现；生产环境必须设置 CONCLAVE_API_TOKEN"
        else:
            info["token"] = None
            info["note"] = "生产模式：使用 CONCLAVE_API_TOKEN env 值"
        return info

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
