# 自建 Web Search：Playwright 无头浏览器方案
#
# 架构：
#   Bing 搜索 → Playwright 渲染 Top-K 页面 → 提取正文
#
# 反检测原理（v3 增强）：
#   1. CDP 注入 ≠ DevTools 面板：page.evaluate() 通过 Chrome DevTools Protocol
#      直接在 V8 引擎执行 JS，不经过 DevTools UI。基于 debugger 语句、
#      console 时差的反调试手段完全无效。
#   2. 指纹覆盖 v3（30项）：WebGL/Canvas 指纹随机化、WebRTC 防泄漏、硬件参数伪装、
#      mediaDevices/Battery API 伪装、chrome.runtime 完整模拟、CDP 特征清除、
#      outerDimensions 区分、screen.availHeight 区分、navigator.vendor/productSub/
#      appVersion/userAgentData 覆盖、iframe contentWindow 防护、mediaCapabilities 伪装、
#      keyboard/gamepads 伪装、document.hidden 修复。
#   3. Session 预热 + Cookie 持久化：首次启动时预热浏览器（访问 Bing 首页、接受 cookie、
#      执行一次无意义搜索建立搜索历史），Cookie 持久化到磁盘复用。
#   4. 查询翻译：中文查询自动翻译为英文（使用 Hunyuan-MT-7B 免费模型），
#      英文搜索质量更高、延迟更低（4.5s vs 60s）、反爬策略更宽松。
#   5. CAPTCHA 主动检测：识别 Cloudflare/reCAPTCHA/hCaptcha/极验/腾讯/百度等验证码，
#      快速跳过（5秒内）而非盲目等待15秒超时；被拦截域名5分钟冷却。
#   6. 拟人化行为：随机延迟、Accept/Sec-Fetch-* 真实请求头、模拟滚动、
#      device_scale_factor 匹配高分屏、逐字输入而非瞬间 fill。
#   7. 行为反爬（Cloudflare/reCAPTCHA）：无法自动破解滑块/点选验证码，
#      检测到后快速跳过并标记域名冷却，不崩溃。
#   8. 异常隔离：每个页面在独立 context 中执行，单页失败不影响其他页面。
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from .domain_registry import (
    match_entity,
    rank_by_tier,
    tag_url,
)
from .playwright.captcha_js import _CAPTCHA_DETECT_JS
from .playwright.chunk_js import _CHUNK_EXTRACT_JS
from .playwright.jsonld_js import _JSONLD_EXTRACT_JS
from .playwright.security import _is_safe_url
from .playwright.session_pool import SessionPool
from .playwright.stealth_js import _STEALTH_JS

logger = logging.getLogger("app.tools.playwright_search")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


class PlaywrightWebSearch:
    """自建 Web Search：Playwright 无头浏览器 + DuckDuckGo 搜索

    零 API 开销，页面动态渲染后提取正文。

    反检测策略：
    - CDP 注入 JS 不经过 DevTools 面板 → 反调试检测无效
    - addInitScript 在页面 JS 前覆盖自动化指纹
    - --disable-blink-features=AutomationControlled 禁用 Blink 自动化标记
    - 行为反爬站点（Cloudflare）超时跳过，不崩溃
    - SessionPool：按 agent_id 分配持久化 Context，保持话题一致性
    """

    name = "playwright_web_search"
    evidence_type = "web"

    def __init__(self) -> None:
        from app.lazy_asyncio import LazyLock, LazySemaphore

        self._browser: Any = None
        self._playwright: Any = None
        self._browser_headed = False  # 标记浏览器当前是否以有头模式运行
        self._semaphore = LazySemaphore(3)  # 并发页面数限制（懒加载，跨循环安全）
        self._lock = LazyLock()  # 浏览器初始化锁（懒加载，跨循环安全）
        # Cookie/存储持久化：保存到数据目录，跨重启复用
        self._storage_state_path = os.path.join(
            os.environ.get("CONCLAVE_DATA_DIR", "/app/data"), "browser_storage_state.json"
        )
        self._captcha_blocked_domains: dict[str, float] = {}  # 域名 → 被阻时间，避免重复尝试
        self._session_warmed = False  # 是否已完成 Session 预热
        self._translator_available: bool | None = None  # 翻译模型可用性（None=未检测）
        self._translation_failures = 0  # 翻译失败计数器（监控用）
        self._session_pool = SessionPool()  # Context 池，按 agent_id 分配
        logger.info("PlaywrightWebSearch 初始化: storage_state=%s", self._storage_state_path)

    async def _translate_query(self, query: str) -> str:
        """将中文查询翻译为英文，使用免费的 Hunyuan-MT-7B 模型。

        仅在查询中包含中文字符时才翻译，纯英文查询直接返回。
        翻译失败时静默降级为原始查询，不阻塞搜索流程。

        上下文长度处理：
        - Hunyuan-MT-7B 上下文窗口约 4096 tokens
        - 搜索查询通常 10-100 字符（< 200 tokens），远低于限制
        - 超长查询（> 2000 字符）自动分句翻译后合并
        """
        # 快速检测：无中文字符直接返回
        if not any("\u4e00" <= c <= "\u9fff" for c in query):
            return query

        # 延迟检测翻译模型可用性
        if self._translator_available is False:
            return query  # 已知不可用，跳过

        try:
            from app.config import settings
            from app.tenants.context import get_tenant_id
            from app.tenants.settings_override import resolve_llm_config as _res_llm

            _tid = get_tenant_id()
            _base, _key, _mdl = _res_llm(_tid, settings.llm_base_url, settings.llm_api_key, settings.llm_model)
            if not _key or not _base:
                self._translator_available = False
                return query

            # 上下文安全检查：超过 2000 字符的查询需要分块翻译
            MAX_CHUNK_CHARS = 2000
            if len(query) <= MAX_CHUNK_CHARS:
                return await self._translate_single(query, _base, _key)

            # 分句翻译 + 合并
            logger.info("查询过长 (%d chars)，启动分块翻译...", len(query))
            chunks = self._split_into_chunks(query, MAX_CHUNK_CHARS)
            logger.info("分为 %d 个 chunk", len(chunks))

            # 并行翻译所有 chunk
            translations = await asyncio.gather(
                *[self._translate_single(c, _base, _key) for c in chunks],
                return_exceptions=True,
            )

            # 合并翻译结果
            merged_parts: list[str] = []
            for i, t in enumerate(translations):
                if isinstance(t, BaseException) or t == chunks[i]:
                    # 翻译失败，使用原始 chunk
                    merged_parts.append(chunks[i])
                    logger.warning("chunk %d 翻译失败，使用原始文本", i)
                else:
                    merged_parts.append(t)

            result = " ".join(merged_parts)
            logger.info("分块翻译完成: %d chars → %d chars", len(query), len(result))
            return result

        except Exception as e:
            self._translation_failures += 1
            logger.warning("查询翻译失败 (%d次, %s)，降级为原始查询", self._translation_failures, str(e)[:60])
            self._translator_available = False

        return query

    async def _translate_single(self, text: str, base_url: str, api_key: str) -> str:
        """翻译单个文本块（调用 Hunyuan-MT-7B API）。"""
        import httpx

        prompt = (
            f"Translate the following Chinese technical query to English. "
            f"Return ONLY the translation, no explanation, no quotes, no extra words:\n\n"
            f"Chinese: {text}\n"
            f"English:"
        )

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "tencent/Hunyuan-MT-7B",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": min(500, max(200, len(text) * 2)),
                    "temperature": 0.1,
                    "stream": False,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                translated = data["choices"][0]["message"]["content"].strip()
                translated = translated.strip('"').strip("'")
                if translated and len(translated) > 2:
                    self._translator_available = True
                    if len(text) <= 200:  # 只对短查询打印日志
                        logger.info("查询翻译: '%s' → '%s'", text[:60], translated[:80])
                    return translated  # type: ignore[no-any-return]
            else:
                logger.warning("翻译模型返回 %d: %s", resp.status_code, resp.text[:200])
                self._translator_available = False
        return text  # 失败时返回原始文本

    @staticmethod
    def _split_into_chunks(text: str, max_chars: int) -> list[str]:
        """按句子边界分割文本，确保每个 chunk 不超过 max_chars。

        分隔符优先级：中文句号/问号/感叹号 > 换行 > 分号 > 逗号 > 空格
        """
        import re

        chunks = []
        # 按句子分隔符切分（中英文通用）
        sentences = re.split(r"(?<=[。！？.!?\n])\s*", text)
        current = ""

        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            if len(current) + len(sent) + 1 <= max_chars:
                current = (current + " " + sent).strip() if current else sent
            else:
                if current:
                    chunks.append(current)
                # 如果单个句子超过限制，强制按字符截断
                if len(sent) > max_chars:
                    for i in range(0, len(sent), max_chars):
                        chunks.append(sent[i : i + max_chars])
                else:
                    current = sent

        if current:
            chunks.append(current)

        return chunks if chunks else [text]

    async def _warmup_session(self) -> None:
        """Session 预热：访问 Bing 首页、接受 cookie、执行一次无意义搜索。

        建立搜索历史后，后续搜索的反爬策略会显著放宽，中文搜索延迟
        从 60s+ 降至 5-8s。

        只在首次搜索前执行一次，后续复用 warmed session。
        """
        if self._session_warmed:
            return
        if self._browser is None:
            return

        try:
            logger.info("开始 Session 预热...")
            from playwright.async_api import Error as PlaywrightError

            context = await self._browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                extra_http_headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                },
                color_scheme="light",
                device_scale_factor=1.25,
                has_touch=False,
                is_mobile=False,
            )
            await context.add_init_script(_STEALTH_JS)

            try:
                page = await context.new_page()
                page.set_default_navigation_timeout(15000)
                page.set_default_timeout(10000)

                # Step 1: 访问 Bing 首页
                await page.goto("https://www.bing.com/", wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2000)

                # Step 2: 接受 Cookie 同意弹窗
                try:
                    accept_btn = page.locator(
                        'button[aria-label="Accept"], button#bnp_btn_accept, '
                        'button[class*="accept"], button[class*="cookie"]'
                    ).first
                    await accept_btn.click(timeout=3000)
                    await page.wait_for_timeout(1000)
                except (PlaywrightError, Exception):
                    pass  # 没有 cookie 弹窗或有其他处理

                # Step 3: 做一次英文热身搜索，建立搜索历史
                search_input = page.locator("textarea[name='q'], input[name='q']").first
                await search_input.wait_for(state="visible", timeout=5000)
                await search_input.click()
                await page.wait_for_timeout(200)
                await search_input.type("test", delay=50)
                await page.wait_for_timeout(300)
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(3000)

                # Step 4: 保存 cookie 供后续复用
                await context.storage_state(path=self._storage_state_path)
                self._session_warmed = True
                logger.info("Session 预热完成，cookie 已持久化到 %s", self._storage_state_path)

            finally:
                await page.close()
                await context.close()

        except Exception as e:
            logger.warning("Session 预热失败 (%s)，将在搜索时重试", str(e)[:60])

    async def _ensure_browser(self) -> None:
        """延迟初始化浏览器（首次搜索时启动，后续复用）

        值守模式下（guard.guard_mode=True）：
        - Chromium 以有头模式（headless=False）启动
        - 输出到 Xvfb 虚拟显示器（DISPLAY=:99）
        - 同时启动 x11vnc + websockify/noVNC 供用户通过 Web 介入
        非值守模式：headless=True，不启动 VNC。

        如果值守模式动态切换（headless ↔ headed），会自动重启浏览器。
        """
        # 检查当前需要的模式
        from app.tools.captcha_guard import get_captcha_guard

        guard = await get_captcha_guard()
        need_headed = guard.guard_mode

        # 如果浏览器已启动，检查连接状态和模式是否匹配
        if self._browser is not None:
            # P0-4: 浏览器健康检查 —— 检测连接断裂（事件循环重建等场景）
            try:
                if not self._browser.is_connected():
                    logger.warning("浏览器连接已断开（事件循环重建？），重新启动...")
                    self._browser = None
                    self._session_pool.clear()  # 浏览器重启后 Context 全部失效
                    self._session_warmed = False  # 浏览器重建后需要重新预热
                    with contextlib.suppress(Exception):
                        await self._playwright.stop()
                    self._playwright = None
            except Exception as e:
                logger.warning("浏览器健康检查失败 (%s)，重新启动...", str(e)[:60])
                self._browser = None
                self._session_pool.clear()  # 浏览器重启后 Context 全部失效
                self._session_warmed = False  # 浏览器重建后需要重新预热
                with contextlib.suppress(Exception):
                    await self._playwright.stop()
                self._playwright = None

        if self._browser is not None:
            if self._browser_headed == need_headed:
                return  # 模式匹配，复用现有浏览器
            # 模式不匹配，关闭旧浏览器，重新启动
            logger.info(
                "CAPTCHA 值守模式切换（%s → %s），重启浏览器...",
                "有头" if self._browser_headed else "无头",
                "有头" if need_headed else "无头",
            )
            with contextlib.suppress(Exception):
                await self._browser.close()
            self._browser = None
            self._session_pool.clear()  # 浏览器重启后 Context 全部失效
            with contextlib.suppress(Exception):
                await self._playwright.stop()
            self._playwright = None

        async with self._lock:
            if self._browser is not None:
                return
            from playwright.async_api import async_playwright

            headless = True
            launch_env: dict[str, str] = {}
            vnc_started = False

            if need_headed:
                # 尝试启动 VNC 环境
                try:
                    vnc_started = await guard.start_vnc()
                    if vnc_started:
                        headless = False
                        launch_env["DISPLAY"] = ":99"
                        logger.info("CAPTCHA 值守模式：以有头模式启动浏览器 (DISPLAY=:99)")
                    else:
                        logger.warning("CAPTCHA 值守模式开启但 VNC 环境不可用，仍使用 headless 模式")
                except Exception as e:
                    logger.warning("CAPTCHA 值守模式初始化失败: %s", str(e)[:100])

            mode_desc = "有头+VNC" if not headless else "headless"
            logger.info("启动 Playwright Chromium 浏览器 (%s)", mode_desc)
            self._playwright = await async_playwright().start()
            launch_args = [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-gpu" if headless else "",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-sync",
                "--no-first-run",
                "--disable-default-apps",
                "--window-size=1280,800" if not headless else "--window-size=1920,1080",
            ]
            launch_args = [a for a in launch_args if a]

            if not headless:
                # 有头模式：添加远程调试端口
                launch_args.append("--remote-debugging-port=9222")

            self._browser = await self._playwright.chromium.launch(
                headless=headless,
                args=launch_args,
                env=launch_env if launch_env else None,
            )
            self._browser_headed = not headless

    async def search(self, query: str, top_k: int = 5, **kwargs: Any) -> list[dict[str, Any]]:
        """搜索流程：Bing 搜索 → Tier 重排 → Playwright 渲染 → Claim 粒度分块提取

        Phase 1.5 改进（Claude Sonnet 5 #4 + #5）：
        1. 每页从单 blob 改为 N 个 atomic claim（按 heading 分块）
        2. 每块携带 heading_path（h1 > h2 > h3）结构元数据
        3. UGC guard：嵌入评论/社区笔记降级为 C tier（不继承 S/A/B）
        4. 保留 Phase 1 的全部增强：Bing 排除、tier 重排、JSON-LD、signals 袋、staleness
        5. 新增：支持 language（zh-CN/en-US）、time_range（day/week/month/year）、country 参数

        Args:
            query: 搜索查询
            top_k: 最大结果数
            **kwargs:
                language: 搜索语言 (zh-CN/en-US，默认 zh-CN)
                time_range: 时间过滤 (day/week/month/year)
                country: 国家/地区代码 (CN/US等)
                session_key: Session 池标识（如 meeting_id 或 agent_id），
                             同一 key 的搜索复用同一 BrowserContext，保持话题一致性

        返回格式（chunk-level evidence）：
        [{
            "evidence_id": "web-0",
            "quote": "atomic claim text...",
            "source": "web:docs.python.org",
            "url": "https://...",
            "domain": "docs.python.org",
            "source_tier": "S",
            "signals": { ... }
        }]
        """
        from playwright.async_api import Error as PlaywrightError

        fetched_at = datetime.now(timezone.utc).isoformat()
        # 提取 session_key（消费掉，避免 _do_search 调用时 kwargs 重复传参）
        session_key = kwargs.pop("session_key", "default")
        # Phase 3: 中文查询自动翻译为英文（在 try 之前执行，重试时复用）
        translated_query = await self._translate_query(query)
        if translated_query != query:
            kwargs["language"] = "en-US"
        try:
            return await asyncio.wait_for(
                self._do_search(translated_query, top_k, fetched_at, session_key, **kwargs),
                timeout=60.0,  # P0-3: 整体超时 60s（Bing 重试 32s + 渲染 28s）
            )
        except PlaywrightError as e:
            # 捕获 Playwright 连接错误，自动重建浏览器并重试一次
            msg = str(e)
            if "browser has been closed" in msg or "not connected" in msg:
                logger.warning("浏览器连接断开 (PlaywrightError)，自动重建并重试...")
                self._browser = None
                self._session_pool.clear()
                self._session_warmed = False
                await self._ensure_browser()
                # 重试一次
                return await asyncio.wait_for(
                    self._do_search(translated_query, top_k, fetched_at, session_key, **kwargs),
                    timeout=60.0,
                )
            # 不是连接错误，重新抛出
            raise
        except asyncio.TimeoutError:
            logger.warning("Web Search 整体超时 60s: query=%s", query[:50])
            return []

    async def fetch_url(self, url: str, max_chars: int = 5000) -> dict[str, Any]:
        """直接抓取指定URL的内容，无需搜索

        Args:
            url: 要抓取的URL
            max_chars: 最大返回字符数

        Returns:
            {"url", "title", "content", "chunks", "source_tier", "signals", "error"}
        """
        from .domain_registry import tag_url

        fetched_at = datetime.now(timezone.utc).isoformat()

        # SSRF 校验
        safe, reason = _is_safe_url(url)
        if not safe:
            logger.warning("fetch_url SSRF拦截: url=%s reason=%s", url[:80], reason)
            return {
                "url": url,
                "title": "",
                "content": "",
                "chunks": [],
                "source_tier": "D",
                "signals": {},
                "error": reason,
            }

        await self._ensure_browser()
        tier_info = tag_url(url)
        hostname = urlparse(url).hostname or "unknown"

        try:
            result = await asyncio.wait_for(
                self._fetch_and_extract(url, locale="zh-CN"),
                timeout=20.0,
            )
        except asyncio.TimeoutError:
            return {
                "url": url,
                "title": "",
                "content": "",
                "chunks": [],
                "source_tier": tier_info["source_tier"],
                "signals": {},
                "error": "timeout",
            }
        except Exception as e:
            return {
                "url": url,
                "title": "",
                "content": "",
                "chunks": [],
                "source_tier": tier_info["source_tier"],
                "signals": {},
                "error": str(e)[:200],
            }

        chunks = result.get("chunks", [])
        title = result.get("title", "")
        jsonld = result.get("jsonld", {})

        if not chunks:
            return {
                "url": url,
                "title": title,
                "content": "",
                "chunks": [],
                "source_tier": tier_info["source_tier"],
                "signals": {"page_title": title, "fetched_at": fetched_at},
                "error": "no_content",
            }

        # 组装 content（拼接前几个 chunk 的文本）和 chunks 列表
        content_parts = []
        chunk_list = []
        total_chars = 0
        for _i, chunk in enumerate(chunks):
            text = chunk.get("text", "")
            chunk_list.append(
                {
                    "text": text[:max_chars],
                    "heading_path": chunk.get("heading_path", ""),
                    "heading_level": chunk.get("heading_level", 0),
                    "is_ugc": chunk.get("is_ugc", False),
                }
            )
            if total_chars < max_chars:
                content_parts.append(text)
                total_chars += len(text)

        content = "\n\n".join(content_parts)[:max_chars]

        return {
            "url": url,
            "title": title,
            "content": content,
            "chunks": chunk_list,
            "source_tier": tier_info["source_tier"],
            "signals": {
                "domain": hostname,
                "page_title": title,
                "fetched_at": fetched_at,
                "jsonld_publisher": jsonld.get("publisher"),
                "chunk_count": len(chunks),
                "is_official": tier_info["is_official"],
            },
            "error": None,
        }

    async def _do_search(
        self, query: str, top_k: int, fetched_at: str, session_key: str, **kwargs: Any
    ) -> list[dict[str, Any]]:
        """搜索核心逻辑（被 search() 的 wait_for 包裹）

        Args:
            session_key: Session 池标识，用于复用 BrowserContext
            **kwargs: language, time_range, country
        """
        # 解析参数
        language = kwargs.get("language", "zh-CN")
        time_range = kwargs.get("time_range")
        country = kwargs.get("country", "CN" if language.startswith("zh") else "US")

        # locale 映射：zh-CN → 中文搜索，其他默认 en-US
        locale = language if language in ("zh-CN", "en-US", "zh-TW", "ja-JP") else "en-US"

        try:
            # 0. 确保浏览器已启动（含健康检查，P0-4 修复）
            await self._ensure_browser()

            # 0.5. Session 预热（首次搜索时执行，建立搜索历史，降低反爬强度）
            # P0-4 修复：预热暂时跳过，先验证浏览器生命周期修复
            if not self._session_warmed:
                self._session_warmed = True  # 跳过预热，但不影响后续搜索
            # await self._warmup_session() -- 暂时禁用，等浏览器生命周期修复后启用

            # 0.6. 实体匹配（零开销子串匹配，用于日志记录）
            entity = match_entity(query)
            if entity:
                logger.info("Web Search 实体匹配: query=%s → entity=%s", query[:50], entity)

            # 1. Bing 搜索获取 URL 列表（请求 3x 结果用于 tier 重排）
            fetch_count = min(top_k * 3, 15)
            urls = await self._search_ddg(
                query, fetch_count, session_key=session_key, locale=locale, time_range=time_range, country=country
            )
            if not urls:
                logger.warning("Bing 搜索无结果: query=%s", query[:50])
                return []

            # 2. 按 domain tier 重排（官方源优先）
            ranked_urls = rank_by_tier(urls)[:top_k]

            # 3. 并行渲染页面（并发限制）
            tasks = [self._fetch_and_extract(url, locale=locale, session_key=session_key) for url in ranked_urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 5. 从 chunks 组装 evidence（每 chunk 一条 evidence）
            evidence: list[dict[str, Any]] = []
            ev_idx = 0
            for url, result in zip(ranked_urls, results, strict=False):
                if isinstance(result, Exception):
                    logger.warning("页面提取失败: url=%s err=%s", url, str(result)[:100])
                    continue
                if not isinstance(result, dict):
                    continue

                chunks = result.get("chunks", [])
                if not chunks:
                    logger.debug("页面无有效分块，跳过: url=%s", url)
                    continue

                hostname = urlparse(url).hostname or "unknown"
                tier_info = tag_url(url)
                jsonld = result.get("jsonld", {})
                last_modified = result.get("last_modified")
                page_title = result.get("title", "")
                page_last_modified = last_modified or jsonld.get("dateModified")
                page_fallback = result.get("fallback", False)
                page_ugc_count = result.get("ugc_count", 0)

                # UGC tier downgrade（Claude #5）：
                # 嵌入评论/社区笔记的 chunk 不继承 S/A/B tier，降级为 C
                def _effective_tier(is_ugc: bool, tier_info: dict[str, Any] = tier_info) -> str:
                    if is_ugc:
                        return "C"
                    return tier_info["source_tier"]  # type: ignore[no-any-return]

                # 限制每页最大 chunk 数，避免 evidence 爆炸（如 docs.python.org 85 chunks）
                max_chunks_per_page = 5
                for chunk_idx, chunk in enumerate(chunks[:max_chunks_per_page]):
                    chunk_ugc = chunk.get("is_ugc", False)
                    eff_tier = _effective_tier(chunk_ugc)

                    # P0-4: prompt injection 防御 — quote 用定界符包裹
                    # 让 LLM 能结构性区分"数据"与"指令"
                    raw_text = chunk.get("text", "")[:500]
                    quote_delimited = f"[EVIDENCE_DATA_BEGIN]{raw_text}[EVIDENCE_DATA_END]"

                    # A-4: content hash — 基于结构化 chunk 输出（heading_path + text），非 raw HTML
                    heading_path = chunk.get("heading_path", "")
                    content_hash = hashlib.sha256(f"{heading_path}|{raw_text}".encode()).hexdigest()[:16]

                    evidence.append(
                        {
                            "evidence_id": f"web-{ev_idx}",
                            "quote": quote_delimited,
                            "source": f"web:{hostname}",
                            "url": url,
                            "domain": hostname,
                            "content_hash": content_hash,
                            # 顶层 tier 向后兼容（用 effective_tier）
                            "source_tier": eff_tier,
                            # signals 袋 — 原始正交信号，agent 自行加权
                            "signals": {
                                # 页面级信号
                                "tier_static": tier_info["source_tier"],
                                "effective_tier": eff_tier,
                                "is_official": tier_info["is_official"],
                                "fetched_at": fetched_at,
                                "page_last_modified": page_last_modified,
                                "jsonld_publisher": jsonld.get("publisher"),
                                "jsonld_author": jsonld.get("author"),
                                "jsonld_date_published": jsonld.get("datePublished"),
                                "jsonld_type": jsonld.get("type"),
                                "structured_data_present": bool(jsonld.get("entry_count", 0) > 0),
                                "page_title": page_title,
                                "page_fallback": page_fallback,
                                "page_ugc_count": page_ugc_count,
                                "iframe_fallback": result.get("iframe_fallback", False),
                                # chunk 级信号（Phase 1.5 新增）
                                "heading_path": heading_path,
                                "heading_level": chunk.get("heading_level", 0),
                                "chunk_index": chunk_idx,
                                "total_chunks": min(len(chunks), max_chunks_per_page),
                                "is_ugc": chunk_ugc,
                                "content_hash": content_hash,
                            },
                        }
                    )
                    ev_idx += 1

            logger.info(
                "Web Search 完成: query=%s, 获取 %d 条证据 / %d 页 (entity=%s)",
                query[:50],
                len(evidence),
                len(ranked_urls),
                entity or "unknown",
            )
            return evidence

        except Exception as e:
            logger.error("Web Search 异常: %s", str(e)[:200])
            return []

    async def _search_ddg(
        self,
        query: str,
        top_k: int,
        *,
        session_key: str = "default",
        locale: str = "zh-CN",
        time_range: str | None = None,
        country: str = "CN",
    ) -> list[str]:
        """Bing 搜索（含 MultiEngineSearch failover 到 DDG）

        搜索策略（三级 fallback）：
        1. MultiEngineSearch（Bing → DDG failover）
        2. 直接 Bing 表单搜索（重试 2 次）
        3. 直接 DDG 搜索（Bing CAPTCHA/无结果时的最终降级）

        Args:
            query: 搜索查询
            top_k: 最大结果数
            session_key: Session 池标识
            locale: 区域设置 (zh-CN/en-US)
            time_range: 时间过滤 (day/week/month/year)
            country: 国家代码

        Returns:
            list[str]: URL 列表
        """
        # Phase D: 优先使用 MultiEngineSearch（含自动 failover）
        try:
            from app.tools.search_engine import get_multi_engine_search

            multi = get_multi_engine_search()
            if multi._engines:  # 有可用引擎时
                search_kwargs: dict[str, Any] = {}
                if time_range:
                    search_kwargs["time_range"] = time_range
                if country:
                    search_kwargs["country"] = country
                result = await multi.search(query, max_results=top_k, **search_kwargs)
                if result["results"]:
                    urls = [r.url for r in result["results"]]
                    logger.info("MultiEngineSearch 成功: engine=%s, urls=%d", result["engine_used"], len(urls))
                    return urls
                # MultiEngineSearch 所有引擎都失败，降级到直接 Bing 搜索
                logger.warning("MultiEngineSearch 全部失败 (%s)，降级到直接 Bing 搜索", result["failed_engines"])
        except Exception as e:
            logger.warning("MultiEngineSearch 异常，降级到直接 Bing 搜索: %s", str(e)[:100])

        # 降级路径：直接 Bing 表单搜索（原有逻辑）
        match_entity(query)

        # 重试机制：Bing 表单搜索偶发返回空结果
        for attempt in range(2):
            try:
                raw_results = await self._do_bing_search(
                    query, top_k, session_key=session_key, locale=locale, time_range=time_range, country=country
                )
                if raw_results:
                    # _do_bing_search 返回 list[dict{url, title}]，提取 URL
                    return [r["url"] for r in raw_results if "url" in r]
                if attempt == 0:
                    logger.debug("Bing 搜索无结果，重试: query=%s", query[:50])
                    await asyncio.sleep(2)  # 重试前等待
            except Exception as e:
                if attempt == 0:
                    logger.warning("Bing 搜索异常，重试: %s", str(e)[:100])
                    await asyncio.sleep(2)
                else:
                    raise

        # P0-6: Bing 全部失败（CAPTCHA 拦截 / 无结果），最终降级到 DDG 直接搜索
        logger.warning("Bing 搜索 2 次均无结果，最终降级到 DDG 直接搜索: query=%s", query[:50])
        try:
            from app.tools.engines.ddg_engine import DuckDuckGoEngine

            ddg = DuckDuckGoEngine()
            if ddg.is_available:
                ddg_results = await ddg.search(query, max_results=top_k)
                if ddg_results:
                    urls = [r.url for r in ddg_results]
                    logger.info("DDG 直接搜索成功: urls=%d", len(urls))
                    return urls
                logger.warning("DDG 直接搜索也无结果: query=%s", query[:50])
        except Exception as e:
            logger.warning("DDG 直接搜索异常: %s", str(e)[:100])

        return []

    async def _do_bing_search(
        self,
        query: str,
        top_k: int,
        *,
        session_key: str = "default",
        locale: str = "zh-CN",
        time_range: str | None = None,
        country: str = "CN",
    ) -> list[dict[str, str]]:
        """执行单次 Bing 表单搜索（使用 SessionPool 复用 Context）

        流程：从 SessionPool 获取 Context → 访问首页 → 搜索框输入 → 从 cite 标签提取真实 URL
        支持 locale（zh-CN 中文搜索 / en-US 英文搜索）和时间过滤。

        Args:
            query: 搜索查询
            top_k: 最大结果数
            session_key: Session 池标识
            locale: 区域设置 (zh-CN/en-US)
            time_range: 时间过滤 (day/week/month/year)
            country: 国家代码

        Returns:
            list[dict]: 每项为 {"url": str, "title": str}
        """
        await self._ensure_browser()

        # Bing 时间过滤参数映射
        _BING_TIME_FILTERS = {
            "day": 'interval%3d"7"',
            "week": 'interval%3d"8"',
            "month": 'interval%3d"9"',
            "year": 'interval%3d"10"',
        }

        # 根据 locale 选择 Bing 域名和 Accept-Language
        if locale.startswith("zh"):
            bing_base = "https://cn.bing.com"
            accept_langs = ["zh-CN", "zh", "en-US", "en"]
        else:
            bing_base = "https://www.bing.com"
            accept_langs = ["en-US", "en"]

        # 加载持久化 Cookie
        bing_storage = self._storage_state_path if os.path.exists(self._storage_state_path) else None

        # Context 复用：从 SessionPool 获取（同一 session_key 复用，失败时自动切换）
        for attempt in range(2):
            context = None
            page = None
            try:
                context = await self._session_pool.get(
                    session_key,
                    self._browser,
                    user_agent=_USER_AGENT,
                    viewport={"width": 1920, "height": 1080},
                    locale=locale,
                    storage_state=bing_storage,
                    extra_http_headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                        "Accept-Language": ",".join(accept_langs),
                        "Accept-Encoding": "gzip, deflate, br",
                        "DNT": "1",
                        "Sec-Fetch-Dest": "document",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-Site": "none",
                        "Sec-Fetch-User": "?1",
                    },
                    color_scheme="light",
                    device_scale_factor=1.25,
                    has_touch=False,
                    is_mobile=False,
                )
                page = await context.new_page()
                page.set_default_navigation_timeout(20000)
                page.set_default_timeout(10000)

                # Step 1: 访问 Bing 首页
                await page.goto(bing_base + "/", wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(1000 + int(500 * (hash(query) % 100) / 100))

                # Step 2: 在搜索框输入并提交（拟人化输入）
                search_input = page.locator("textarea[name='q'], input[name='q']").first
                await search_input.wait_for(state="visible", timeout=5000)
                await search_input.click()
                await page.wait_for_timeout(200)
                await search_input.type(query, delay=50 + (hash(query) % 50))
                await page.wait_for_timeout(300)
                await page.keyboard.press("Enter")

                # Step 3: 等待结果页加载
                await page.wait_for_timeout(4000)

                # Step 3.25: 检测 Bing 验证码
                try:
                    captcha_result = await page.evaluate(_CAPTCHA_DETECT_JS)
                    if captcha_result and captcha_result.get("detected"):
                        logger.warning("Bing 搜索遇到 CAPTCHA: types=%s", captcha_result.get("types"))
                        return []  # Bing 被验证码拦截，返回空，让 failover 到 DDG
                except Exception:
                    pass

                # Step 3.5: 如果需要时间过滤，导航到带过滤参数的 URL
                if time_range and time_range in _BING_TIME_FILTERS:
                    current_url = page.url
                    time_param = _BING_TIME_FILTERS[time_range]
                    if "?" in current_url:
                        filtered_url = current_url + f"&qft={time_param}"
                    else:
                        filtered_url = current_url + f"?qft={time_param}"
                    try:
                        await page.goto(filtered_url, wait_until="domcontentloaded", timeout=15000)
                        await page.wait_for_timeout(3000)
                    except Exception:
                        pass  # 时间过滤失败不影响主流程

                # Step 4: 从 <cite> 标签提取真实 URL
                raw_results = await page.evaluate("""
                    () => {
                        const items = [];
                        document.querySelectorAll('li.b_algo').forEach(li => {
                            const cite = li.querySelector('cite');
                            const h2a = li.querySelector('h2 a');
                            const title = h2a ? (h2a.textContent || '').trim() : '';
                            const citeText = cite ? (cite.textContent || '').trim() : '';
                            items.push({title: title, cite: citeText});
                        });
                        return items;
                    }
                """)

                # 从 cite 文本重建完整 URL + 保留标题
                from .domain_registry import SPAM_DOMAINS

                results: list[dict[str, str]] = []  # {url, title}
                seen: set[str] = set()
                for item in raw_results[:top_k]:
                    cite = item.get("cite", "")
                    if not cite:
                        continue
                    title = item.get("title", "")
                    if cite.startswith("http"):
                        parts = cite.split(" › ")
                        if parts:
                            base = parts[0].rstrip("/")
                            path = "/".join(parts[1:]) if len(parts) > 1 else ""
                            url = f"{base}/{path}" if path else base
                            hostname = url.split("/")[2] if len(url.split("/")) > 2 else ""
                            if hostname in SPAM_DOMAINS:
                                continue
                            if url not in seen:
                                seen.add(url)
                                results.append({"url": url, "title": title})
                    else:
                        first_part = cite.split(" › ")[0] if " › " in cite else cite.split(" ")[0]
                        if first_part and "." in first_part:
                            url = f"https://{first_part}"
                            if url not in seen:
                                seen.add(url)
                                results.append({"url": url, "title": title})

                logger.debug("Bing 搜索: query=%s, 获取 %d URLs", query[:50], len(results))
                # 成功获取结果后保存 Cookie 状态
                if results:
                    with contextlib.suppress(Exception):
                        await context.storage_state(path=self._storage_state_path)
                return results[:top_k]

            except Exception as e:
                logger.warning(
                    "Bing 搜索失败 (attempt=%d, session_key=%s): %s", attempt + 1, session_key[:20], str(e)[:100]
                )
                # Context 可能已损坏，从池中移除
                if context is not None:
                    await self._session_pool.invalidate(session_key)
                if attempt == 0:
                    await asyncio.sleep(2)
                else:
                    raise  # 第二次仍然失败，向上抛出

            finally:
                # 只关闭 Page，不关闭 Context（Context 由 SessionPool 管理）
                if page is not None:
                    with contextlib.suppress(Exception):
                        await page.close()

        return []  # 防御性返回（理论不会到达，因为第二次失败会 raise）

    async def _fetch_and_extract(
        self, url: str, *, locale: str = "zh-CN", session_key: str = "default"
    ) -> dict[str, Any]:
        """Playwright 渲染页面并提取 claim 粒度分块 + 结构化元数据

        Phase 1.5 改进（Claude Sonnet 5 #4）：
        - 从整页 blob 改为 heading-based chunking
        - 每块携带 heading_path（h1 > h2 > h3）作为结构元数据
        - 无 heading 页面使用段落 fallback
        - 小段合并避免碎片化

        P0 安全修复（Claude 交叉评审）：
        - SSRF: 初始 URL 校验 + redirect-hop 后 response.url 校验
        - Response size: 超过 MAX_RESPONSE_BYTES 的页面跳过提取
        - Context 由 SessionPool 管理，不再每次创建新 Context

        Args:
            url: 要抓取的 URL
            locale: 浏览器区域设置 (zh-CN/en-US)
            session_key: Session 池标识，用于复用 Context

        返回：
        {
            "chunks": list[dict],    # [{heading_path, heading_level, text, is_ugc}]
            "title": str,            # 页面标题
            "jsonld": dict,          # schema.org JSON-LD 提取结果
            "last_modified": str|None,  # HTTP Last-Modified 头
            "fallback": bool,        # 是否使用了段落 fallback
            "ugc_count": int,        # 检测到的 UGC 元素数
        }

        异常处理：所有 Playwright 异常被捕获，返回空 chunks。
        """
        # P0-1: SSRF 初始 URL 校验
        safe, reason = _is_safe_url(url)
        if not safe:
            logger.warning("SSRF 拦截: url=%s reason=%s", url[:80], reason)
            return {
                "chunks": [],
                "title": "",
                "jsonld": {"entry_count": 0},
                "last_modified": None,
                "fallback": True,
                "ugc_count": 0,
            }

        # A-3: per-domain 限速（token-bucket）
        try:
            from app.tools.rate_limiter import get_rate_limiter

            acquired = await get_rate_limiter().acquire(url, max_wait=5.0)
            if not acquired:
                logger.warning("域名限速超时，跳过: url=%s", url[:80])
                return {
                    "chunks": [],
                    "title": "",
                    "jsonld": {"entry_count": 0},
                    "last_modified": None,
                    "fallback": True,
                    "ugc_count": 0,
                }
        except Exception:
            pass  # 限速器故障不阻断主流程

        async with self._semaphore:
            page = None
            try:
                # 检查域名是否近期被验证码拦截
                hostname_check = urlparse(url).hostname or ""
                now = asyncio.get_running_loop().time()
                if hostname_check in self._captcha_blocked_domains:
                    blocked_at = self._captcha_blocked_domains[hostname_check]
                    if now - blocked_at < 300:  # 5分钟内不重试被验证码拦截的域名
                        logger.debug("域名近期被CAPTCHA拦截，跳过: %s", hostname_check)
                        return {
                            "chunks": [],
                            "title": "",
                            "jsonld": {"entry_count": 0},
                            "last_modified": None,
                            "fallback": True,
                            "ugc_count": 0,
                            "captcha": True,
                            "captcha_types": ["cooldown"],
                        }

                # 加载持久化的 Cookie（如果存在）
                storage_state = None
                if os.path.exists(self._storage_state_path):
                    try:
                        storage_state = self._storage_state_path
                    except Exception:
                        storage_state = None

                # 从 SessionPool 获取 Context（复用），只创建新 Page
                context = await self._session_pool.get(
                    session_key,
                    self._browser,
                    user_agent=_USER_AGENT,
                    viewport={"width": 1920, "height": 1080},
                    locale=locale,
                    timezone_id="Asia/Shanghai",
                    java_script_enabled=True,
                    storage_state=storage_state,
                    color_scheme="light",
                    reduced_motion="no-preference",
                    forced_colors="none",
                    has_touch=False,
                    is_mobile=False,
                    device_scale_factor=1.25,
                    extra_http_headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8" if locale.startswith("zh") else "en-US,en;q=0.9",
                        "Accept-Encoding": "gzip, deflate, br",
                        "DNT": "1",
                        "Connection": "keep-alive",
                        "Upgrade-Insecure-Requests": "1",
                        "Sec-Fetch-Dest": "document",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-Site": "none",
                        "Sec-Fetch-User": "?1",
                        "Cache-Control": "max-age=0",
                    },
                )
                page = await context.new_page()
                # 拟人化：设置默认导航超时
                page.set_default_navigation_timeout(20000)
                page.set_default_timeout(10000)

                # goto 返回 Response 对象，含 HTTP 头
                response = await page.goto(url, wait_until="domcontentloaded", timeout=15000)

                # P0-1: redirect-hop SSRF 验证
                if response:
                    final_url = response.url
                    safe_redirect, redirect_reason = _is_safe_url(final_url)
                    if not safe_redirect:
                        logger.warning(
                            "SSRF redirect 拦截: initial=%s final=%s reason=%s",
                            url[:60],
                            final_url[:60],
                            redirect_reason,
                        )
                        return {
                            "chunks": [],
                            "title": "",
                            "jsonld": {"entry_count": 0},
                            "last_modified": None,
                            "fallback": True,
                            "ugc_count": 0,
                        }

                # P0-5: response body 大小限制
                MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5MB
                content_length = None
                if response:
                    cl = response.headers.get("content-length")
                    if cl:
                        with contextlib.suppress(ValueError):
                            content_length = int(cl)
                if content_length and content_length > MAX_RESPONSE_BYTES:
                    logger.warning("响应体过大，跳过: url=%s size=%d", url[:60], content_length)
                    return {
                        "chunks": [],
                        "title": "",
                        "jsonld": {"entry_count": 0},
                        "last_modified": None,
                        "fallback": True,
                        "ugc_count": 0,
                    }

                # 拟人化等待：随机延迟 500-1500ms（模拟人类阅读页面开始加载）
                await page.wait_for_timeout(500 + int(500 * (hash(url) % 100) / 100))

                # ===== CAPTCHA 快速检测（在等待完整内容前先检测）=====
                try:
                    captcha_result = await page.evaluate(_CAPTCHA_DETECT_JS)
                    if captcha_result and captcha_result.get("detected"):
                        captcha_types = captcha_result.get("types", [])
                        captcha_title = captcha_result.get("title", "")
                        logger.warning(
                            "CAPTCHA 检测: url=%s types=%s title=%s", url[:60], captcha_types, captcha_title[:50]
                        )
                        # 记录被拦截的域名
                        if hostname_check:
                            self._captcha_blocked_domains[hostname_check] = now

                        # 值守模式：暂停等待人工介入
                        try:
                            from app.tools.captcha_guard import (
                                CaptchaStatus,
                                get_captcha_guard,
                            )

                            guard = await get_captcha_guard()
                            if guard.guard_mode:
                                status = await guard.intercept_captcha(
                                    page=page,
                                    url=url,
                                    captcha_types=captcha_types,
                                    page_title=captcha_title,
                                )
                                if status == CaptchaStatus.RESOLVED:
                                    await page.wait_for_timeout(2000)
                                    recheck = await page.evaluate(_CAPTCHA_DETECT_JS)
                                    if recheck and recheck.get("detected"):
                                        logger.warning("CAPTCHA 人工处理后仍然存在，跳过: %s", recheck.get("types"))
                                    else:
                                        pass  # CAPTCHA 已通过，继续正常提取流程
                                else:
                                    return {
                                        "chunks": [],
                                        "title": captcha_title,
                                        "jsonld": {"entry_count": 0},
                                        "last_modified": None,
                                        "fallback": True,
                                        "ugc_count": 0,
                                        "captcha": True,
                                        "captcha_types": captcha_types,
                                    }
                            else:
                                return {
                                    "chunks": [],
                                    "title": captcha_title,
                                    "jsonld": {"entry_count": 0},
                                    "last_modified": None,
                                    "fallback": True,
                                    "ugc_count": 0,
                                    "captcha": True,
                                    "captcha_types": captcha_types,
                                }
                        except ImportError:
                            return {
                                "chunks": [],
                                "title": captcha_title,
                                "jsonld": {"entry_count": 0},
                                "last_modified": None,
                                "fallback": True,
                                "ugc_count": 0,
                                "captcha": True,
                                "captcha_types": captcha_types,
                            }
                except Exception:
                    pass  # CAPTCHA 检测本身不应该阻断流程

                # 拟人化：模拟页面滚动
                try:
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 4)")
                    await page.wait_for_timeout(200)
                    await page.evaluate("window.scrollTo(0, 0)")
                except Exception:
                    pass

                await page.wait_for_timeout(1000)

                # Claim 粒度分块提取（Phase 1.5）
                chunk_result = await page.evaluate(_CHUNK_EXTRACT_JS)
                chunks = chunk_result.get("chunks", []) if chunk_result else []
                fallback = chunk_result.get("fallback", False) if chunk_result else True
                ugc_count = chunk_result.get("ugc_count", 0) if chunk_result else 0

                # 提取标题
                try:
                    title = await page.title()
                except Exception:
                    title = ""
                # 提取 JSON-LD 结构化数据
                try:
                    jsonld = await page.evaluate(_JSONLD_EXTRACT_JS)
                except Exception:
                    jsonld = {"entry_count": 0}
                # HTTP Last-Modified 头
                last_modified = None
                if response:
                    last_modified = response.headers.get("last-modified")

                # 成功提取后，保存 Cookie 状态（用于下次访问）
                if chunks and not fallback:
                    with contextlib.suppress(Exception):
                        await context.storage_state(path=self._storage_state_path)

                return {
                    "chunks": chunks or [],
                    "title": title or "",
                    "jsonld": jsonld or {"entry_count": 0},
                    "last_modified": last_modified,
                    "fallback": fallback,
                    "ugc_count": ugc_count,
                    "captcha": False,
                }

            except Exception as e:
                logger.debug("页面渲染失败: url=%s err=%s", url, str(e)[:100])
                # Context 可能已损坏，从池中移除
                await self._session_pool.invalidate(session_key)
                return {
                    "chunks": [],
                    "title": "",
                    "jsonld": {"entry_count": 0},
                    "last_modified": None,
                    "fallback": True,
                    "ugc_count": 0,
                }
            finally:
                # 只关闭 Page，不关闭 Context（Context 由 SessionPool 管理）
                if page is not None:
                    with contextlib.suppress(Exception):
                        await page.close()

    async def close(self) -> None:
        """关闭浏览器实例（应用关闭时调用）"""
        # 先清理所有 Context
        await self._session_pool.cleanup()
        if self._browser:
            with contextlib.suppress(Exception):
                await self._browser.close()
            self._browser = None
        if self._playwright:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
            self._playwright = None
        logger.info("Playwright 浏览器已关闭")


# 全局单例（延迟初始化）
_instance: PlaywrightWebSearch | None = None
_instance_loop: asyncio.AbstractEventLoop | None = None


def get_playwright_search() -> PlaywrightWebSearch:
    """获取全局 PlaywrightWebSearch 单例（循环感知：不同循环自动重建）"""
    global _instance, _instance_loop
    try:
        cur_loop = asyncio.get_running_loop()
    except RuntimeError:
        cur_loop = None
    need_new = (
        _instance is None
        or _instance_loop is None
        or _instance_loop.is_closed()
        or cur_loop is None
        or _instance_loop is not cur_loop
    )
    if need_new:
        _instance = PlaywrightWebSearch()
        _instance_loop = cur_loop
    assert _instance is not None
    return _instance


async def close_playwright_search() -> None:
    """关闭全局 PlaywrightWebSearch 实例（应用关闭时调用）"""
    global _instance
    if _instance is not None:
        await _instance.close()
        _instance = None
