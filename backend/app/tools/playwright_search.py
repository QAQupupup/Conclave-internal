# 自建 Web Search：Playwright 无头浏览器方案
#
# 架构：
#   DuckDuckGo HTML 搜索 → Playwright 渲染 Top-K 页面 → 提取正文
#
# 反检测原理：
#   1. CDP 注入 ≠ DevTools 面板：page.evaluate() 通过 Chrome DevTools Protocol
#      直接在 V8 引擎执行 JS，不经过 DevTools UI。页面中基于 debugger 语句、
#      console 时差的反调试手段完全无效。
#   2. 指纹覆盖：在页面 JS 执行前注入反检测脚本，覆盖 navigator.webdriver
#      等自动化标记。
#   3. 行为反爬（Cloudflare/reCAPTCHA）：无法绕过，超时跳过，不崩溃。
#   4. 异常隔离：每个页面在独立 context 中执行，单页失败不影响其他页面。
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("app.tools.playwright_search")

# ---------- 反检测脚本 ----------
# 在页面任何 JS 执行前注入（addInitScript），覆盖自动化指纹
_STEALTH_JS = """
// 1. 覆盖 navigator.webdriver（Playwright 默认为 true）
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true,
});

// 2. 模拟真实浏览器插件列表
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: '' },
            { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: '' },
            { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: '' },
            { name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: '' },
        ];
        const pluginArray = Object.create(PluginArray.prototype);
        for (let i = 0; i < plugins.length; i++) {
            Object.defineProperty(pluginArray, i, { value: plugins[i] });
        }
        Object.defineProperty(pluginArray, 'length', { value: plugins.length });
        return pluginArray;
    },
    configurable: true,
});

// 3. 覆盖 navigator.languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en-US', 'en'],
    configurable: true,
});

// 4. 覆盖 navigator.platform（匹配 User-Agent）
Object.defineProperty(navigator, 'platform', {
    get: () => 'Win32',
    configurable: true,
});

// 5. 覆盖 navigator.permissions.query（某些站点检测 Notification 权限）
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters)
);

// 6. 遮挡 window.chrome（headless 模式下可能缺失）
if (!window.chrome) {
    window.chrome = {
        runtime: {},
        loadTimes: function() {},
        csi: function() {},
        app: {},
    };
}

// 7. 覆盖 navigator.connection（部分反爬检测 effectiveType）
if (navigator.connection) {
    Object.defineProperty(navigator.connection, 'effectiveType', {
        get: () => '4g',
        configurable: true,
    });
}
"""

# 真实 User-Agent（避免 headless 标记）
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# 页面内容提取 JS：移除噪声元素后提取正文
_EXTRACT_JS = """
() => {
    // 移除噪声 DOM 元素
    const noiseSelectors = [
        'script', 'style', 'noscript', 'iframe', 'svg', 'canvas',
        'nav', 'footer', 'header', 'aside',
        '.ad', '.ads', '.advertisement', '.sidebar',
        '.cookie-notice', '.popup', '.modal',
        '.share', '.social', '.comment', '.comments',
        '#comments', '#sidebar', '#footer',
    ];
    noiseSelectors.forEach(sel => {
        document.querySelectorAll(sel).forEach(el => el.remove());
    });

    // 优先提取 article / main / [role=main] 标签
    const main = document.querySelector('article, main, [role="main"], .article-body, .post-content, .entry-content, .content');
    const target = main || document.body;
    if (!target) return '';

    // 提取纯文本，保留段落结构
    const text = target.innerText || target.textContent || '';
    // 压缩多余空白，限制 3000 字符
    return text.replace(/\\n{3,}/g, '\\n\\n').trim().substring(0, 3000);
}
"""


class PlaywrightWebSearch:
    """自建 Web Search：Playwright 无头浏览器 + DuckDuckGo 搜索

    零 API 开销，页面动态渲染后提取正文。

    反检测策略：
    - CDP 注入 JS 不经过 DevTools 面板 → 反调试检测无效
    - addInitScript 在页面 JS 前覆盖自动化指纹
    - --disable-blink-features=AutomationControlled 禁用 Blink 自动化标记
    - 行为反爬站点（Cloudflare）超时跳过，不崩溃
    """

    name = "playwright_web_search"
    evidence_type = "web"

    def __init__(self) -> None:
        self._browser = None
        self._playwright = None
        self._semaphore = asyncio.Semaphore(3)  # 并发页面数限制
        self._lock = asyncio.Lock()  # 浏览器初始化锁

    async def _ensure_browser(self) -> None:
        """延迟初始化浏览器（首次搜索时启动，后续复用）"""
        if self._browser is not None:
            return
        async with self._lock:
            if self._browser is not None:
                return
            from playwright.async_api import async_playwright

            logger.info("启动 Playwright Chromium 无头浏览器")
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-sync",
                    "--no-first-run",
                    "--disable-default-apps",
                    "--window-size=1920,1080",
                ],
            )

    async def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """搜索流程：DuckDuckGo 搜索 → Playwright 渲染 → 提取正文

        返回格式与 TavilyWebSearch 对齐：
        [{ "evidence_id": "web-0", "quote": "...", "source": "web:example.com", "url": "..." }]
        """
        try:
            # 1. DuckDuckGo HTML 搜索获取 URL 列表
            urls = await self._search_ddg(query, top_k)
            if not urls:
                logger.warning("DuckDuckGo 搜索无结果: query=%s", query[:50])
                return []

            # 2. 确保浏览器已启动
            await self._ensure_browser()

            # 3. 并行渲染页面（并发限制）
            tasks = [self._fetch_and_extract(url) for url in urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 4. 过滤失败结果，组装证据
            evidence: list[dict[str, Any]] = []
            for i, (url, result) in enumerate(zip(urls, results)):
                if isinstance(result, Exception):
                    logger.warning("页面提取失败: url=%s err=%s", url, str(result)[:100])
                    continue
                if not result or len(result.strip()) < 50:
                    logger.debug("页面内容过短，跳过: url=%s", url)
                    continue
                hostname = urlparse(url).hostname or "unknown"
                evidence.append({
                    "evidence_id": f"web-{i}",
                    "quote": result[:300],
                    "source": f"web:{hostname}",
                    "url": url,
                })

            logger.info("Web Search 完成: query=%s, 获取 %d 条证据", query[:50], len(evidence))
            return evidence

        except Exception as e:
            logger.error("Web Search 异常: %s", str(e)[:200])
            return []

    async def _search_ddg(self, query: str, top_k: int) -> list[str]:
        """Bing 搜索：零 API key，解析 HTML 提取结果 URL

        优先使用 Bing（中国可访问），DuckDuckGo 在中国被墙。
        使用 cn.bing.com 的 HTML 结果页。
        """
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://cn.bing.com/search",
                    params={"q": query, "count": str(top_k), "setlang": "en"},
                    headers={
                        "User-Agent": _USER_AGENT,
                        "Accept": "text/html,application/xhtml+xml",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                    timeout=10.0,
                    follow_redirects=True,
                )
                resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            urls: list[str] = []
            seen: set[str] = set()

            # Bing 结果页结构：li.b_algo > h2 > a
            for li in soup.select("li.b_algo"):
                a_tag = li.select_one("h2 a")
                if not a_tag:
                    continue
                href = a_tag.get("href", "")
                if href.startswith("http") and href not in seen:
                    seen.add(href)
                    urls.append(href)
                if len(urls) >= top_k:
                    break

            return urls[:top_k]

        except Exception as e:
            logger.warning("Bing 搜索失败: %s", str(e)[:200])
            return []

    async def _fetch_and_extract(self, url: str) -> str:
        """Playwright 渲染页面并提取正文

        流程：
        1. 创建独立 context（隔离 cookie/cache）
        2. 注入反检测脚本（addInitScript，在页面 JS 前执行）
        3. 导航到 URL，等待 DOM 加载
        4. 等待动态内容渲染（2s）
        5. 执行提取 JS，获取正文
        6. 关闭 context（释放资源）

        异常处理：所有 Playwright 异常被捕获，返回空字符串。
        """
        async with self._semaphore:
            context = None
            page = None
            try:
                # 每个页面独立 context（隔离 cookie/fingerprint）
                context = await self._browser.new_context(
                    user_agent=_USER_AGENT,
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                    timezone_id="Asia/Shanghai",
                    java_script_enabled=True,
                )

                # 关键：在页面任何 JS 执行前注入反检测脚本
                # addInitScript 会在每个新页面加载时、页面 JS 之前执行
                await context.add_init_script(_STEALTH_JS)

                page = await context.new_page()

                # 导航：domcontentloaded 比 load 快，适合内容提取
                # networkidle 太慢（等待所有请求完成），不适用于有长连接的页面
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)

                # 等待动态内容渲染（SPA / AJAX 加载）
                await page.wait_for_timeout(2000)

                # 执行提取 JS（通过 CDP 在 V8 引擎直接执行，不经过 DevTools）
                content = await page.evaluate(_EXTRACT_JS)
                return content or ""

            except Exception as e:
                logger.debug("页面渲染失败: url=%s err=%s", url, str(e)[:100])
                return ""
            finally:
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass
                if context:
                    try:
                        await context.close()
                    except Exception:
                        pass

    async def close(self) -> None:
        """关闭浏览器实例（应用关闭时调用）"""
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        logger.info("Playwright 浏览器已关闭")


# 全局单例（延迟初始化）
_instance: PlaywrightWebSearch | None = None


def get_playwright_search() -> PlaywrightWebSearch:
    """获取全局 PlaywrightWebSearch 单例"""
    global _instance
    if _instance is None:
        _instance = PlaywrightWebSearch()
    return _instance


async def close_playwright_search() -> None:
    """关闭全局 PlaywrightWebSearch 实例（应用关闭时调用）"""
    global _instance
    if _instance is not None:
        await _instance.close()
        _instance = None
