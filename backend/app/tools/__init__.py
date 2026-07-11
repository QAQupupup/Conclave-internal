"""Web 搜索工具层

三种模式通过环境变量 CONCLAVE_WEB_SEARCH_MODE 控制：
- "stub"      : 返回空结果（离线模式）
- "tavily"    : 使用 Tavily API（需要 CONCLAVE_WEB_SEARCH_API_KEY）
- "playwright": 本地 Playwright 无头浏览器爬取 Bing + 正文提取（默认，零 API 开销）

模块对外暴露：
- ToolPort           : 工具协议（search + fetch_url）
- StubWebSearch      : 空实现
- TavilyWebSearch    : Tavily API 实现
- PlaywrightWebSearch: Playwright 实现
- get_web_search()   : 工厂函数，返回配置的搜索实例
- get_web_fetch()    : 获取URL内容抓取工具（复用Playwright实例）
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

from app.config import settings

logger = logging.getLogger(__name__)


class ToolPort(Protocol):
    """Web 搜索/抓取工具统一接口"""

    async def search(self, query: str, top_k: int = 5, **kwargs: Any) -> list[dict[str, Any]]:
        """执行网络搜索，返回证据列表

        Args:
            query: 搜索查询
            top_k: 最大结果数
            **kwargs: 可选参数
                - language: 搜索语言 (zh-CN/en-US等)
                - time_range: 时间过滤 (day/week/month/year)
                - country: 国家/地区代码
        """
        ...

    async def fetch_url(self, url: str, max_chars: int = 5000) -> dict[str, Any]:
        """直接抓取指定URL的内容，无需搜索

        Args:
            url: 要抓取的URL
            max_chars: 最大返回字符数

        Returns:
            {"url", "title", "content", "chunks", "source_tier", "signals", "error"}
        """
        ...


class StubWebSearch:
    """空搜索实现（离线/无网络时使用）"""

    async def search(self, query: str, top_k: int = 5, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def fetch_url(self, url: str, max_chars: int = 5000) -> dict[str, Any]:
        return {"url": url, "title": "", "content": "", "chunks": [], "error": "web_search_disabled"}


class TavilyWebSearch:
    """Tavily API 搜索实现"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client: Any = None

    def _get_client(self) -> Any:
        import httpx
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=20.0)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def search(self, query: str, top_k: int = 5, **kwargs: Any) -> list[dict[str, Any]]:
        try:
            client = self._get_client()
            payload: dict[str, Any] = {
                "api_key": self.api_key,
                "query": query,
                "max_results": top_k,
                "search_depth": kwargs.get("search_depth", "basic"),
                "include_answer": False,
            }
            # 时间过滤
            time_range = kwargs.get("time_range")
            if time_range in ("day", "week", "month", "year"):
                payload["topic"] = "news"
                days_map = {"day": 1, "week": 7, "month": 30, "year": 365}
                payload["days"] = days_map[time_range]

            resp = await client.post("https://api.tavily.com/search", json=payload)
            resp.raise_for_status()
            data = resp.json()
            results = []
            for i, item in enumerate(data.get("results", [])[:top_k]):
                content = item.get("content", "") or ""
                results.append({
                    "evidence_id": f"web-{i}",
                    "quote": content[:500],
                    "source": f"web:{item.get('url', '')}",
                    "url": item.get("url", ""),
                    "source_tier": "B",
                    "signals": {
                        "title": item.get("title", ""),
                        "score": item.get("score", 0),
                        "engine": "tavily",
                    },
                })
            return results
        except Exception as e:
            logger.warning("Tavily 搜索失败: %s", e)
            return []

    async def fetch_url(self, url: str, max_chars: int = 5000) -> dict[str, Any]:
        """Tavily的extract API获取URL内容"""
        try:
            client = self._get_client()
            resp = await client.post(
                "https://api.tavily.com/extract",
                json={"api_key": self.api_key, "urls": url},
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if results:
                r = results[0]
                raw = r.get("raw_content", "") or ""
                return {
                    "url": url,
                    "title": r.get("title", ""),
                    "content": raw[:max_chars],
                    "chunks": [{"text": raw[:max_chars], "heading_path": "", "heading_level": 0}],
                    "source_tier": "B",
                    "signals": {"engine": "tavily_extract"},
                    "error": None,
                }
            return {"url": url, "title": "", "content": "", "chunks": [], "error": "no_content"}
        except Exception as e:
            logger.warning("Tavily fetch_url失败: %s", e)
            return {"url": url, "title": "", "content": "", "chunks": [], "error": str(e)}


# 单例
_instance: ToolPort | None = None


def get_web_search() -> ToolPort:
    """获取配置的 Web 搜索工具实例（单例）"""
    global _instance
    if _instance is not None:
        return _instance

    settings_obj = settings
    mode = settings_obj.web_search_mode

    if mode == "tavily" and settings_obj.web_search_api_key:
        logger.info("Web Search: 使用 Tavily API 模式")
        _instance = TavilyWebSearch(settings_obj.web_search_api_key)
    elif mode == "playwright":
        try:
            from app.tools.playwright_search import PlaywrightWebSearch
            logger.info("Web Search: 使用 Playwright 本地爬取模式")
            _instance = PlaywrightWebSearch()
        except Exception as e:
            logger.warning("Playwright 初始化失败，回退到 stub: %s", e)
            _instance = StubWebSearch()
    else:
        if mode == "tavily" and not settings_obj.web_search_api_key:
            logger.warning("Tavily 模式需要 CONCLAVE_WEB_SEARCH_API_KEY，回退到 stub")
        else:
            logger.info("Web Search: 使用 stub 模式（返回空结果）")
        _instance = StubWebSearch()

    return _instance


def get_web_fetch() -> ToolPort:
    """获取URL抓取工具（与search共用同一个实例）"""
    return get_web_search()
