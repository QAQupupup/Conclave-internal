"""Web 搜索工具层

四种模式通过环境变量控制：
- "stub"      : 返回空结果（离线模式）
- "tavily"    : 使用 Tavily API（需要 CONCLAVE_WEB_SEARCH_API_KEY）
- "playwright": 本地 Playwright 无头浏览器爬取 Bing + 正文提取
- "remote"    : 通过 HTTP 协议访问独立 Web Search Service（服务解耦模式）

优先级：CONCLAVE_WEB_SEARCH_SERVICE_URL > CONCLAVE_WEB_SEARCH_MODE

模块对外暴露：
- ToolPort           : 工具协议（search + fetch_url）
- StubWebSearch      : 空实现
- TavilyWebSearch    : Tavily API 实现
- RemoteWebSearch    : HTTP 远程服务实现（推荐生产模式）
- PlaywrightWebSearch: Playwright 实现（开发/单机模式）
- get_web_search()   : 工厂函数，返回配置的搜索实例
- get_web_fetch()    : 获取URL内容抓取工具（复用搜索实例）
"""

from __future__ import annotations

import logging
import os
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
                - session_key: Session 池标识
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


class RemoteWebSearch:
    """HTTP 远程搜索实现 — 通过协议访问独立 Web Search Service

    设计原则：
    - 零耦合：不依赖 Playwright、浏览器、app.tools.* 内部模块
    - 协议驱动：纯 HTTP/JSON 通信，任何语言可对接
    - 透明 failover：服务不可用时自动降级为 StubWebSearch

    环境变量：
        CONCLAVE_WEB_SEARCH_SERVICE_URL — 服务地址（如 http://web-search:9100）
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._client: Any = None
        self._failures = 0
        self._max_failures = 3

    def _get_client(self) -> Any:
        import httpx

        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(65.0, connect=5.0),
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def search(self, query: str, top_k: int = 5, **kwargs: Any) -> list[dict[str, Any]]:
        if self._failures >= self._max_failures:
            return []  # 连续失败，跳过避免阻塞

        try:
            client = self._get_client()
            payload: dict[str, Any] = {
                "query": query,
                "top_k": top_k,
                "session_key": kwargs.get("session_key", "default"),
                "language": kwargs.get("language", "zh-CN"),
            }
            if kwargs.get("time_range"):
                payload["time_range"] = kwargs["time_range"]
            if kwargs.get("country"):
                payload["country"] = kwargs["country"]

            resp = await client.post(f"{self.base_url}/search", json=payload)
            resp.raise_for_status()
            data = resp.json()
            self._failures = 0  # 成功，重置失败计数
            return data.get("results", [])  # type: ignore[no-any-return]
        except Exception as e:
            self._failures += 1
            logger.warning("RemoteWebSearch 搜索失败 (%d/%d): %s", self._failures, self._max_failures, str(e)[:100])
            return []

    async def fetch_url(self, url: str, max_chars: int = 5000) -> dict[str, Any]:
        if self._failures >= self._max_failures:
            return {"url": url, "title": "", "content": "", "chunks": [], "error": "service_unavailable"}

        try:
            client = self._get_client()
            resp = await client.post(
                f"{self.base_url}/fetch",
                json={"url": url, "max_chars": max_chars, "session_key": "default"},
            )
            resp.raise_for_status()
            data = resp.json()
            self._failures = 0
            return {
                "url": url,
                "title": data.get("title", ""),
                "content": data.get("content", ""),
                "chunks": [{"text": data.get("content", ""), "heading_path": "", "heading_level": 0}],
                "source_tier": data.get("source_tier", "C"),
                "signals": {"engine": "remote"},
                "error": data.get("error"),
            }
        except Exception as e:
            self._failures += 1
            logger.warning(
                "RemoteWebSearch fetch_url失败 (%d/%d): %s", self._failures, self._max_failures, str(e)[:100]
            )
            return {"url": url, "title": "", "content": "", "chunks": [], "error": str(e)}


class TavilyWebSearch:
    """Tavily API 搜索实现。支持租户级 api_key 覆盖。"""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key  # 全局默认 key，可能为空
        self._client: Any = None

    def _get_client(self) -> Any:
        import httpx

        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=20.0)
        return self._client

    def _resolve_api_key(self) -> str:
        """解析当前生效的 api_key：租户覆盖 > 全局默认"""
        try:
            from app.tenants.context import get_tenant_id
            from app.tenants.settings_override import get_cached_overrides

            tid = get_tenant_id()
            if tid is not None:
                ov = get_cached_overrides(tid)
                key = ov.get("web_search_api_key") if ov else None
                if key:
                    return key
        except Exception:
            pass
        return self.api_key

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def search(self, query: str, top_k: int = 5, **kwargs: Any) -> list[dict[str, Any]]:
        api_key = self._resolve_api_key()
        if not api_key:
            return []
        try:
            client = self._get_client()
            payload: dict[str, Any] = {
                "api_key": api_key,
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
                results.append(
                    {
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
                    }
                )
            return results
        except Exception as e:
            logger.warning("Tavily 搜索失败: %s", e)
            return []

    async def fetch_url(self, url: str, max_chars: int = 5000) -> dict[str, Any]:
        """Tavily的extract API获取URL内容"""
        api_key = self._resolve_api_key()
        if not api_key:
            return {"url": url, "title": "", "content": "", "chunks": [], "error": "no_api_key"}
        try:
            client = self._get_client()
            resp = await client.post(
                "https://api.tavily.com/extract",
                json={"api_key": api_key, "urls": url},
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
    """获取配置的 Web 搜索工具实例（单例）

    优先级：
    1. CONCLAVE_WEB_SEARCH_SERVICE_URL → RemoteWebSearch（服务解耦，推荐生产模式）
    2. CONCLAVE_WEB_SEARCH_MODE=playwright → PlaywrightWebSearch（开发/单机模式）
    3. CONCLAVE_WEB_SEARCH_MODE=tavily  → TavilyWebSearch（付费 API）
    4. 默认 → StubWebSearch（离线模式）
    """
    global _instance
    if _instance is not None:
        return _instance

    # 优先使用远程服务模式（零耦合，推荐生产环境）
    service_url = os.environ.get("CONCLAVE_WEB_SEARCH_SERVICE_URL", "")
    if service_url:
        logger.info("Web Search: 使用远程服务模式 (url=%s)", service_url)
        _instance = RemoteWebSearch(service_url)
        return _instance

    settings_obj = settings
    mode = settings_obj.web_search_mode

    if mode == "tavily":
        logger.info("Web Search: 使用 Tavily API 模式（支持租户级 key 覆盖）")
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
        logger.info("Web Search: 使用 stub 模式（返回空结果）")
        _instance = StubWebSearch()

    return _instance


def get_web_fetch() -> ToolPort:
    """获取URL抓取工具（与search共用同一个实例）"""
    return get_web_search()
