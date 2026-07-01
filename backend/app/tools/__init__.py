# Web Search 工具：感知层实现（stub / tavily / playwright 三模式）
from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger("app.tools")


class ToolPort(Protocol):
    """工具端口协议：agent 可调用的外部感知能力"""
    name: str
    evidence_type: str  # "web" | "platform_api" | "browser" | "desktop"

    async def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """检索并返回证据列表，结果标注来源类型"""
        ...


class StubWebSearch:
    """桩 Web Search：无 API key 时返回空结果

    不虚构搜索结果，让 evidence_check 走 [common_knowledge] 降级路径。
    """

    name = "stub_web_search"
    evidence_type = "web"

    async def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """返回空列表，让调用方走降级路径"""
        return []


class TavilyWebSearch:
    """Tavily Web Search 实现（需 CONCLAVE_WEB_SEARCH_API_KEY）

    结果格式：
    [{ "evidence_id": "web-0", "quote": "...", "source": "web:example.com", "url": "..." }]
    """

    name = "tavily_web_search"
    evidence_type = "web"

    def __init__(self) -> None:
        from app.config import settings
        self._api_key = settings.web_search_api_key
        self._base_url = "https://api.tavily.com"

    async def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        if not self._api_key:
            return []
        import httpx
        resp = await httpx.AsyncClient().post(
            f"{self._base_url}/search",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"query": query, "max_results": top_k},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json().get("results", [])
        return [
            {
                "evidence_id": f"web-{i}",
                "quote": item.get("content", "")[:300],
                "source": f"web:{item.get('url', 'unknown')}",
                "url": item.get("url", ""),
            }
            for i, item in enumerate(data)
        ]


def get_web_search() -> ToolPort:
    """按配置返回 Web Search 工具

    三种模式（CONCLAVE_WEB_SEARCH_MODE 环境变量）：
    - playwright（默认）：自建无头浏览器，零 API 开销
    - tavily：Tavily API，需 CONCLAVE_WEB_SEARCH_API_KEY
    - stub：空结果，走降级路径
    """
    from app.config import settings
    mode = settings.web_search_mode

    if mode == "tavily" and settings.web_search_api_key:
        logger.info("Web Search 模式: Tavily API")
        return TavilyWebSearch()

    if mode == "playwright":
        try:
            from app.tools.playwright_search import get_playwright_search
            logger.info("Web Search 模式: Playwright 无头浏览器")
            return get_playwright_search()
        except ImportError:
            logger.warning("Playwright 未安装，降级到 StubWebSearch")
            return StubWebSearch()

    logger.info("Web Search 模式: Stub（空结果降级）")
    return StubWebSearch()
