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
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import init_auth as init_jwt_auth  # noqa: F401  # 保留供外部引用，实际初始化由 auth 插件完成
from app.core.exceptions import AppException
from app.db.base import Base
from app.db.engine import async_session_factory
from app.db.redis import close_redis, init_redis
from app.events import start_event_bus, stop_event_bus
from app.logging_config import setup_logging
from app.middleware import setup_trace_middleware
from app.net_auth import init_auth_table
from app.plugins import PluginRegistry, set_global_registry
from app.routers import admin as admin_router
from app.routers import agent_roles as agent_roles_router
from app.routers import artifacts as artifacts_router
from app.routers import audit_logs as audit_router
from app.routers import captcha as captcha_router
from app.routers import code as code_router
from app.routers import config as config_router
from app.routers import docker_hosts as docker_hosts_router
from app.routers import documents as documents_router
from app.routers import graph as graph_router
from app.routers import issues as issues_router
from app.routers import meetings as meetings_router
from app.routers import metrics as metrics_router
from app.routers import net_auth as net_auth_router
from app.routers import notifications as notifications_router
from app.routers import preferences as preferences_router
from app.routers import projects as projects_router
from app.routers import regression as regression_router
from app.routers import system as system_router
from app.routers import teams as teams_router
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
    # 建表单一入口：ORM 表走 Base.metadata.create_all()（见下方 db_mode 分支），
    # 增量变更走 Alembic；raw SQL ensure 函数仅用于少数 legacy 表（见 docs/sql-development-rules.md §5）
    await init_auth_table()
    # 注意：JWT 用户认证系统（init_auth）由 auth CORE 插件 on_startup 处理，此处不再直接调用

    from app.config import settings

    # PostgreSQL 表结构初始化（SQLAlchemy ORM，含记忆子系统表）
    if settings.db_mode == "postgresql":
        async with async_session_factory() as session, session.bind.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)  # type: ignore[union-attr]

    # RBAC 多租户：建表 + Casbin 初始化
    try:
        from app.rbac import ensure_rbac_tables, init_rbac
        from app.rbac.policies import (
            ROLE_BANNED,
            seed_default_policies,
            seed_team_policies,
        )

        await ensure_rbac_tables()
        await init_rbac()

        # 确保默认系统策略存在
        await seed_default_policies()

        # 为现有租户 seed Casbin 策略（幂等）
        from sqlalchemy import select as _sel

        from app.db.models import TenantModel

        async with async_session_factory() as _s:
            _tenants = (await _s.execute(_sel(TenantModel.id))).scalars().all()
            for _tid in _tenants:
                await seed_team_policies(_tid)

        # 为现有用户同步 Casbin 角色（从 tenant_members 表，幂等）
        from app.db.models import TenantMemberModel as _TM
        from app.rbac.enforcer import get_enforcer as _get_enf
        from app.rbac.enforcer import team_domain as _tdom

        async with async_session_factory() as _s:
            _members = (await _s.execute(_sel(_TM))).scalars().all()
            _e = _get_enf()
            for _m in _members:
                _role = ROLE_BANNED if _m.is_banned else _m.role
                await _e.add_grouping_policy(str(_m.user_id), _role, _tdom(_m.tenant_id))
            await _e.save_policy()

        logger.info("RBAC Casbin 初始化完成（%d 个租户，%d 个成员记录）", len(_tenants), len(_members))
    except Exception as e:
        logger.error("RBAC 初始化失败（致命）: %s: %s", type(e).__name__, str(e)[:300])
        raise

    # Schema 一致性校验（防止 ORM 与 raw SQL DDL 双源真相）
    # 仅在 PostgreSQL 模式且非测试环境下做硬校验；测试环境在 conftest 中单独调用
    if settings.db_mode == "postgresql" and not os.environ.get("CONCLAVE_TEST_MODE"):
        try:
            from app.db.schema_verify import verify_schema_consistency

            await verify_schema_consistency(raise_on_error=False)  # 启动时仅警告，不阻断
        except Exception as e:
            logger.warning("Schema 校验执行失败（非致命）: %s", e)

    # 记忆子系统初始化（从 PG 恢复画像/特征/原始发言到内存）
    from app.memory.store import memory_store

    await memory_store.init()

    logger.info("db_mode=%s", settings.db_mode)

    # 插件系统：触发所有已注册插件的 on_startup（bootstrap 已在 create_app 同步完成）
    # 插件目录扫描（外部/额外插件）：通过 CONCLAVE_PLUGINS_EXTRA_DIR 指定
    try:
        import importlib.resources as _pkg_res

        from app.plugins import builtin as _builtin_ns

        _builtin_dir = Path(_pkg_res.files(_builtin_ns)._paths[0])  # type: ignore[attr-defined]
    except Exception:
        _builtin_dir = Path(__file__).parent / "plugins" / "builtin"
    _extra_dir_raw = os.environ.get("CONCLAVE_PLUGINS_EXTRA_DIR", "").strip()
    _plugin_dirs: list[Path] = [_builtin_dir]
    if _extra_dir_raw:
        _plugin_dirs.append(Path(_extra_dir_raw))
    try:
        # 同步扫描额外目录（Phase 1a 仅扫描，Phase 1b 起动态加载外部插件）
        app.state.plugin_registry.sync_discover(_plugin_dirs)
        await app.state.plugin_registry.initialize_all(app)
        logger.info(
            "插件系统初始化完成，共 %d 个插件已就绪",
            app.state.plugin_registry.loaded_count(),
        )
    except Exception as e:
        logger.warning("插件系统初始化失败（非致命，继续启动）: %s", e)

    # 启动时扫描工作区孤立目录
    _cleanup_orphaned_workspaces()

    # 启动时清理过期录制文件（操作回放截图保留策略，非致命）
    try:
        from app.services.recording_store import cleanup_expired

        removed = cleanup_expired()
        if removed:
            logger.info("启动时清理过期录制文件：%d 个会议目录", removed)
    except Exception as e:
        logger.warning("录制文件保留清理失败（非致命）: %s", e)

    # Redis 初始化（不可用时降级，不阻塞启动）
    await init_redis(app)

    # 事件总线 Redis Pub/Sub 桥接启动（Redis 不可用时自动降级为纯内存模式）
    await start_event_bus()

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

    # ===== 关闭阶段（逆序：先业务资源，后基础设施）=====
    # 关闭插件系统（逆序 shutdown，在基础设施关闭之前）
    try:
        await app.state.plugin_registry.shutdown_all()
    except Exception as e:
        logger.warning("插件系统关闭异常（非致命）: %s", e)
    # 停止速率限制清理
    stop_rate_limit_cleanup()
    # 停止后台指标采集
    if os.environ.get("CONCLAVE_DISABLE_METRICS") != "1":
        try:
            await get_metrics_store().stop()
        except Exception as e:
            logger.warning("指标采集停止异常（非致命）: %s", e)
    # 停止事件总线 Redis Pub/Sub 桥接（必须在 close_redis 之前）
    try:
        await stop_event_bus()
    except Exception as e:
        logger.warning("事件总线停止异常（非致命）: %s", e)
    # 关闭 Redis
    try:
        await close_redis(app)
    except Exception as e:
        logger.warning("Redis 关闭异常（非致命）: %s", e)
    # 清理所有沙箱服务容器
    try:
        from app.sandbox import cleanup_all_services

        await cleanup_all_services()
    except Exception as e:
        logger.warning("沙箱清理异常（非致命）: %s", e)
    # 关闭 LLM 底层 httpx 连接池
    try:
        from app.agents.compute import shutdown_compute

        await shutdown_compute()
    except Exception as e:
        logger.warning("LLM 连接池关闭异常（非致命）: %s", e)
    # 关闭 Playwright 浏览器（browser_tool + playwright_search）
    try:
        from app.tools.browser_tool import close_browser_tool

        await close_browser_tool()
    except Exception as e:
        logger.warning("browser_tool 关闭异常（非致命）: %s", e)
    try:
        from app.tools.playwright_search import close_playwright_search

        await close_playwright_search()
    except Exception as e:
        logger.warning("playwright_search 关闭异常（非致命）: %s", e)
    # 关闭 network_security 的异步 httpx 连接池
    try:
        from app.network_security import shutdown_async_client

        await shutdown_async_client()
    except Exception as e:
        logger.warning("network_security 连接池关闭异常（非致命）: %s", e)
    # 关闭数据库引擎连接池（释放 PG 连接）
    try:
        from app.db.engine import get_engine

        engine = await get_engine()
        await engine.dispose()
        logger.info("数据库引擎连接池已释放")
    except Exception as e:
        logger.warning("数据库引擎释放异常（非致命）: %s", e)


def create_app() -> FastAPI:
    """构造 FastAPI 应用"""
    # [安全加固] 通过环境变量控制是否暴露 API 文档（生产环境默认关闭，避免暴露完整 API schema）
    _docs_url = "/docs" if os.environ.get("CONCLAVE_ENABLE_DOCS", "0") == "1" else None
    _redoc_url = "/redoc" if os.environ.get("CONCLAVE_ENABLE_DOCS", "0") == "1" else None
    _openapi_url = "/openapi.json" if os.environ.get("CONCLAVE_ENABLE_DOCS", "0") == "1" else None

    app = FastAPI(
        title="Conclave",
        description="会议型多智能体系统后端",
        version="0.3.0",
        lifespan=lifespan,
        docs_url=_docs_url,
        redoc_url=_redoc_url,
        openapi_url=_openapi_url,
    )

    # 插件系统：创建全局注册中心，注册内置 CORE 插件
    _registry = PluginRegistry()
    app.state.plugin_registry = _registry
    set_global_registry(_registry)

    # 注册内置插件（Phase 1a：auth 插件接管认证）
    from app.plugins.builtin.auth import AuthPlugin

    _registry.register(AuthPlugin())  # type: ignore[arg-type]  # Protocol ClassVar 与实例变量不匹配，已知 mypy 限制

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
    # [SECURITY-FIX] 请求体大小限制（默认 20MB，文件上传端点单独放宽）
    _max_body_size = int(os.environ.get("CONCLAVE_MAX_BODY_SIZE", str(20 * 1024 * 1024)))

    @app.middleware("http")
    async def limit_request_size(request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > _max_body_size:
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": f"请求体过大（{int(content_length) // 1024}KB），上限 {_max_body_size // 1024 // 1024}MB"
                    },
                )
        return await call_next(request)

    # [安全加固] 指纹隐藏中间件：剥离 Server/X-Powered-By 头，添加基础安全头
    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response: Response = await call_next(request)
        # 剥离可能暴露后端框架/版本的响应头（MutableHeaders 支持 del）
        for _h in ("server", "x-powered-by", "x-process-time"):
            if _h in response.headers:
                del response.headers[_h]
        # 不覆盖 nginx 层已设置的安全头（nginx 层更权威）；
        # 但对直连后端（开发模式）确保基础安全头存在
        if "x-content-type-options" not in response.headers:
            response.headers["x-content-type-options"] = "nosniff"
        if "x-frame-options" not in response.headers:
            response.headers["x-frame-options"] = "DENY"
        if "referrer-policy" not in response.headers:
            response.headers["referrer-policy"] = "strict-origin-when-cross-origin"
        return response

    # 请求追踪中间件（auth 中间件由插件 bootstrap 注册）
    setup_trace_middleware(app)
    # 插件 bootstrap：同步注册中间件/路由/异常处理器
    _registry.bootstrap(app)

    # 全局 AppException 处理器（统一 JSON 错误格式）
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):  # type: ignore[unused-argument]
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_dict(),
        )

    # [安全加固] 自定义 HTTP 异常响应格式，消除 FastAPI/Starlette 默认指纹
    # 默认 404 返回 {"detail":"Not Found"}，是框架最强指纹之一
    # 保留 exc.detail 作为用户可见的错误消息，避免覆盖路由中设置的具体信息
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):  # type: ignore[unused-argument]
        import json as _json

        _code_map = {
            400: ("BAD_REQUEST", "请求错误"),
            401: ("UNAUTHENTICATED", "未认证，请先登录"),
            403: ("ACCESS_DENIED", "访问被拒绝"),
            404: ("NOT_FOUND", "资源不存在"),
            405: ("METHOD_NOT_ALLOWED", "请求方法不允许"),
            409: ("CONFLICT", "资源状态冲突"),
            413: ("PAYLOAD_TOO_LARGE", "请求体过大"),
            429: ("RATE_LIMITED", "请求过于频繁"),
        }

        # 从 exc.detail 提取用户可见消息
        detail = exc.detail
        if isinstance(detail, str):
            message = detail
        elif isinstance(detail, (dict, list)):
            message = _json.dumps(detail, ensure_ascii=False)
        else:
            message = str(detail) if detail else ""

        # 如果 detail 为空（None/空字符串），使用默认消息
        default_code, default_msg = _code_map.get(exc.status_code, ("HTTP_ERROR", f"HTTP {exc.status_code}"))
        code = default_code
        if not message:
            message = default_msg

        # 提取 details（如果 detail 是 dict）
        details: dict[str, Any] = {}
        if isinstance(detail, dict):
            details = detail

        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": message, "details": details}},
        )

    # [安全加固] 自定义 422 响应格式，消除 FastAPI 默认校验错误指纹
    # 默认 422 返回 {"detail":[{...}]}，是 FastAPI 框架最强指纹
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):  # type: ignore[unused-argument]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "请求参数验证失败",
                    "details": {"errors": exc.errors()},
                }
            },
        )

    # 挂载业务路由（auth 路由由插件注册）
    app.include_router(agent_roles_router.router)
    app.include_router(captcha_router.router)
    app.include_router(meetings_router.router)
    # ADR-017 Phase 1：产物查询 API（列表/单条/血缘）
    app.include_router(artifacts_router.router)
    # ADR-017 Phase 2：项目与议题池（/api/projects、/api/issues）
    app.include_router(projects_router.router)
    app.include_router(issues_router.router)
    app.include_router(documents_router.router)
    app.include_router(code_router.router)
    app.include_router(metrics_router.router)
    app.include_router(workspace_router.router)
    app.include_router(ws_router.router)
    app.include_router(regression_router.router)
    app.include_router(system_router.router)
    app.include_router(net_auth_router.router)
    app.include_router(preferences_router.router)
    app.include_router(audit_router.router)
    app.include_router(docker_hosts_router.router)
    app.include_router(graph_router.router)
    app.include_router(notifications_router.router)
    app.include_router(teams_router.router)
    app.include_router(config_router.router)
    app.include_router(admin_router.router)

    @app.get("/health", tags=["meta"])
    async def health(request: Request, detail: str = "0") -> dict[str, Any]:
        """健康检查：检查关键依赖可用性。

        [安全加固] 默认 detail=0（最小响应），仅返回 {"status": "ok"}，不暴露内部架构信息；
        detail=1（内网）返回完整 checks 详情。nginx 层根据来源 IP 自动注入 detail=1。
        直连后端 8000 端口时默认安全，不泄露 PG/Redis/Qdrant 等依赖状态。
        """
        from app.config import settings

        # 外网最小响应模式：不执行依赖检查，仅返回存活状态
        # 这避免了通过 health 端点探测内部服务架构（PG/Redis/Qdrant/Docker/LLM）
        if detail == "0":
            return {"status": "ok"}

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
                    "docker",
                    "info",
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

        # 插件系统状态
        try:
            _pr = app.state.plugin_registry
            _ = _pr.loaded_count()
            checks["plugins"] = "ok"
        except Exception:
            checks["plugins"] = "error: unavailable"

        _healthy_vals = {"ok", "closed", "half_open", "disabled"}
        all_ok = all(v in _healthy_vals for v in checks.values())
        return {"status": "ok" if all_ok else "degraded", "checks": checks}

    _app_env = os.environ.get("APP_ENV", "dev").lower()
    if _app_env != "production":

        @app.get("/debug/auth-info", tags=["debug"])
        async def debug_auth_info(request: Request) -> dict[str, Any]:
            """认证信息查询端点（仅开发/测试模式可用）。"""
            from app.middleware import _API_TOKEN, _DEV_TOKEN, get_dev_token_info

            info = get_dev_token_info()
            if not _API_TOKEN:
                info["token"] = _DEV_TOKEN
                info["note"] = "dev 模式自动发现；生产环境必须设置 CONCLAVE_API_TOKEN"
            else:
                info["token"] = None
                info["note"] = "非 dev 模式"
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
