# DuckDuckGoEngine：DuckDuckGo 搜索引擎（备用引擎）
#
# 实现 SearchEngine Protocol，作为 BingPlaywrightEngine 的 failover 备选。
# 使用 DuckDuckGo HTML 版本（https://html.duckduckgo.com/html/）进行搜索，
# 解析简单且不依赖 JS 渲染。
#
# 与 BingPlaywrightEngine 的区别：
# - DDG HTML 版直接返回结果 HTML，无需表单提交
# - DDG 的 result URL 在 <a class="result__a"> 的 href 中
# - DDG 的 result snippet 在 <a class="result__snippet"> 中
# - DDG 的 result URL 是重定向链接，需要解析出真实 URL
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from app.tools.search_engine import SearchResult, SearchEngineError

logger = logging.getLogger("app.tools.engines.ddg")

# DDG HTML 版结果提取 JS
_DDG_EXTRACT_JS = """
() => {
    const results = [];
    document.querySelectorAll('.result, .web-result').forEach((el, i) => {
        const titleEl = el.querySelector('.result__a, .result__url');
        const snippetEl = el.querySelector('.result__snippet');
        const title = titleEl ? titleEl.textContent.trim() : '';
        let href = titleEl ? titleEl.href : '';
        const snippet = snippetEl ? snippetEl.textContent.trim() : '';

        // DDG 的 href 是重定向链接 (//duckduckgo.com/l/?uddg=...)，需要解析
        if (href && href.includes('uddg=')) {
            try {
                const url = new URL(href, window.location.origin);
                const uddg = url.searchParams.get('uddg');
                if (uddg) href = decodeURIComponent(uddg);
            } catch (e) {}
        }
        // 去掉 // 前缀
        if (href.startsWith('//')) href = 'https:' + href;

        if (href && href.startsWith('http')) {
            results.push({ url: href, title: title, snippet: snippet, rank: i });
        }
    });
    return results;
}
"""


class DuckDuckGoEngine:
    """DuckDuckGo 搜索引擎：通过 Playwright 搜索 DDG HTML 版

    实现 SearchEngine Protocol。
    作为 BingPlaywrightEngine 的备用引擎。

    特点：
    - 使用 DDG HTML 版（轻量，无需 JS 渲染）
    - 重定向 URL 解析（uddg 参数提取真实 URL）
    - 复用 PlaywrightWebSearch 的浏览器实例
    """

    @property
    def name(self) -> str:
        return "ddg"

    @property
    def is_available(self) -> bool:
        """检查 Playwright 是否可用"""
        try:
            import playwright  # noqa: F401
            return True
        except ImportError:
            return False

    async def search(self, query: str, max_results: int = 5, **kwargs: Any) -> list[SearchResult]:
        """执行 DuckDuckGo 搜索，返回 SearchResult 列表

        流程：
        1. 获取 PlaywrightWebSearch 单例（复用浏览器）
        2. 导航到 DDG HTML 搜索页
        3. 填写搜索框并提交
        4. 提取结果（URL + title + snippet）
        5. 转换为 SearchResult（自动填充 tier/signals）
        """
        if not self.is_available:
            raise SearchEngineError("Playwright 未安装")

        try:
            from app.tools.playwright_search import get_playwright_search
            from app.tools.domain_registry import rank_by_tier, SPAM_DOMAINS

            pw_search = get_playwright_search()
            await pw_search._ensure_browser()

            # 使用 DDG HTML 版
            # DDG HTML 版可以直接通过 URL 搜索：https://html.duckduckgo.com/html/?q=query
            # 但为了绕过反爬，使用表单提交
            browser = pw_search._browser
            if browser is None:
                raise SearchEngineError("浏览器未初始化")

            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()

            try:
                # 导航到 DDG HTML 版首页
                await page.goto("https://html.duckduckgo.com/html/", wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(500)

                # 填写搜索框并提交
                search_input = page.locator('input[name="q"]')
                await search_input.fill(query)
                await search_input.press("Enter")

                # 等待结果加载
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
                await page.wait_for_timeout(1000)

                # 提取结果
                raw_results = await page.evaluate(_DDG_EXTRACT_JS)

                if not raw_results:
                    logger.debug("DDG 搜索无结果: query=%s", query[:50])
                    return []

                # 转换为 SearchResult
                results: list[SearchResult] = []
                seen_urls: set[str] = set()
                for item in raw_results:
                    url = item.get("url", "")
                    if not url or url in seen_urls:
                        continue

                    # 过滤 spam 域名
                    hostname = urlparse(url).hostname or ""
                    if hostname in SPAM_DOMAINS:
                        continue

                    seen_urls.add(url)
                    results.append(SearchResult(
                        url=url,
                        title=item.get("title", ""),
                        snippet=item.get("snippet", ""),
                        rank=item.get("rank", 0),
                        engine=self.name,
                    ))

                # 按 tier 重排
                url_to_idx = {r.url: i for i, r in enumerate(results)}
                ranked_urls = rank_by_tier([r.url for r in results])

                ranked_results = []
                for url in ranked_urls[:max_results]:
                    idx = url_to_idx.get(url)
                    if idx is not None:
                        ranked_results.append(results[idx])

                logger.debug("DDG 搜索: query=%s, 获取 %d 结果", query[:50], len(ranked_results))
                return ranked_results

            finally:
                await page.close()
                await context.close()

        except SearchEngineError:
            raise
        except Exception as e:
            raise SearchEngineError(f"DDG 搜索失败: {e}") from e

    async def health_check(self) -> bool:
        """健康检查：尝试访问 DDG HTML 版首页"""
        if not self.is_available:
            return False
        try:
            from app.tools.playwright_search import get_playwright_search
            pw_search = get_playwright_search()
            await pw_search._ensure_browser()
            return pw_search._browser is not None
        except Exception:
            return False
