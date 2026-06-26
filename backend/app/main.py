# FastAPI 入口：挂载 routers，CORS，lifespan
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db
from app.routers import documents as documents_router
from app.routers import meetings as meetings_router
from app.routers import ws as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库"""
    init_db()
    yield


def create_app() -> FastAPI:
    """构造 FastAPI 应用"""
    app = FastAPI(
        title="Conclave",
        description="会议型多智能体系统后端（迭代一）",
        version="0.1.0",
        lifespan=lifespan,
    )
    # CORS：开发期全放开
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # 挂载路由
    app.include_router(meetings_router.router)
    app.include_router(documents_router.router)
    app.include_router(ws_router.router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        """健康检查"""
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
