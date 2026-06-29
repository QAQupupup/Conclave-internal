# FastAPI 入口：挂载 routers，CORS，lifespan
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db
from app.logging_config import setup_logging
from app.middleware import setup_trace_middleware
from app.net_auth import init_auth_table
from app.routers import documents as documents_router
from app.routers import meetings as meetings_router
from app.routers import net_auth as net_auth_router
from app.routers import regression as regression_router
from app.routers import workspace as workspace_router
from app.routers import ws as ws_router

# 应用启动时初始化日志系统
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库 + 崩溃恢复"""
    init_db()
    init_auth_table()
    # 崩溃恢复：把上次未完成的 RUNNING 会议标记为 PAUSED
    from app.orchestrator.runner import recover_crashed_meetings
    recovered = recover_crashed_meetings()
    if recovered:
        import logging
        logging.getLogger("lifespan").info("崩溃恢复：%d 个会议标记为 PAUSED", len(recovered))
    yield


def create_app() -> FastAPI:
    """构造 FastAPI 应用"""
    app = FastAPI(
        title="Conclave",
        description="会议型多智能体系统后端（迭代二）",
        version="0.2.0",
        lifespan=lifespan,
    )
    # CORS：开发期全放开，生产环境应限制 origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("CONCLAVE_CORS_ORIGINS", "*").split(","),
        allow_credentials=os.environ.get("CONCLAVE_CORS_ORIGINS", "") != "" or False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # API 认证中间件：基于 token 的认证
    from app.middleware import setup_auth_middleware
    setup_auth_middleware(app)
    # 请求追踪中间件：分配 request_id，注入日志
    setup_trace_middleware(app)
    # 挂载路由
    app.include_router(meetings_router.router)
    app.include_router(documents_router.router)
    app.include_router(workspace_router.router)
    app.include_router(ws_router.router)
    app.include_router(regression_router.router)
    app.include_router(net_auth_router.router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, Any]:
        """健康检查：检查关键依赖可用性"""
        checks: dict[str, str] = {}

        # SQLite 检查
        try:
            from app.db import _connect
            conn = _connect()
            conn.execute("SELECT 1")
            conn.close()
            checks["sqlite"] = "ok"
        except Exception as e:
            checks["sqlite"] = f"error: {e}"

        # Qdrant 检查
        try:
            import httpx
            async with httpx.AsyncClient(timeout=3) as client:
                qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
                resp = await client.get(f"{qdrant_url}/healthz")
                checks["qdrant"] = "ok" if resp.status_code == 200 else f"error: {resp.status_code}"
        except Exception as e:
            checks["qdrant"] = f"error: {type(e).__name__}"

        # Docker 检查
        try:
            import subprocess
            result = subprocess.run(
                ["docker", "info"], capture_output=True, timeout=3,
            )
            checks["docker"] = "ok" if result.returncode == 0 else "error: docker unavailable"
        except Exception as e:
            checks["docker"] = f"error: {type(e).__name__}"

        # LLM 熔断器状态
        try:
            from app.agents.llm import get_circuit_breaker
            cb = get_circuit_breaker()
            checks["llm_circuit"] = cb.state
        except Exception:
            checks["llm_circuit"] = "unknown"

        all_ok = all(v == "ok" or v == "closed" for v in checks.values())
        return {"status": "ok" if all_ok else "degraded", "checks": checks}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
