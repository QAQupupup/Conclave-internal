# BingPlaywrightEngine：Bing 搜索引擎实现（SearchEngine Protocol）
#
# 封装 PlaywrightWebSearch 的 Bing 表单搜索功能，
# 返回 SearchResult 对象（带 tier/signals）而非裸 URL 列表。
from __future__ import annotations

import logging
from typing import Any

from app.tools.search_engine import SearchResult, SearchEngineError

logger = logging.getLogger("app.tools.engines.bing")


class BingPlaywrightEngine:
    """Bing 搜索引擎：通过 Playwright 表单提交实现

    实现 SearchEngine Protocol。
    复用 PlaywrightWebSearch 的 _do_bing_search() 方法。
    """

    @property
    def name(self) -> str:
        return "bing"

    @property
    def is_available(self) -> bool:
        """检查 Playwright 是否可用"""
        try:
            import playwright  # noqa: F401
            return True
        except ImportError:
            return False

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """执行 Bing 搜索，返回 SearchResult 列表

        流程：
        1. 获取 PlaywrightWebSearch 单例
        2. 调用 _do_bing_search 获取 {url, title} 列表
        3. 转换为 SearchResult（自动填充 tier/signals）
        4. 按 tier 排序后截取 max_results
        """
        if not self.is_available:
            raise SearchEngineError("Playwright 未安装")

        try:
            from app.tools.playwright_search import get_playwright_search
            from app.tools.domain_registry import rank_by_tier

            pw_search = get_playwright_search()
            # 请求 3x 结果用于 tier 重排
            fetch_count = min(max_results * 3, 15)
            raw_results = await pw_search._do_bing_search(query, fetch_count)

            if not raw_results:
                return []

            # 转换为 SearchResult
            results: list[SearchResult] = []
            for i, item in enumerate(raw_results):
                url = item.get("url", "")
                title = item.get("title", "")
                if not url:
                    continue
                results.append(SearchResult(
                    url=url,
                    title=title,
                    rank=i,
                    engine=self.name,
                ))

            # 按 tier 重排
            url_to_idx = {r.url: i for i, r in enumerate(results)}
            ranked_urls = rank_by_tier([r.url for r in results])

            # 按重排顺序重新排列
            ranked_results = []
            for url in ranked_urls[:max_results]:
                idx = url_to_idx.get(url)
                if idx is not None:
                    ranked_results.append(results[idx])

            return ranked_results

        except SearchEngineError:
            raise
        except Exception as e:
            raise SearchEngineError(f"Bing 搜索失败: {e}") from e

    async def health_check(self) -> bool:
        """健康检查：尝试访问 Bing 首页"""
        if not self.is_available:
            return False
        try:
            from app.tools.playwright_search import get_playwright_search
            pw_search = get_playwright_search()
            await pw_search._ensure_browser()
            # 简单检查浏览器是否可用
            return pw_search._browser is not None
        except Exception:
            return False
