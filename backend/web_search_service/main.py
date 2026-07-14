#!/usr/bin/env python3
"""
Web Search Service — 独立基础设施服务

通过 HTTP 协议对外暴露搜索能力，与 Conclave 主进程解耦。

架构：
- 单进程内管理 Playwright 浏览器生命周期
- SessionPool 按 session_key 复用 BrowserContext（话题一致性）
- 所有反检测、翻译、CAPTCHA 值守逻辑内聚在本服务中

API:
    GET  /health              → 健康检查
    GET  /stats               → SessionPool 统计
    POST /search              → 执行搜索
    POST /fetch               → 抓取 URL 内容
    POST /sessions/{key}/clear → 清除指定 session

环境变量（替代 app.config.settings）：
    CONCLAVE_LLM_API_KEY    — 翻译模型 API key（可选，不设置则跳过翻译）
    CONCLAVE_LLM_BASE_URL   — 翻译模型 API 地址
    CONCLAVE_DATA_DIR       — Cookie 持久化目录
    CONCLAVE_WEB_SEARCH_PORT — 服务端口（默认 9100）
    CONCLAVE_WEB_SEARCH_HEADED — 设为 1 启用有头模式（值守模式）
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import Any

# 确保 backend 目录在 sys.path 中（服务 Docker 镜像内 backend 是工作目录）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ── 日志 ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("web_search_service")

# ── 配置：通过 app.config.settings 统一加载（一致性要求） ─────────
# LLM API key 从 app.config.settings 读取，保持与主进程一致
from app.config import settings
LLM_BASE_URL = settings.llm_base_url
LLM_API_KEY = settings.llm_api_key
PORT = int(os.environ.get("CONCLAVE_WEB_SEARCH_PORT", "9100"))
DATA_DIR = os.environ.get("CONCLAVE_DATA_DIR", "/app/data")
HEADED = os.environ.get("CONCLAVE_WEB_SEARCH_HEADED", "0") == "1"

# 确保翻译所需的环境变量在 PlaywrightWebSearch 导入前设置
os.environ.setdefault("CONCLAVE_DATA_DIR", DATA_DIR)

# ── 全局状态 ──────────────────────────────────────────────────
_ws_instance: Any = None  # PlaywrightWebSearch 实例
_research_agent: Any = None  # DeepResearchAgent 实例
_startup_time: float = 0

# ── 注入环境变量供 PlaywrightWebSearch 读取
if settings.web_search_service_url:
    os.environ.setdefault("CONCLAVE_WEB_SEARCH_SERVICE_URL", settings.web_search_service_url)


# ── 生命周期 ──────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ws_instance, _research_agent, _startup_time

    logger.info("正在启动 Web Search Service...")
    _startup_time = time.time()

    # 延迟导入：避免在模块加载时触发 Playwright 启动
    from app.tools.playwright_search import PlaywrightWebSearch

    _ws_instance = PlaywrightWebSearch()
    await _ws_instance._ensure_browser()

    # 初始化 ResearchAgent（LLM 驱动的研究规划能力）
    from web_search_service.research_agent import get_research_agent

    async def _search_wrapper(query: str, top_k: int, session_key: str, language: str):
        """将 PlaywrightWebSearch.search 适配为 Agent 期望的签名"""
        return await _ws_instance.search(
            query, top_k=top_k, session_key=session_key, language=language,
        )

    _research_agent = get_research_agent(_search_wrapper)
    logger.info("Web Search Service 已就绪 (port=%d, headed=%s, agent=%s)",
                PORT, HEADED, "ready" if _research_agent else "disabled")

    yield

    # 关闭
    logger.info("正在关闭 Web Search Service...")
    if _ws_instance:
        await _ws_instance.close()
    logger.info("Web Search Service 已关闭")


# ── FastAPI 应用 ──────────────────────────────────────────────
app = FastAPI(
    title="Web Search Service",
    version="1.0.0",
    lifespan=lifespan,
)


# ── 请求模型 ──────────────────────────────────────────────────
class SearchRequest(BaseModel):
    query: str = Field(..., description="搜索查询", min_length=1, max_length=5000)
    top_k: int = Field(default=5, ge=1, le=20, description="最大结果数")
    session_key: str = Field(default="default", description="Session 标识，同一 key 复用 Context")
    language: str = Field(default="zh-CN", description="搜索语言")
    time_range: str | None = Field(default=None, description="时间过滤: day/week/month/year")
    country: str = Field(default="CN", description="国家代码")


class SearchResult(BaseModel):
    evidence_id: str
    quote: str
    source: str
    url: str
    source_tier: str
    signals: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    results: list[dict[str, Any]]
    elapsed_ms: float
    query: str
    translated: bool = False


class FetchRequest(BaseModel):
    url: str = Field(..., description="目标 URL")
    max_chars: int = Field(default=5000, ge=100, le=50000)
    session_key: str = Field(default="default")


class FetchResponse(BaseModel):
    url: str
    title: str
    content: str
    source_tier: str
    error: str | None = None


class ResearchRequest(BaseModel):
    topic: str = Field(..., description="研究主题", min_length=1, max_length=500)
    max_rounds: int = Field(default=3, ge=1, le=6, description="最大迭代轮数")


class ResearchFinding(BaseModel):
    claim: str
    sources: list[str]
    confidence: str


class ResearchResponse(BaseModel):
    topic: str
    summary: str
    key_findings: list[ResearchFinding]
    detailed_analysis: str
    sources: list[dict[str, str]]
    rounds: int
    total_time_ms: float
    confidence: str


class HealthResponse(BaseModel):
    status: str
    browser_connected: bool
    session_count: int
    uptime_seconds: float
    version: str = "1.0.0"


class StatsResponse(BaseModel):
    session_count: int
    session_keys: list[str]
    browser_connected: bool
    captcha_blocked_domains: int


# ── API 端点 ──────────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse)
async def health():
    """健康检查"""
    browser_ok = False
    session_count = 0
    try:
        if _ws_instance and _ws_instance._browser:
            browser_ok = _ws_instance._browser.is_connected()
        if _ws_instance:
            session_count, _ = _ws_instance._session_pool.get_stats()
    except Exception:
        pass

    return HealthResponse(
        status="ok" if browser_ok else "degraded",
        browser_connected=browser_ok,
        session_count=session_count,
        uptime_seconds=time.time() - _startup_time,
    )


@app.get("/stats", response_model=StatsResponse)
async def stats():
    """SessionPool 统计"""
    session_keys: list[str] = []
    session_count = 0
    browser_ok = False
    captcha_count = 0

    if _ws_instance:
        session_count, session_keys = _ws_instance._session_pool.get_stats()
        captcha_count = len(_ws_instance._captcha_blocked_domains)
        if _ws_instance._browser:
            browser_ok = _ws_instance._browser.is_connected()

    return StatsResponse(
        session_count=session_count,
        session_keys=session_keys,
        browser_connected=browser_ok,
        captcha_blocked_domains=captcha_count,
    )


@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    """🔧 工具层端点：无状态搜索（纯 I/O 函数）

    职责边界：
    - 输入：query（单一搜索词）→ 输出：results（原始搜索结果列表）
    - 智能：零。不规划、不评估、不迭代。纯函数。
    - 调用方：Conclave Orchestrator（主应用 Agent，自己做规划和判断）
    - 协议：更换实现不影响调用方（ToolPort 协议）

    与 /research 的区别：
    - /search 是"工具"——调用方决定搜什么、搜多少、够不够
    - /research 是"Agent"——服务内部自主规划、搜索、评估、合成

    设计原则：Conclave 主应用只使用 /search，不使用 /research。
    避免两个 Agent（Conclave Orchestrator + DeepResearchAgent）嵌套冲突。
    """
    if not _ws_instance:
        raise HTTPException(status_code=503, detail="服务未就绪")

    start = time.monotonic()
    try:
        results = await _ws_instance.search(
            req.query,
            top_k=req.top_k,
            session_key=req.session_key,
            language=req.language,
            time_range=req.time_range,
            country=req.country,
        )
        elapsed = (time.monotonic() - start) * 1000

        # 检测是否经过了翻译（简单启发：如果查询含中文但 language 被设为 en-US）
        translated = any('\u4e00' <= c <= '\u9fff' for c in req.query) and req.language != "en-US"

        return SearchResponse(
            results=results,
            elapsed_ms=round(elapsed, 1),
            query=req.query,
            translated=translated,
        )
    except asyncio.TimeoutError:
        elapsed = (time.monotonic() - start) * 1000
        raise HTTPException(
            status_code=504,
            detail=f"搜索超时 ({elapsed:.0f}ms): {req.query[:50]}",
        )
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        logger.error("搜索失败: %s", str(e)[:200])
        raise HTTPException(
            status_code=500,
            detail=f"搜索失败 ({elapsed:.0f}ms): {str(e)[:100]}",
        )


@app.post("/fetch", response_model=FetchResponse)
async def fetch_url(req: FetchRequest):
    """抓取 URL 内容"""
    if not _ws_instance:
        raise HTTPException(status_code=503, detail="服务未就绪")

    try:
        result = await _ws_instance.fetch_url(req.url, max_chars=req.max_chars)
        return FetchResponse(
            url=req.url,
            title=result.get("title", ""),
            content=result.get("content", ""),
            source_tier=result.get("source_tier", "C"),
            error=result.get("error"),
        )
    except Exception as e:
        logger.error("抓取失败: url=%s err=%s", req.url[:80], str(e)[:200])
        return FetchResponse(
            url=req.url,
            title="",
            content="",
            source_tier="C",
            error=str(e)[:200],
        )


@app.post("/research", response_model=ResearchResponse)
async def research(req: ResearchRequest):
    """🧠 Agent 层端点：自主研究（Plan → Search → Evaluate → Synthesize）

    职责边界：
    - 输入：topic（自然语言研究主题）→ 输出：ResearchReport（结构化报告）
    - 智能：完整。LLM 驱动的五阶段流水线（规划、搜索、评估、补全、合成）
    - 调用方：外部项目、curl 用户、前端直接调用（不需要自己写 Agent 逻辑）
    - 时长：通常 20-60 秒，取决于 topic 复杂度和迭代轮数

    与 /search 的区别：
    - /search 是"工具"——调用方决定搜什么、搜多少、够不够
    - /research 是"Agent"——服务内部自主规划、搜索、评估、合成

    设计原则：Conclave 主应用只使用 /search，不使用 /research。
    避免两个 Agent（Conclave Orchestrator + DeepResearchAgent）嵌套冲突。
    """
    if not _research_agent:
        raise HTTPException(status_code=503, detail="ResearchAgent 未就绪（LLM API key 未配置）")

    try:
        report = await _research_agent.research(
            req.topic, max_rounds=req.max_rounds,
        )
        return ResearchResponse(
            topic=report.topic,
            summary=report.summary,
            key_findings=[
                ResearchFinding(
                    claim=f["claim"],
                    sources=f.get("sources", []),
                    confidence=f.get("confidence", "medium"),
                )
                for f in report.key_findings
            ],
            detailed_analysis=report.detailed_analysis,
            sources=report.sources,
            rounds=report.rounds,
            total_time_ms=report.total_time_ms,
            confidence=report.confidence,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="研究超时")
    except Exception as e:
        logger.error("研究失败: %s", str(e)[:200])
        raise HTTPException(status_code=500, detail=f"研究失败: {str(e)[:200]}")


@app.post("/sessions/{session_key}/clear")
async def clear_session(session_key: str):
    """清除指定 session（Context 故障时手动清理）"""
    if not _ws_instance:
        raise HTTPException(status_code=503, detail="服务未就绪")

    await _ws_instance._session_pool.invalidate(session_key)
    return {"status": "cleared", "session_key": session_key}


# ── 主入口 ────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")