# Web Search 工具：感知层首期实现（预留接口 + stub）
from __future__ import annotations

from typing import Any, Protocol


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
    接入真实 API（Tavily/SerpAPI）时替换此类即可。
    """

    name = "stub_web_search"
    evidence_type = "web"

    async def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """返回空列表，让调用方走降级路径"""
        return []


class TavilyWebSearch:
    """Tavily Web Search 实现（预留，需 CONCLAVE_WEB_SEARCH_API_KEY）

    接入时取消注释并填入真实端点。结果格式：
    [{ "quote": "...", "source": "web:example.com", "url": "..." }]
    """

    name = "tavily_web_search"
    evidence_type = "web"

    def __init__(self) -> None:
        from app.config import settings
        self._api_key = getattr(settings, "web_search_api_key", "")
        self._base_url = "https://api.tavily.com"

    async def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        if not self._api_key:
            return []
        # 接入真实 API 时取消以下注释
        # import httpx
        # resp = await httpx.AsyncClient().post(
        #     f"{self._base_url}/search",
        #     headers={"Authorization": f"Bearer {self._api_key}"},
        #     json={"query": query, "max_results": top_k},
        #     timeout=30.0,
        # )
        # resp.raise_for_status()
        # data = resp.json().get("results", [])
        # return [
        #     {
        #         "evidence_id": f"web-{i}",
        #         "quote": item.get("content", "")[:300],
        #         "source": f"web:{item.get('url', 'unknown')}",
        #         "url": item.get("url", ""),
        #     }
        #     for i, item in enumerate(data)
        # ]
        return []


def get_web_search() -> ToolPort:
    """按配置返回 Web Search 工具：有 key 用 Tavily，否则用 stub"""
    from app.config import settings
    if getattr(settings, "web_search_api_key", ""):
        return TavilyWebSearch()
    return StubWebSearch()
