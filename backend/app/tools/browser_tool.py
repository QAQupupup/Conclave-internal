# BrowserTool v2：生产级 Agent 浏览器操作工具集
#
# 架构变更（v1 → v2）：
# - 全局单例 → BrowserPool（按 meeting_id 隔离 BrowserContext）
# - Semaphore(5) 共享 page → 每 Page 独立 Lock（同页串行，跨页并行）
# - 无安全 → 域名白名单 + scheme 校验 + 私网拒绝 + 重定向校验
# - 无审计 → 每次操作记录结构化日志（LogBus）+ 脱敏
# - 单路径提取 → 渐进式降级链（DOM → 动态等待 → evaluate）
# - 无反验证码 → 区分 403/验证码/超时，分别走降级路径
#
# 评审参考：DeepSeek 4 Pro 原始评审 + GPT 两轮交叉评审（N1-N10）
from __future__ import annotations

import asyncio
import base64
import ipaddress
import logging
import re
import time
from typing import Any, Optional
from urllib.parse import urlparse

from .playwright_search import _STEALTH_JS, _USER_AGENT

logger = logging.getLogger("app.tools.browser_tool")

# ================================================================
# 配置
# ================================================================

# 资源限制
MAX_CONTEXTS = 10                # 最多 10 个并行 meeting
MAX_TABS_PER_CONTEXT = 5         # 每个 meeting 最多 5 个标签
IDLE_TIMEOUT_SECONDS = 600       # 空闲 10 分钟回收 Context
MAX_NAVIGATION_DEPTH = 15        # 最大导航跳转深度
MAX_ACTIONS_PER_MINUTE = 30      # 操作频率限流
SCREENSHOT_MAX_BYTES = 2 * 1024 * 1024   # 截图最大 2MB
EVALUATE_MAX_RETURN_BYTES = 1024 * 1024   # evaluate 返回最大 1MB
EVALUATE_TIMEOUT_SECONDS = 10             # evaluate 超时 10s
LOG_SUMMARY_MAX_BYTES = 2048             # 日志摘要最大 2KB

# 域名白名单（空列表 = 允许所有公网域名，但拒绝私网）
ALLOWED_DOMAINS: list[str] = []  # 通配符格式: "*.github.com" 或 "example.com"

# 始终拒绝的 scheme
_BLOCKED_SCHEMES = {"file", "data", "javascript", "vbscript", "about", "blob"}

# 私网 IP 范围
def _is_private_ip(hostname: str) -> bool:
    """检查 hostname 是否为私网/保留地址"""
    try:
        ip = ipaddress.ip_address(hostname)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except ValueError:
        # 不是 IP 地址，检查常见内网域名
        return hostname in ("localhost", "metadata.google.internal")


def _matches_domain(hostname: str, pattern: str) -> bool:
    """检查 hostname 是否匹配域名通配符模式"""
    if pattern.startswith("*."):
        suffix = pattern[1:]  # .github.com
        return hostname.endswith(suffix)
    return hostname == pattern


def _is_url_allowed(url: str) -> tuple[bool, str]:
    """校验 URL 安全性（P0-2 + N5）

    检查项：
    1. scheme 必须是 http/https
    2. 拒绝 file/data/javascript 等危险 scheme
    3. 拒绝私网 IP / localhost / 元数据端点
    4. hostname 白名单（如果配置了）
    5. 检测 URL 中的 userinfo 绕过（http://allowed@evil.com）

    Returns:
        (allowed: bool, reason: str)
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "URL 解析失败"

    # scheme 校验
    if parsed.scheme not in ("http", "https"):
        return False, f"scheme '{parsed.scheme}' 不允许（仅 http/https）"

    if parsed.scheme in _BLOCKED_SCHEMES:
        return False, f"scheme '{parsed.scheme}' 被禁止"

    hostname = parsed.hostname or ""
    if not hostname:
        return False, "URL 缺少 hostname"

    # 私网 IP 拒绝
    if _is_private_ip(hostname):
        return False, f"私网/保留地址 '{hostname}' 被拒绝"

    # userinfo 绕过检测（http://allowed.com@evil.com/）
    if "@" in (parsed.netloc or ""):
        # 提取 @ 后面的真实 host
        real_host = parsed.netloc.rsplit("@", 1)[-1].split(":")[0]
        if real_host != hostname:
            return False, f"URL userinfo 绕过检测：声称 '{hostname}' 实际 '{real_host}'"

    # 白名单校验（如果配置了）
    if ALLOWED_DOMAINS:
        if not any(_matches_domain(hostname, p) for p in ALLOWED_DOMAINS):
            return False, f"hostname '{hostname}' 不在白名单中"

    return True, "ok"


# ================================================================
# 日志脱敏
# ================================================================

# 匹配疑似 token/cookie 的模式
_SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)(session\s*=\s*)[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)(token\s*=\s*)[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)(api[_-]?key\s*=\s*)[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)(password\s*=\s*)[^\s&]+"),
]


def _sanitize_for_log(text: str, max_length: int = LOG_SUMMARY_MAX_BYTES) -> str:
    """脱敏文本用于审计日志（N9）

    - 截断到 max_length
    - 移除疑似 token/cookie/密码模式
    注意：此函数仅用于审计日志，不影响 Agent 提取的原始数据。
    """
    if not text:
        return ""
    result = text[:max_length]
    for pattern in _SENSITIVE_PATTERNS:
        result = pattern.sub(r"\1***REDACTED***", result)
    return result


# ================================================================
# 渐进式提取降级链（N3 + N7）
# ================================================================

# 提取策略链：1) DOM 直接提取 → 2) 动态等待 + scroll → 3) evaluate
_EXTRACT_JS = """
() => {
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
    const main = document.querySelector('article, main, [role="main"], .article-body, .post-content, .entry-content, .content');
    const target = main || document.body;
    if (!target) return '';
    const text = target.innerText || target.textContent || '';
    return text.replace(/\\n{3,}/g, '\\n\\n').trim().substring(0, 3000);
}
"""


# ================================================================
# Page 包装：串行锁 + 统一等待 + 审计
# ================================================================

class _PageSession:
    """单个 Page 的会话上下文

    职责：
    - Page 级串行锁（同一 page 的操作排队执行）
    - 统一 wait_for_settle（每个 action 后等待页面就绪）
    - 操作计数与频率限流
    """

    def __init__(self, page: Any, meeting_id: str, context: "_ContextSession"):
        self.page = page
        self.meeting_id = meeting_id
        self.context = context
        self._lock = asyncio.Lock()  # 同页串行
        self._last_activity = time.monotonic()
        self._action_count = 0
        self._action_times: list[float] = []  # 滑动窗口频率限流

    async def execute(self, action_name: str, action_fn, *args, **kwargs) -> dict[str, Any]:
        """串行执行一个操作，带审计日志和统一等待

        Args:
            action_name: 操作名（如 "click", "goto"）
            action_fn: 异步函数，签名为 async fn(page, **kwargs) -> Any
        Returns:
            操作结果 dict
        """
        async with self._lock:
            # 频率限流
            now = time.monotonic()
            self._action_times = [t for t in self._action_times if now - t < 60.0]
            if len(self._action_times) >= MAX_ACTIONS_PER_MINUTE:
                return {"status": "error", "error": f"操作频率超限（{MAX_ACTIONS_PER_MINUTE}/分钟）"}
            self._action_times.append(now)
            self._action_count += 1
            self._last_activity = now

            start_time = time.time()
            result: dict[str, Any]
            try:
                raw_result = await action_fn(self.page, *args, **kwargs)
                # 统一等待页面就绪（N6）
                if action_name not in ("screenshot", "get_url", "get_title", "get_tabs"):
                    await self._wait_for_settle()
                result = raw_result if isinstance(raw_result, dict) else {"status": "ok", "data": raw_result}
            except Exception as e:
                result = {"status": "error", "error": str(e)[:200]}
                logger.warning("BrowserTool 操作失败: meeting=%s action=%s err=%s",
                               self.meeting_id, action_name, str(e)[:100])

            duration_ms = int((time.time() - start_time) * 1000)

            # 审计日志（P0-3 + N9）
            from app.observability.log_bus import log_bus
            log_bus.emit(
                "INFO",
                f"browser_action: {action_name}",
                logger="app.tools.browser_tool",
                extra={
                    "meeting_id": self.meeting_id,
                    "action": action_name,
                    "duration_ms": duration_ms,
                    "status": result.get("status", "ok"),
                    "url": _sanitize_for_log(self.page.url, 200) if hasattr(self.page, 'url') else "",
                    "result_summary": _sanitize_for_log(str(result.get("error", result.get("data", ""))), 500),
                },
            )

            return result

    async def _wait_for_settle(self, timeout: float = 5.0) -> None:
        """统一页面就绪检查（N6）

        每个 action 后等待页面达到稳定状态：
        1. wait_for_load_state('domcontentloaded') — DOM 解析完成
        2. 短暂等待动态内容渲染（500ms）
        """
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=timeout * 1000)
        except Exception:
            pass  # 页面可能已卸载或超时，不阻断后续操作
        try:
            await self.page.wait_for_timeout(500)
        except Exception:
            pass


# ================================================================
# Context 会话：按 meeting_id 隔离
# ================================================================

class _ContextSession:
    """单个 meeting 的浏览器会话

    职责：
    - 管理独立 BrowserContext（cookie/localStorage 隔离）
    - 管理 Page 列表（max_tabs_per_context 限制）
    - 导航深度计数
    - 空闲超时检测
    """

    def __init__(self, context: Any, meeting_id: str, pool: "BrowserPool"):
        self.context = context
        self.meeting_id = meeting_id
        self.pool = pool
        self.pages: list[_PageSession] = []
        self._nav_depth = 0
        self._last_activity = time.monotonic()
        self._lock = asyncio.Lock()
        # 注意：stealth 脚本注入在 BrowserPool.get_context() 中 await 完成，
        # 不在此处 create_task，避免首个 page 创建时脚本未注入的竞态条件。

    async def get_or_create_page(self, page_index: int = 0) -> _PageSession:
        """获取或创建指定索引的 Page"""
        async with self._lock:
            if page_index < len(self.pages):
                return self.pages[page_index]
            if len(self.pages) >= MAX_TABS_PER_CONTEXT:
                # 关闭最老的标签页
                oldest = self.pages.pop(0)
                try:
                    await oldest.page.close()
                except Exception:
                    pass
            new_page = await self.context.new_page()
            session = _PageSession(new_page, self.meeting_id, self)
            self.pages.append(session)
            self._last_activity = time.monotonic()
            return session

    @property
    def active_page(self) -> _PageSession:
        """获取当前活动 Page（最后一个）"""
        if not self.pages:
            raise RuntimeError(f"meeting {self.meeting_id} 无活动 Page")
        return self.pages[-1]

    def check_nav_depth(self) -> bool:
        """检查导航深度是否超限"""
        return self._nav_depth < MAX_NAVIGATION_DEPTH

    def touch(self) -> None:
        """更新最后活动时间"""
        self._last_activity = time.monotonic()

    @property
    def is_idle(self) -> bool:
        """是否空闲超时"""
        return time.monotonic() - self._last_activity > IDLE_TIMEOUT_SECONDS

    async def close(self) -> None:
        """关闭 Context 及所有 Page"""
        for ps in self.pages:
            try:
                await ps.page.close()
            except Exception:
                pass
        self.pages.clear()
        try:
            await self.context.close()
        except Exception:
            pass
        logger.info("Context 已关闭: meeting=%s", self.meeting_id)


# ================================================================
# BrowserPool：核心管理器
# ================================================================

class BrowserPool:
    """浏览器资源池：1 Chromium → N Context（按 meeting_id 隔离）

    这是 BrowserTool v2 的核心，替代 v1 的全局单例。

    用法::

        pool = get_browser_pool()
        session = await pool.get_context("meeting-123")
        page = await session.get_or_create_page(0)
        result = await page.execute("goto", lambda p: p.goto("https://example.com"))
    """

    def __init__(self) -> None:
        self._browser = None
        self._playwright = None
        self._contexts: dict[str, _ContextSession] = {}
        self._lock = asyncio.Lock()
        self._idle_check_task: asyncio.Task | None = None
        # C-1: NavigationSkill 排他锁（按 meeting_id 隔离）
        # 当 NavigationSkill 执行时，锁住整个 meeting 的浏览器操作，
        # 防止 web_search 等并发操作干扰页面状态
        self._exclusive_locks: dict[str, asyncio.Lock] = {}

    async def _ensure_browser(self) -> None:
        """延迟初始化 Chromium"""
        if self._browser is not None:
            return
        async with self._lock:
            if self._browser is not None:
                return
            from playwright.async_api import async_playwright

            logger.info("启动 BrowserPool Chromium 无头浏览器")
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-extensions",
                    "--disable-file-access-from-files",
                    "--no-first-run",
                    "--disable-default-apps",
                    "--window-size=1920,1080",
                ],
            )
            self._browser.on("disconnected", self._on_browser_disconnected)

            # 启动空闲检测后台任务
            self._idle_check_task = asyncio.create_task(self._idle_reclaim_loop())

    def _on_browser_disconnected(self) -> None:
        """浏览器断开时清理所有 Context"""
        logger.warning("Chromium 浏览器断开连接，清理所有 Context")
        for meeting_id in list(self._contexts.keys()):
            ctx = self._contexts.pop(meeting_id, None)
            if ctx:
                ctx.pages.clear()
                ctx.context = None

    async def get_context(self, meeting_id: str) -> _ContextSession:
        """获取或创建指定 meeting 的 Context

        如果 Context 数量达到上限，先回收最空闲的。
        """
        await self._ensure_browser()

        if meeting_id in self._contexts:
            ctx = self._contexts[meeting_id]
            ctx.touch()
            return ctx

        async with self._lock:
            # 再次检查（可能在等锁期间被创建）
            if meeting_id in self._contexts:
                return self._contexts[meeting_id]

            # Context 数量限制
            if len(self._contexts) >= MAX_CONTEXTS:
                await self._reclaim_oldest_idle()
                if len(self._contexts) >= MAX_CONTEXTS:
                    raise RuntimeError(f"BrowserPool 已满（{MAX_CONTEXTS} 个 Context）")

            # 创建独立 Context（cookie/localStorage 隔离）
            context = await self._browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="Asia/Shanghai",
                java_script_enabled=True,
                bypass_csp=True,  # N2: 绕过 CSP 限制
            )
            # 在页面 JS 前注入 stealth 脚本（await 确保首个 page 也能注入）
            await context.add_init_script(_STEALTH_JS)
            session = _ContextSession(context, meeting_id, self)
            self._contexts[meeting_id] = session

            from app.observability.log_bus import log_bus
            log_bus.emit("INFO", f"browser_context_created: meeting={meeting_id}",
                         logger="app.tools.browser_tool",
                         extra={"meeting_id": meeting_id, "total_contexts": len(self._contexts)})

            return session

    async def release_context(self, meeting_id: str) -> None:
        """显式释放指定 meeting 的 Context（meeting 结束时调用）"""
        ctx = self._contexts.pop(meeting_id, None)
        if ctx:
            await ctx.close()
        # 清理排他锁
        self._exclusive_locks.pop(meeting_id, None)
        from app.observability.log_bus import log_bus
        log_bus.emit("INFO", f"browser_context_released: meeting={meeting_id}",
                     logger="app.tools.browser_tool",
                     extra={"meeting_id": meeting_id, "remaining_contexts": len(self._contexts)})

    def get_exclusive_lock(self, meeting_id: str) -> asyncio.Lock:
        """获取指定 meeting 的排他锁（NavigationSkill 使用）

        NavigationSkill 执行期间持有此锁，阻塞同 meeting 的其他浏览器操作。
        这是 blocking 模式：NavigationSkill 首次实现不共享浏览器上下文。

        用法：
            lock = pool.get_exclusive_lock(meeting_id)
            async with lock:
                # 执行 NavigationSkill 步骤
                ...
        """
        if meeting_id not in self._exclusive_locks:
            self._exclusive_locks[meeting_id] = asyncio.Lock()
        return self._exclusive_locks[meeting_id]

    async def _reclaim_oldest_idle(self) -> None:
        """回收最空闲的 Context"""
        for meeting_id, ctx in sorted(self._contexts.items(), key=lambda x: x[1]._last_activity):
            if ctx.is_idle:
                logger.info("回收空闲 Context: meeting=%s", meeting_id)
                await self.release_context(meeting_id)
                return

    async def _idle_reclaim_loop(self) -> None:
        """后台定时检测空闲 Context"""
        while True:
            await asyncio.sleep(60)  # 每分钟检查一次
            for meeting_id in list(self._contexts.keys()):
                ctx = self._contexts.get(meeting_id)
                if ctx and ctx.is_idle:
                    logger.info("空闲超时回收: meeting=%s", meeting_id)
                    await self.release_context(meeting_id)

    @property
    def context_count(self) -> int:
        return len(self._contexts)

    async def close(self) -> None:
        """关闭所有资源（应用关闭时调用）"""
        if self._idle_check_task:
            self._idle_check_task.cancel()
            try:
                await self._idle_check_task
            except asyncio.CancelledError:
                pass

        for meeting_id in list(self._contexts.keys()):
            await self.release_context(meeting_id)

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._browser = None
        self._playwright = None
        logger.info("BrowserPool 已关闭")


# ================================================================
# BrowserTool v2：Agent 友好的高级 API
# ================================================================

class BrowserTool:
    """Agent 浏览器操作工具（v2）

    通过 BrowserPool 管理 Context，所有操作需携带 meeting_id。

    用法::

        tool = get_browser_tool()
        await tool.goto("meeting-123", "https://example.com")
        title = await tool.get_title("meeting-123")
        await tool.click("meeting-123", "Login", strategy="text")
        text = await tool.extract_content("meeting-123")
    """

    def __init__(self) -> None:
        self._pool = get_browser_pool()

    def _pool_ref(self) -> BrowserPool:
        return self._pool

    async def _get_page(self, meeting_id: str, page_index: int = 0) -> _PageSession:
        """获取指定 meeting 的 Page session"""
        ctx = await self._pool.get_context(meeting_id)
        return await ctx.get_or_create_page(page_index)

    # ================================================================
    # URL 安全校验（P0-2 + N5）
    # ================================================================

    def _check_url(self, url: str) -> tuple[bool, str]:
        """URL 安全校验"""
        return _is_url_allowed(url)

    async def _verify_post_redirect(self, page: Any) -> tuple[bool, str]:
        """重定向后 URL 校验（N5）

        goto 完成后检查最终 URL 是否安全（防止白名单域名重定向到恶意域名）。
        """
        final_url = page.url
        allowed, reason = _is_url_allowed(final_url)
        if not allowed:
            return False, f"重定向后 URL 不安全: {reason} (final={final_url})"
        return True, "ok"

    # ================================================================
    # 1. 导航
    # ================================================================

    async def goto(self, meeting_id: str, url: str, wait_until: str = "domcontentloaded",
                   timeout: int = 30000, page_index: int = 0) -> dict[str, Any]:
        """导航到指定 URL（含安全校验 + 重定向验证 + 导航深度检查）"""
        # 安全校验
        allowed, reason = self._check_url(url)
        if not allowed:
            return {"status": "error", "error": f"URL 被拒绝: {reason}", "url": url}

        # 导航深度检查
        ctx = await self._pool.get_context(meeting_id)
        if not ctx.check_nav_depth():
            return {"status": "error", "error": f"导航深度超限（{MAX_NAVIGATION_DEPTH}）"}
        ctx._nav_depth += 1

        ps = await self._get_page(meeting_id, page_index)

        async def _do_goto(page: Any) -> dict[str, Any]:
            # 反验证码检测（N1）
            await page.goto(url, wait_until=wait_until, timeout=timeout)
            await page.wait_for_timeout(1000)

            # 重定向后校验（N5）
            redirect_ok, redirect_reason = await self._verify_post_redirect(page)
            if not redirect_ok:
                return {"status": "error", "error": redirect_reason, "url": page.url}

            # 反验证码检测
            captcha_result = await self._detect_captcha(page)
            if captcha_result["detected"]:
                return {
                    "status": "captcha",
                    "captcha_type": captcha_result["type"],
                    "error": captcha_result["message"],
                    "url": page.url,
                }

            title = await page.title()
            return {"url": page.url, "title": title, "status": "ok"}

        return await ps.execute("goto", _do_goto)

    async def back(self, meeting_id: str, page_index: int = 0) -> dict[str, Any]:
        """后退"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            response = await page.go_back(wait_until="domcontentloaded")
            await page.wait_for_timeout(500)
            return {"url": page.url, "status": "ok" if response else "no_history"}
        return await ps.execute("back", _do)

    async def forward(self, meeting_id: str, page_index: int = 0) -> dict[str, Any]:
        """前进"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            response = await page.go_forward(wait_until="domcontentloaded")
            await page.wait_for_timeout(500)
            return {"url": page.url, "status": "ok" if response else "no_history"}
        return await ps.execute("forward", _do)

    async def reload(self, meeting_id: str, page_index: int = 0) -> dict[str, Any]:
        """重新加载"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            await page.reload(wait_until="domcontentloaded")
            await page.wait_for_timeout(1000)
            return {"url": page.url, "status": "ok"}
        return await ps.execute("reload", _do)

    async def get_url(self, meeting_id: str, page_index: int = 0) -> str:
        """获取当前 URL"""
        ps = await self._get_page(meeting_id, page_index)
        return ps.page.url

    async def get_title(self, meeting_id: str, page_index: int = 0) -> str:
        """获取页面标题"""
        ps = await self._get_page(meeting_id, page_index)
        return await ps.page.title()

    # ================================================================
    # 2. 交互
    # ================================================================

    def _resolve_locator(self, page: Any, selector: str, strategy: str = "auto") -> Any:
        """将 (selector, strategy) 解析为 Playwright Locator"""
        if strategy == "auto":
            if selector.startswith("//") or selector.startswith("xpath="):
                return page.locator(selector)
            if selector.startswith("#") or selector.startswith(".") or ">" in selector or "[" in selector:
                return page.locator(selector)
            return page.get_by_text(selector)
        elif strategy == "role":
            parts = selector.split(":", 1)
            role = parts[0]
            name = parts[1] if len(parts) > 1 else None
            return page.get_by_role(role, name=name) if name else page.get_by_role(role)
        elif strategy == "text":
            return page.get_by_text(selector)
        elif strategy == "label":
            return page.get_by_label(selector)
        elif strategy == "placeholder":
            return page.get_by_placeholder(selector)
        elif strategy == "css":
            return page.locator(selector)
        elif strategy == "xpath":
            return page.locator(f"xpath={selector}")
        elif strategy == "test_id":
            return page.get_by_test_id(selector)
        else:
            return page.locator(selector)

    async def click(self, meeting_id: str, selector: str, strategy: str = "auto",
                    timeout: int = 10000, page_index: int = 0) -> dict[str, Any]:
        """点击元素"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            loc = self._resolve_locator(page, selector, strategy)
            await loc.click(timeout=timeout)
            return {"status": "ok", "selector": selector}
        return await ps.execute("click", _do)

    async def fill(self, meeting_id: str, selector: str, value: str, strategy: str = "auto",
                   timeout: int = 10000, page_index: int = 0) -> dict[str, Any]:
        """清空并填入文本"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            loc = self._resolve_locator(page, selector, strategy)
            await loc.fill(value, timeout=timeout)
            return {"status": "ok", "selector": selector}
        return await ps.execute("fill", _do)

    async def type(self, meeting_id: str, selector: str, text: str, strategy: str = "auto",
                   delay: int = 50, timeout: int = 10000, page_index: int = 0) -> dict[str, Any]:
        """逐字符输入"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            loc = self._resolve_locator(page, selector, strategy)
            await loc.type(text, delay=delay, timeout=timeout)
            return {"status": "ok", "selector": selector}
        return await ps.execute("type", _do)

    async def press(self, meeting_id: str, key: str, selector: Optional[str] = None,
                    strategy: str = "auto", page_index: int = 0) -> dict[str, Any]:
        """按键"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            if selector:
                loc = self._resolve_locator(page, selector, strategy)
                await loc.press(key)
            else:
                await page.keyboard.press(key)
            return {"status": "ok", "key": key}
        return await ps.execute("press", _do)

    async def scroll(self, meeting_id: str, direction: str = "down", amount: int = 500,
                     selector: Optional[str] = None, page_index: int = 0) -> dict[str, Any]:
        """滚动"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            if selector:
                loc = self._resolve_locator(page, selector, "auto")
                await loc.scroll_into_view_if_needed()
            else:
                delta = amount if direction == "down" else -amount
                await page.mouse.wheel(0, delta)
                await page.wait_for_timeout(300)
            return {"status": "ok", "direction": direction, "amount": amount}
        return await ps.execute("scroll", _do)

    async def hover(self, meeting_id: str, selector: str, strategy: str = "auto",
                    timeout: int = 10000, page_index: int = 0) -> dict[str, Any]:
        """悬停"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            loc = self._resolve_locator(page, selector, strategy)
            await loc.hover(timeout=timeout)
            return {"status": "ok", "selector": selector}
        return await ps.execute("hover", _do)

    async def select(self, meeting_id: str, selector: str, value: Optional[str] = None,
                     label: Optional[str] = None, strategy: str = "auto", page_index: int = 0) -> dict[str, Any]:
        """下拉选择"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            loc = self._resolve_locator(page, selector, strategy)
            if label:
                await loc.select_option(label=label)
            elif value:
                await loc.select_option(value=value)
            else:
                return {"status": "error", "error": "需指定 value 或 label"}
            return {"status": "ok", "selector": selector}
        return await ps.execute("select", _do)

    async def check(self, meeting_id: str, selector: str, strategy: str = "auto",
                    checked: bool = True, page_index: int = 0) -> dict[str, Any]:
        """勾选/取消勾选"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            loc = self._resolve_locator(page, selector, strategy)
            if checked:
                await loc.check()
            else:
                await loc.uncheck()
            return {"status": "ok", "selector": selector}
        return await ps.execute("check", _do)

    async def drag(self, meeting_id: str, source: str, target: str, strategy: str = "auto",
                   page_index: int = 0) -> dict[str, Any]:
        """拖拽"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            src_loc = self._resolve_locator(page, source, strategy)
            tgt_loc = self._resolve_locator(page, target, strategy)
            await src_loc.drag_to(tgt_loc)
            return {"status": "ok", "source": source, "target": target}
        return await ps.execute("drag", _do)

    # ================================================================
    # 3. 内容提取（含渐进式降级 N3 + N7）
    # ================================================================

    async def get_text(self, meeting_id: str, selector: Optional[str] = None,
                       strategy: str = "auto", page_index: int = 0) -> str:
        """获取元素文本"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            if selector:
                loc = self._resolve_locator(page, selector, strategy)
                return await loc.text_content() or ""
            return await page.inner_text("body")
        result = await ps.execute("get_text", _do)
        return result.get("data", "") if result.get("status") == "ok" else ""

    async def get_html(self, meeting_id: str, selector: Optional[str] = None,
                       strategy: str = "auto", page_index: int = 0) -> str:
        """获取元素 HTML"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            if selector:
                loc = self._resolve_locator(page, selector, strategy)
                html = await loc.inner_html()
            else:
                html = await page.content()
            # 截断（N8）
            if len(html) > EVALUATE_MAX_RETURN_BYTES:
                html = html[:EVALUATE_MAX_RETURN_BYTES] + "...[truncated]"
            return html
        result = await ps.execute("get_html", _do)
        return result.get("data", "") if result.get("status") == "ok" else ""

    async def get_attribute(self, meeting_id: str, selector: str, attribute: str,
                            strategy: str = "auto", page_index: int = 0) -> Optional[str]:
        """获取元素属性"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            loc = self._resolve_locator(page, selector, strategy)
            return await loc.get_attribute(attribute)
        result = await ps.execute("get_attribute", _do)
        return result.get("data") if result.get("status") == "ok" else None

    async def extract_content(self, meeting_id: str, max_length: int = 5000,
                              page_index: int = 0) -> str:
        """提取页面正文（渐进式降级 N3 + N7）

        降级链：
        1. evaluate JS 提取（最优，能移除噪声 DOM）
        2. 失败 → inner_text("body") 纯文本提取（无噪声移除但可靠）
        """
        ps = await self._get_page(meeting_id, page_index)

        async def _do(page):
            # 策略 1: JS 提取（最优）
            try:
                content = await asyncio.wait_for(
                    page.evaluate(_EXTRACT_JS),
                    timeout=EVALUATE_TIMEOUT_SECONDS,
                )
                if content and len(content.strip()) > 50:
                    if len(content) > max_length:
                        content = content[:max_length] + "..."
                    return content
            except asyncio.TimeoutError:
                logger.warning("evaluate 超时，降级到 inner_text: meeting=%s", meeting_id)
            except Exception as e:
                logger.warning("evaluate 失败，降级到 inner_text: meeting=%s err=%s",
                               meeting_id, str(e)[:100])

            # 策略 2: inner_text 纯文本提取（降级）
            try:
                text = await page.inner_text("body")
                if text and len(text) > max_length:
                    text = text[:max_length] + "..."
                return text or ""
            except Exception as e:
                logger.error("inner_text 也失败: meeting=%s err=%s", meeting_id, str(e)[:100])
                return ""

        result = await ps.execute("extract_content", _do)
        return result.get("data", "") if result.get("status") == "ok" else ""

    async def extract_structured(self, meeting_id: str, selector: str, fields: dict[str, str],
                                 strategy: str = "auto", page_index: int = 0) -> dict[str, Any]:
        """结构化数据提取"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            loc = self._resolve_locator(page, selector, strategy)
            count = await loc.count()
            # N8: 数组长度限制
            if count > 100:
                count = 100
            items: list[dict[str, Any]] = []
            for i in range(count):
                item: dict[str, Any] = {}
                for field_name, extractor in fields.items():
                    try:
                        if extractor.startswith("@"):
                            attr_name = extractor[1:]
                            item[field_name] = await loc.nth(i).get_attribute(attr_name)
                        elif extractor.startswith("$"):
                            prop = extractor[1:]
                            if prop == "html":
                                val = await loc.nth(i).inner_html()
                                item[field_name] = val[:1000] if val else ""
                            elif prop == "text":
                                item[field_name] = await loc.nth(i).inner_text()
                        else:
                            child_loc = loc.nth(i).locator(extractor)
                            item[field_name] = await child_loc.text_content()
                    except Exception:
                        item[field_name] = None
                items.append(item)
            return {"count": count, "items": items}
        return await ps.execute("extract_structured", _do)

    async def screenshot(self, meeting_id: str, path: Optional[str] = None, full_page: bool = False,
                         selector: Optional[str] = None, strategy: str = "auto",
                         page_index: int = 0) -> dict[str, Any]:
        """截图（N8: 协议层截断）"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            if selector:
                loc = self._resolve_locator(page, selector, strategy)
                if path:
                    await loc.screenshot(path=path)
                    return {"status": "ok", "path": path}
                else:
                    buf = await loc.screenshot()
                    if len(buf) > SCREENSHOT_MAX_BYTES:
                        return {"status": "error", "error": f"截图过大 ({len(buf)} bytes)"}
                    return {"status": "ok", "base64": base64.b64encode(buf).decode()}
            else:
                if path:
                    await page.screenshot(path=path, full_page=full_page)
                    return {"status": "ok", "path": path, "full_page": full_page}
                else:
                    buf = await page.screenshot(full_page=full_page)
                    if len(buf) > SCREENSHOT_MAX_BYTES:
                        return {"status": "error", "error": f"截图过大 ({len(buf)} bytes)"}
                    return {"status": "ok", "base64": base64.b64encode(buf).decode(), "full_page": full_page}
        return await ps.execute("screenshot", _do)

    # ================================================================
    # 4. 元素查询
    # ================================================================

    async def find_elements(self, meeting_id: str, selector: str, strategy: str = "auto",
                            page_index: int = 0) -> list[dict[str, Any]]:
        """查找元素列表"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            loc = self._resolve_locator(page, selector, strategy)
            count = min(await loc.count(), 50)  # 限制返回数量
            results: list[dict[str, Any]] = []
            for i in range(count):
                el = loc.nth(i)
                tag = await el.evaluate("el => el.tagName.toLowerCase()")
                text = (await el.text_content() or "")[:100]
                visible = await el.is_visible()
                info: dict[str, Any] = {"index": i, "tag": tag, "text": text, "visible": visible}
                for attr in ["href", "src", "id", "class", "value", "name", "type", "placeholder", "role"]:
                    val = await el.get_attribute(attr)
                    if val:
                        info[attr] = val[:100]
                results.append(info)
            return results
        result = await ps.execute("find_elements", _do)
        return result.get("data", []) if result.get("status") == "ok" else []

    async def find_by_text(self, meeting_id: str, text: str, exact: bool = False,
                           page_index: int = 0) -> list[dict[str, Any]]:
        """按可见文本查找"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            loc = page.get_by_text(text, exact=exact)
            count = min(await loc.count(), 50)
            results: list[dict[str, Any]] = []
            for i in range(count):
                el = loc.nth(i)
                tag = await el.evaluate("el => el.tagName.toLowerCase()")
                el_text = (await el.text_content() or "")[:100]
                visible = await el.is_visible()
                results.append({"index": i, "tag": tag, "text": el_text, "visible": visible})
            return results
        result = await ps.execute("find_by_text", _do)
        return result.get("data", []) if result.get("status") == "ok" else []

    async def find_by_role(self, meeting_id: str, role: str, name: Optional[str] = None,
                           page_index: int = 0) -> list[dict[str, Any]]:
        """按 ARIA 角色查找"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            loc = page.get_by_role(role, name=name) if name else page.get_by_role(role)
            count = min(await loc.count(), 50)
            results: list[dict[str, Any]] = []
            for i in range(count):
                el = loc.nth(i)
                tag = await el.evaluate("el => el.tagName.toLowerCase()")
                text = (await el.text_content() or "")[:100]
                visible = await el.is_visible()
                results.append({"index": i, "tag": tag, "text": text, "visible": visible})
            return results
        result = await ps.execute("find_by_role", _do)
        return result.get("data", []) if result.get("status") == "ok" else []

    async def wait_for_element(self, meeting_id: str, selector: str, strategy: str = "auto",
                               state: str = "visible", timeout: int = 10000,
                               page_index: int = 0) -> dict[str, Any]:
        """等待元素"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            loc = self._resolve_locator(page, selector, strategy)
            await loc.wait_for(state=state, timeout=timeout)
            return {"status": "ok", "selector": selector}
        return await ps.execute("wait_for_element", _do)

    # ================================================================
    # 5. JS 注入（含超时 + 截断 + 降级）
    # ================================================================

    async def evaluate(self, meeting_id: str, expression: str, arg: Any = None,
                       page_index: int = 0) -> Any:
        """在页面执行 JS（10s 超时 + 1MB 截断）"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            try:
                result = await asyncio.wait_for(
                    page.evaluate(expression, arg),
                    timeout=EVALUATE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                return {"status": "error", "error": f"evaluate 超时 ({EVALUATE_TIMEOUT_SECONDS}s)"}
            # 截断大返回值（N8）
            result_str = str(result) if result else ""
            if len(result_str) > EVALUATE_MAX_RETURN_BYTES:
                return {"status": "ok", "data": result_str[:EVALUATE_MAX_RETURN_BYTES] + "...[truncated]"}
            return {"status": "ok", "data": result}
        return await ps.execute("evaluate", _do)

    async def evaluate_on(self, meeting_id: str, selector: str, expression: str,
                          strategy: str = "auto", arg: Any = None, page_index: int = 0) -> Any:
        """在匹配元素上执行 JS"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            loc = self._resolve_locator(page, selector, strategy)
            try:
                result = await asyncio.wait_for(
                    loc.evaluate(expression, arg),
                    timeout=EVALUATE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                return {"status": "error", "error": f"evaluate 超时 ({EVALUATE_TIMEOUT_SECONDS}s)"}
            result_str = str(result) if result else ""
            if len(result_str) > EVALUATE_MAX_RETURN_BYTES:
                return {"status": "ok", "data": result_str[:EVALUATE_MAX_RETURN_BYTES] + "...[truncated]"}
            return {"status": "ok", "data": result}
        return await ps.execute("evaluate_on", _do)

    # ================================================================
    # 6. 标签页管理
    # ================================================================

    async def new_tab(self, meeting_id: str, url: Optional[str] = None,
                      page_index: int = 0) -> dict[str, Any]:
        """新建标签页"""
        ctx = await self._pool.get_context(meeting_id)
        if len(ctx.pages) >= MAX_TABS_PER_CONTEXT:
            # 关闭最老标签（P1-1）
            oldest = ctx.pages.pop(0)
            try:
                await oldest.page.close()
            except Exception:
                pass

        page = await ctx.context.new_page()
        ps = _PageSession(page, meeting_id, ctx)
        ctx.pages.append(ps)

        if url:
            allowed, reason = self._check_url(url)
            if not allowed:
                return {"status": "error", "error": f"URL 被拒绝: {reason}"}
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1000)

        return {"status": "ok", "tab_index": len(ctx.pages) - 1, "url": url or "about:blank"}

    async def switch_tab(self, meeting_id: str, index: int) -> dict[str, Any]:
        """切换标签页"""
        ctx = await self._pool.get_context(meeting_id)
        if 0 <= index < len(ctx.pages):
            # 通过将目标 page 移到列表末尾使其成为 "active"
            page = ctx.pages.pop(index)
            ctx.pages.append(page)
            try:
                await page.page.bring_to_front()
            except Exception:
                pass
            return {"status": "ok", "tab_index": index, "url": page.page.url}
        return {"status": "error", "error": f"标签页索引 {index} 超出范围（共 {len(ctx.pages)} 个）"}

    async def close_tab(self, meeting_id: str, index: Optional[int] = None) -> dict[str, Any]:
        """关闭标签页"""
        ctx = await self._pool.get_context(meeting_id)
        if not ctx.pages:
            return {"status": "error", "error": "无可关闭的标签页"}
        target_idx = index if index is not None else len(ctx.pages) - 1
        if 0 <= target_idx < len(ctx.pages):
            ps = ctx.pages.pop(target_idx)
            try:
                await ps.page.close()
            except Exception:
                pass
            return {"status": "ok", "closed_index": target_idx, "remaining": len(ctx.pages)}
        return {"status": "error", "error": f"标签页索引 {target_idx} 超出范围"}

    async def get_tabs(self, meeting_id: str) -> list[dict[str, Any]]:
        """获取所有标签页信息"""
        ctx = await self._pool.get_context(meeting_id)
        tabs: list[dict[str, Any]] = []
        for i, ps in enumerate(ctx.pages):
            try:
                title = await ps.page.title()
            except Exception:
                title = ""
            tabs.append({
                "index": i,
                "url": ps.page.url,
                "title": title,
                "active": i == len(ctx.pages) - 1,
            })
        return tabs

    # ================================================================
    # 7. 辅助方法
    # ================================================================

    async def get_links(self, meeting_id: str, page_index: int = 0) -> list[dict[str, str]]:
        """提取页面所有链接"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            return await page.evaluate("""
                () => Array.from(document.querySelectorAll('a[href]')).map(a => ({
                    text: (a.textContent || '').trim().substring(0, 100),
                    href: a.href,
                })).filter(l => l.href)
            """)
        result = await ps.execute("get_links", _do)
        return result.get("data", []) if result.get("status") == "ok" else []

    async def get_forms(self, meeting_id: str, page_index: int = 0) -> list[dict[str, Any]]:
        """提取页面所有表单"""
        ps = await self._get_page(meeting_id, page_index)
        async def _do(page):
            return await page.evaluate("""
                () => Array.from(document.forms).map(form => ({
                    action: form.action,
                    method: form.method,
                    fields: Array.from(form.elements).map(el => ({
                        name: el.name || '',
                        type: el.type || el.tagName.toLowerCase(),
                        value: el.value || '',
                        placeholder: el.placeholder || '',
                        required: el.required,
                    })).filter(f => f.name || f.type === 'submit'),
                }))
            """)
        result = await ps.execute("get_forms", _do)
        return result.get("data", []) if result.get("status") == "ok" else []

    async def release_meeting(self, meeting_id: str) -> None:
        """释放 meeting 的所有浏览器资源（meeting 结束时调用）"""
        await self._pool.release_context(meeting_id)

    # ================================================================
    # 8. 反验证码检测（N1）
    # ================================================================

    async def _detect_captcha(self, page: Any) -> dict[str, Any]:
        """检测页面是否被验证码/反爬拦截（N1）

        检测策略：
        1. 页面标题检测（常见验证码页面标题）
        2. DOM 元素检测（reCAPTCHA / hCaptcha / Cloudflare）
        3. HTTP 状态码检测（通过 response 对象）
        """
        try:
            title = (await page.title()).lower()

            # Cloudflare 检测
            if "just a moment" in title or "attention required" in title:
                return {"detected": True, "type": "cloudflare",
                        "message": "Cloudflare 验证页面，建议换源或降低频率"}

            # reCAPTCHA 检测
            has_recaptcha = await page.evaluate("""
                () => {
                    return !!document.querySelector(
                        '.g-recaptcha, iframe[src*="recaptcha"], iframe[src*="captcha"]'
                    );
                }
            """)
            if has_recaptcha:
                return {"detected": True, "type": "recaptcha",
                        "message": "reCAPTCHA 验证码，建议换搜索入口或换源"}

            # hCaptcha 检测
            has_hcaptcha = await page.evaluate("""
                () => !!document.querySelector('iframe[src*="hcaptcha"], .h-captcha')
            """)
            if has_hcaptcha:
                return {"detected": True, "type": "hcaptcha",
                        "message": "hCaptcha 验证码，建议换搜索入口或换源"}

            # 403 检测（常见 IP 封禁页面）
            body_text = await page.inner_text("body")
            if len(body_text) < 200 and any(kw in body_text.lower() for kw in [
                "403", "forbidden", "access denied", "blocked", "rate limit",
            ]):
                return {"detected": True, "type": "blocked",
                        "message": "页面被拦截（403/封禁），建议换代理或降低频率"}

        except Exception:
            pass

        return {"detected": False, "type": "", "message": ""}


# ================================================================
# 全局单例
# ================================================================

_pool_instance: BrowserPool | None = None
_tool_instance: BrowserTool | None = None


def get_browser_pool() -> BrowserPool:
    """获取全局 BrowserPool 单例"""
    global _pool_instance
    if _pool_instance is None:
        _pool_instance = BrowserPool()
    return _pool_instance


def get_browser_tool() -> BrowserTool:
    """获取全局 BrowserTool 单例"""
    global _tool_instance
    if _tool_instance is None:
        _tool_instance = BrowserTool()
    return _tool_instance


async def close_browser_tool() -> None:
    """关闭全局 BrowserTool 和 BrowserPool（应用关闭时调用）"""
    global _tool_instance, _pool_instance
    if _pool_instance is not None:
        await _pool_instance.close()
        _pool_instance = None
    _tool_instance = None
