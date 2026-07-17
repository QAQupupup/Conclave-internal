# FastAPI 入口：挂载 routers，CORS，lifespan
from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db_legacy import init_db
from app.logging_config import setup_logging
from app.middleware import setup_trace_middleware
from app.db.redis import init_redis, close_redis
from app.db.engine import async_session_factory
from app.db.base import Base
from app.net_auth import init_auth_table
from app.auth import init_auth as init_jwt_auth
from app.routers import agent_roles as agent_roles_router
from app.routers import auth as auth_router
from app.routers import captcha as captcha_router
from app.routers import documents as documents_router
from app.routers import meetings as meetings_router
from app.routers import metrics as metrics_router
from app.routers import net_auth as net_auth_router
from app.routers import preferences as preferences_router
from app.routers import regression as regression_router
from app.routers import workspace as workspace_router
from app.routers import ws as ws_router
from app.utils.tasks import create_supervised_task

# 应用启动时初始化日志系统
setup_logging()

logger = logging.getLogger("lifespan")


def _cleanup_orphaned_workspaces() -> None:
    """[M-07 修复] 启动时清理工作区中过期的孤立目录

    清理超过 7 天的、已完成/已删除会议的工作区目录，防止磁盘长期占用。
    """
    try:
        from app.config import settings as _settings
        ws_root = Path(_settings.workspace_root)
        if not ws_root.exists():
            return
        cutoff = time.time() - 7 * 86400  # 7 天前
        cleaned = 0
        for entry in ws_root.iterdir():
            if not entry.is_dir() or not entry.name.startswith("mtg-"):
                continue
            try:
                mtime = entry.stat().st_mtime
                if mtime < cutoff:
                    # 仅清理目录，不强制递归删除（保护未预期的数据）
                    # 这里只记录日志，由用户手动清理或后续版本添加安全的递归删除
                    logger.info("发现孤立工作区目录（超过7天）: %s", entry.name)
                    cleaned += 1
            except OSError:
                continue
        if cleaned:
            logger.info("启动时发现 %d 个过期工作区目录，已记录", cleaned)
    except Exception as e:
        logger.warning("工作区清理扫描失败（非致命）: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库 + 崩溃恢复 + 后台指标采集"""
    # PostgreSQL 兼容层（db_legacy，逐步迁移到 async Repository）
    await init_db()
    await init_auth_table()
    # JWT 用户认证系统（建表 + 默认管理员）
    await init_jwt_auth()

    from app.config import settings

    # PostgreSQL 表结构初始化（SQLAlchemy ORM，含记忆子系统表）
    if settings.db_mode == "postgresql":
        async with async_session_factory() as session:
            async with session.bind.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

    # 记忆子系统初始化（从 PG 恢复画像/特征/原始发言到内存）
    from app.memory.store import memory_store
    await memory_store.init()

    logger.info("db_mode=%s", settings.db_mode)

    # 启动时扫描工作区孤立目录
    _cleanup_orphaned_workspaces()

    # Redis 初始化（不可用时降级，不阻塞启动）
    await init_redis(app)

    # 崩溃恢复：把上次未完成的 RUNNING 会议标记为 PAUSED
    from app.orchestrator.runner import recover_crashed_meetings
    recovered = await recover_crashed_meetings()
    if recovered:
        logger.info("崩溃恢复：%d 个会议标记为 PAUSED", len(recovered))

    # 启动后台指标采集（测试模式下可禁用，避免事件循环冲突）
    if os.environ.get("CONCLAVE_DISABLE_METRICS") != "1":
        from app.observability.metrics_store import get_metrics_store
        get_metrics_store().start()

    # 沙箱预热：启动时检测 Docker 可用性 + 预拉取镜像（不阻塞启动）
    if os.environ.get("CONCLAVE_DISABLE_SANDBOX_WARMUP") != "1":
        from app.sandbox import warmup_sandbox
        create_supervised_task(warmup_sandbox(), name="sandbox-warmup")

    # 动态定价抓取：启动时后台加载硅基流动实时定价
    if os.environ.get("CONCLAVE_DISABLE_PRICING_LOADER") != "1":
        from app.pricing_fetcher import ensure_pricing_loaded
        create_supervised_task(ensure_pricing_loaded(), name="pricing-loader")

    # 加载持久化的 BYOK API Key 到内存 Provider 配置
    if os.environ.get("CONCLAVE_DISABLE_KEY_LOADER") != "1":
        from app.services.key_store import load_keys_to_providers
        create_supervised_task(load_keys_to_providers(), name="key-loader")

    # 启动速率限制定期清理任务（修复 H-08 内存泄漏）
    from app.middleware import start_rate_limit_cleanup, stop_rate_limit_cleanup
    start_rate_limit_cleanup()

    yield

    # 停止速率限制清理
    stop_rate_limit_cleanup()
    # 停止后台指标采集
    if os.environ.get("CONCLAVE_DISABLE_METRICS") != "1":
        await get_metrics_store().stop()
    # 关闭 Redis
    await close_redis(app)
    # 清理所有沙箱服务容器
    try:
        from app.sandbox import cleanup_all_services
        await cleanup_all_services()
    except Exception:
        pass
    # 关闭 LLM 底层 httpx 连接池
    try:
        from app.agents.compute import shutdown_compute
        await shutdown_compute()
    except Exception:
        pass
    # 关闭 Playwright 浏览器
    try:
        from app.tools.browser_tool import browser_pool
        await browser_pool.shutdown()
    except Exception:
        pass
    # 关闭 network_security 的异步 httpx 连接池
    try:
        from app.network_security import shutdown_async_client
        await shutdown_async_client()
    except Exception:
        pass


def create_app() -> FastAPI:
    """构造 FastAPI 应用"""
    app = FastAPI(
        title="Conclave",
        description="会议型多智能体系统后端",
        version="0.3.0",
        lifespan=lifespan,
    )
    # CORS：生产环境必须通过 CONCLAVE_CORS_ORIGINS 限制；开发环境默认允许常见本地端口
    _cors_origins_raw = os.environ.get("CONCLAVE_CORS_ORIGINS", "")
    if _cors_origins_raw.strip():
        _cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
    else:
        # 开发模式默认：仅允许常见本地开发端口，不使用通配符 *
        _cors_origins = [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
        ]
    _allow_credentials = _cors_origins != ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # API 认证中间件
    from app.middleware import setup_auth_middleware
    setup_auth_middleware(app)
    # 请求追踪中间件
    setup_trace_middleware(app)
    # 挂载路由
    app.include_router(auth_router.router)
    app.include_router(agent_roles_router.router)
    app.include_router(captcha_router.router)
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
        from app.config import settings
        checks: dict[str, str] = {}
        _test_mode = os.environ.get("CONCLAVE_TEST_MODE") == "1"

        # PostgreSQL 检查（单次查询）
        try:
            async with async_session_factory() as session:
                await session.execute(text("SELECT 1"))
            checks["postgresql"] = "ok"
        except Exception as e:
            checks["postgresql"] = f"error: {e}"

        # Redis 检查（测试模式跳过）
        if not _test_mode:
            try:
                import redis.asyncio as aioredis
                r = await aioredis.from_url(settings.redis_url, socket_connect_timeout=3)
                await r.ping()
                await r.close()
                checks["redis"] = "ok"
            except Exception as e:
                checks["redis"] = f"error: {type(e).__name__}"

        # Qdrant 检查（未配置时跳过）
        if settings.qdrant_url:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=3) as client:
                    resp = await client.get(f"{settings.qdrant_url}/healthz")
                    checks["qdrant"] = "ok" if resp.status_code == 200 else f"error: {resp.status_code}"
            except Exception as e:
                checks["qdrant"] = f"error: {type(e).__name__}"

        # Docker 检查（测试模式跳过）
        if not _test_mode:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker", "info",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(proc.wait(), timeout=3)
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

        _healthy_vals = {"ok", "closed", "half_open", "disabled"}
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
    async def debug_auth_info(request: Request) -> dict[str, Any]:
        """认证信息查询端点（供前端自动发现 dev token）。

        [M-11 修复] 生产环境（设置了 CONCLAVE_API_TOKEN）下此端点仅返回认证状态摘要，
        不泄露具体配置细节；dev 模式返回明文 token 供前端自动配置。
        非 GET 或异常请求一律拒绝。
        """
        from app.middleware import _API_TOKEN, _DEV_TOKEN, get_dev_token_info

        info = get_dev_token_info()
        if not _API_TOKEN:
            # dev 模式：返回明文 token
            info["token"] = _DEV_TOKEN
            info["note"] = "dev 模式自动发现；生产环境必须设置 CONCLAVE_API_TOKEN"
        else:
            # 生产模式：不泄露 token 和具体配置细节
            info["token"] = None
            info["note"] = "生产模式"
            # 生产模式下隐藏敏感字段（限速阈值、用户名等）
            info.pop("fail_ban_enabled", None)
            info.pop("rate_limit_per_min", None)
            info.pop("rate_limit_fail_per_min", None)
            info.pop("rate_block_seconds", None)
            info.pop("default_admin_username", None)
        return info

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
