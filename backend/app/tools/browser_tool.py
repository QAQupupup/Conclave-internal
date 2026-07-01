# BrowserTool：Agent 可用的浏览器操作工具集
#
# 基于 Playwright，封装 6 大类操作供 Agent 调用：
# 1. 导航 — goto / back / forward / reload / get_url / get_title
# 2. 交互 — click / fill / type / press / scroll / hover / select / check / drag
# 3. 提取 — get_text / get_html / get_attribute / extract_content / evaluate / screenshot
# 4. 查询 — find_elements / find_by_text / find_by_role / wait_for_element
# 5. 注入 — evaluate / add_script / expose_function
# 6. 标签 — new_tab / switch_tab / close_tab / get_tabs
#
# 设计原则（来自 Browser Use / Stagehand / AgentQL 调研）：
# - Locator-first：用 Playwright Locator（非 ElementHandle），自动等待+重试
# - 语义定位优先：get_by_role > get_by_text > get_by_label > CSS
# - 反检测内置：addInitScript 覆盖自动化指纹
# - 异常隔离：每个操作独立 try/except，返回结构化结果
# - 延迟初始化：首次使用才启动浏览器，关闭时自动清理
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, Optional

from .playwright_search import _STEALTH_JS, _USER_AGENT

logger = logging.getLogger("app.tools.browser_tool")


class BrowserTool:
    """Agent 浏览器操作工具

    封装 Playwright，提供 Agent 友好的高级 API。

    用法::

        tool = get_browser_tool()
        await tool.goto("https://example.com")
        title = await tool.get_title()
        await tool.click("Login", strategy="text")
        text = await tool.extract_content()
        await tool.screenshot("page.png")

    所有方法返回结构化结果或抛出异常（由调用方捕获）。
    """

    def __init__(self) -> None:
        self._browser = None
        self._playwright = None
        self._context: Optional[Any] = None
        self._page: Optional[Any] = None
        self._tabs: list[Any] = []
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(5)  # 并发操作限制

    # ================================================================
    # 生命周期管理
    # ================================================================

    async def _ensure_browser(self) -> None:
        """延迟初始化浏览器（首次操作时启动）"""
        if self._browser is not None:
            return
        async with self._lock:
            if self._browser is not None:
                return
            from playwright.async_api import async_playwright

            logger.info("启动 BrowserTool Chromium 无头浏览器")
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-extensions",
                    "--no-first-run",
                    "--disable-default-apps",
                    "--window-size=1920,1080",
                ],
            )
            # 创建默认 context + page
            self._context = await self._browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="Asia/Shanghai",
                java_script_enabled=True,
            )
            # 反检测：在每个新页面 JS 执行前注入 stealth 脚本
            await self._context.add_init_script(_STEALTH_JS)
            self._page = await self._context.new_page()
            self._tabs = [self._page]

    @property
    def page(self) -> Any:
        """当前活动页面"""
        if self._page is None:
            raise RuntimeError("BrowserTool 未初始化，请先调用 goto()")
        return self._page

    async def close(self) -> None:
        """关闭浏览器（应用关闭时调用）"""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
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
        self._context = None
        self._page = None
        self._tabs = []
        logger.info("BrowserTool 浏览器已关闭")

    # ================================================================
    # 1. 导航
    # ================================================================

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 30000) -> dict[str, Any]:
        """导航到指定 URL

        Args:
            url: 目标 URL
            wait_until: 等待策略 — domcontentloaded(快) / load(默认) / networkidle(慢但完整)
            timeout: 超时（毫秒）

        Returns:
            {"url": 最终URL, "title": 页面标题, "status": "ok"|"error"}
        """
        await self._ensure_browser()
        async with self._semaphore:
            try:
                await self.page.goto(url, wait_until=wait_until, timeout=timeout)
                await self.page.wait_for_timeout(1000)  # 等待动态渲染
                title = await self.page.title()
                return {"url": self.page.url, "title": title, "status": "ok"}
            except Exception as e:
                logger.warning("导航失败: url=%s err=%s", url, str(e)[:100])
                return {"url": url, "title": "", "status": "error", "error": str(e)[:200]}

    async def back(self) -> dict[str, Any]:
        """后退"""
        await self._ensure_browser()
        try:
            response = await self.page.go_back(wait_until="domcontentloaded")
            await self.page.wait_for_timeout(500)
            return {"url": self.page.url, "status": "ok" if response else "no_history"}
        except Exception as e:
            return {"url": self.page.url, "status": "error", "error": str(e)[:200]}

    async def forward(self) -> dict[str, Any]:
        """前进"""
        await self._ensure_browser()
        try:
            response = await self.page.go_forward(wait_until="domcontentloaded")
            await self.page.wait_for_timeout(500)
            return {"url": self.page.url, "status": "ok" if response else "no_history"}
        except Exception as e:
            return {"url": self.page.url, "status": "error", "error": str(e)[:200]}

    async def reload(self, wait_until: str = "domcontentloaded") -> dict[str, Any]:
        """重新加载当前页"""
        await self._ensure_browser()
        try:
            await self.page.reload(wait_until=wait_until)
            await self.page.wait_for_timeout(1000)
            return {"url": self.page.url, "status": "ok"}
        except Exception as e:
            return {"url": self.page.url, "status": "error", "error": str(e)[:200]}

    async def get_url(self) -> str:
        """获取当前页面 URL"""
        await self._ensure_browser()
        return self.page.url

    async def get_title(self) -> str:
        """获取当前页面标题"""
        await self._ensure_browser()
        return await self.page.title()

    # ================================================================
    # 2. 交互
    # ================================================================

    def _resolve_locator(self, selector: str, strategy: str = "auto") -> Any:
        """将 (selector, strategy) 解析为 Playwright Locator

        strategy:
        - auto: 智能推断（含文字用 text，含 // 用 xpath，其余当 CSS）
        - role: 按 ARIA 角色定位（selector 格式: "role:Button" 或 "button"）
        - text: 按可见文本定位
        - label: 按表单 label 定位
        - placeholder: 按 placeholder 定位
        - css: CSS 选择器
        - xpath: XPath 表达式
        - test_id: 按 data-testid 定位
        """
        p = self.page
        if strategy == "auto":
            if selector.startswith("//") or selector.startswith("xpath="):
                return p.locator(selector)
            if selector.startswith("#") or selector.startswith(".") or ">" in selector or "[" in selector:
                return p.locator(selector)
            return p.get_by_text(selector)
        elif strategy == "role":
            # 支持 "button" 或 "button:Submit" 格式
            parts = selector.split(":", 1)
            role = parts[0]
            name = parts[1] if len(parts) > 1 else None
            return p.get_by_role(role, name=name) if name else p.get_by_role(role)
        elif strategy == "text":
            return p.get_by_text(selector)
        elif strategy == "label":
            return p.get_by_label(selector)
        elif strategy == "placeholder":
            return p.get_by_placeholder(selector)
        elif strategy == "css":
            return p.locator(selector)
        elif strategy == "xpath":
            return p.locator(f"xpath={selector}")
        elif strategy == "test_id":
            return p.get_by_test_id(selector)
        else:
            return p.locator(selector)

    async def click(self, selector: str, strategy: str = "auto", timeout: int = 10000) -> dict[str, Any]:
        """点击元素

        Args:
            selector: 元素定位符
            strategy: 定位策略（auto/role/text/label/css/xpath/test_id）
            timeout: 超时毫秒

        Returns:
            {"status": "ok"|"error", "selector": selector}
        """
        await self._ensure_browser()
        async with self._semaphore:
            try:
                loc = self._resolve_locator(selector, strategy)
                await loc.click(timeout=timeout)
                return {"status": "ok", "selector": selector}
            except Exception as e:
                logger.debug("点击失败: %s err=%s", selector, str(e)[:100])
                return {"status": "error", "selector": selector, "error": str(e)[:200]}

    async def fill(self, selector: str, value: str, strategy: str = "auto", timeout: int = 10000) -> dict[str, Any]:
        """清空并填入文本（适合表单输入）

        Args:
            selector: 元素定位符
            value: 要填入的文本
        """
        await self._ensure_browser()
        async with self._semaphore:
            try:
                loc = self._resolve_locator(selector, strategy)
                await loc.fill(value, timeout=timeout)
                return {"status": "ok", "selector": selector, "value": value}
            except Exception as e:
                return {"status": "error", "selector": selector, "error": str(e)[:200]}

    async def type(self, selector: str, text: str, strategy: str = "auto", delay: int = 50, timeout: int = 10000) -> dict[str, Any]:
        """逐字符输入（模拟真实打字，触发联想/自动补全）

        Args:
            selector: 元素定位符
            text: 要输入的文本
            delay: 每个字符间隔毫秒
        """
        await self._ensure_browser()
        async with self._semaphore:
            try:
                loc = self._resolve_locator(selector, strategy)
                await loc.type(text, delay=delay, timeout=timeout)
                return {"status": "ok", "selector": selector, "text": text}
            except Exception as e:
                return {"status": "error", "selector": selector, "error": str(e)[:200]}

    async def press(self, key: str, selector: Optional[str] = None, strategy: str = "auto") -> dict[str, Any]:
        """按键

        Args:
            key: 按键名（如 "Enter", "Escape", "Control+a", "Tab"）
            selector: 可选，在指定元素上按键；不指定则在当前焦点元素上按键
        """
        await self._ensure_browser()
        try:
            if selector:
                loc = self._resolve_locator(selector, strategy)
                await loc.press(key)
            else:
                await self.page.keyboard.press(key)
            return {"status": "ok", "key": key}
        except Exception as e:
            return {"status": "error", "key": key, "error": str(e)[:200]}

    async def scroll(self, direction: str = "down", amount: int = 500, selector: Optional[str] = None) -> dict[str, Any]:
        """滚动页面或元素

        Args:
            direction: "up" / "down"
            amount: 像素数
            selector: 可选，在指定元素内滚动；不指定则滚动整个页面
        """
        await self._ensure_browser()
        try:
            if selector:
                loc = self._resolve_locator(selector, "auto")
                await loc.scroll_into_view_if_needed()
            else:
                delta = amount if direction == "down" else -amount
                await self.page.mouse.wheel(0, delta)
                await self.page.wait_for_timeout(300)
            return {"status": "ok", "direction": direction, "amount": amount}
        except Exception as e:
            return {"status": "error", "error": str(e)[:200]}

    async def hover(self, selector: str, strategy: str = "auto", timeout: int = 10000) -> dict[str, Any]:
        """悬停（触发悬浮菜单/下拉）"""
        await self._ensure_browser()
        try:
            loc = self._resolve_locator(selector, strategy)
            await loc.hover(timeout=timeout)
            return {"status": "ok", "selector": selector}
        except Exception as e:
            return {"status": "error", "selector": selector, "error": str(e)[:200]}

    async def select(self, selector: str, value: Optional[str] = None, label: Optional[str] = None, strategy: str = "auto") -> dict[str, Any]:
        """下拉选择

        Args:
            selector: <select> 元素定位符
            value: 按 option value 选择
            label: 按 option 文本选择
        """
        await self._ensure_browser()
        try:
            loc = self._resolve_locator(selector, strategy)
            if label:
                await loc.select_option(label=label)
            elif value:
                await loc.select_option(value=value)
            else:
                return {"status": "error", "error": "需指定 value 或 label"}
            return {"status": "ok", "selector": selector, "value": value, "label": label}
        except Exception as e:
            return {"status": "error", "selector": selector, "error": str(e)[:200]}

    async def check(self, selector: str, strategy: str = "auto", checked: bool = True) -> dict[str, Any]:
        """勾选/取消勾选 checkbox/radio

        Args:
            selector: checkbox/radio 元素定位符
            checked: True=勾选, False=取消勾选
        """
        await self._ensure_browser()
        try:
            loc = self._resolve_locator(selector, strategy)
            if checked:
                await loc.check()
            else:
                await loc.uncheck()
            return {"status": "ok", "selector": selector, "checked": checked}
        except Exception as e:
            return {"status": "error", "selector": selector, "error": str(e)[:200]}

    async def drag(self, source: str, target: str, strategy: str = "auto") -> dict[str, Any]:
        """拖拽元素

        Args:
            source: 源元素定位符
            target: 目标元素定位符
        """
        await self._ensure_browser()
        try:
            src_loc = self._resolve_locator(source, strategy)
            tgt_loc = self._resolve_locator(target, strategy)
            await src_loc.drag_to(tgt_loc)
            return {"status": "ok", "source": source, "target": target}
        except Exception as e:
            return {"status": "error", "source": source, "target": target, "error": str(e)[:200]}

    # ================================================================
    # 3. 内容提取
    # ================================================================

    async def get_text(self, selector: Optional[str] = None, strategy: str = "auto") -> str:
        """获取元素文本内容

        Args:
            selector: 元素定位符；不指定则获取整个页面 body 文本

        Returns:
            元素的 textContent
        """
        await self._ensure_browser()
        if selector:
            loc = self._resolve_locator(selector, strategy)
            return await loc.text_content() or ""
        return await self.page.inner_text("body")

    async def get_html(self, selector: Optional[str] = None, strategy: str = "auto") -> str:
        """获取元素 HTML

        Args:
            selector: 元素定位符；不指定则获取整页 HTML
        """
        await self._ensure_browser()
        if selector:
            loc = self._resolve_locator(selector, strategy)
            return await loc.inner_html()
        return await self.page.content()

    async def get_attribute(self, selector: str, attribute: str, strategy: str = "auto") -> Optional[str]:
        """获取元素属性值

        Args:
            selector: 元素定位符
            attribute: 属性名（如 "href", "src", "class", "data-id"）
        """
        await self._ensure_browser()
        loc = self._resolve_locator(selector, strategy)
        return await loc.get_attribute(attribute)

    async def extract_content(self, max_length: int = 5000) -> str:
        """提取页面正文内容（去除广告/导航/侧边栏等噪声）

        使用智能提取算法：优先 article/main 标签，移除噪声 DOM 后提取纯文本。
        类似 Mozilla Readability 的效果，但纯 JS 实现。

        Args:
            max_length: 最大字符数

        Returns:
            页面正文纯文本
        """
        await self._ensure_browser()
        # 延迟导入提取脚本（与 playwright_search 共享）
        from .playwright_search import _EXTRACT_JS
        content = await self.page.evaluate(_EXTRACT_JS)
        if content and len(content) > max_length:
            content = content[:max_length] + "..."
        return content or ""

    async def extract_structured(self, selector: str, fields: dict[str, str], strategy: str = "auto") -> dict[str, Any]:
        """结构化数据提取（类似 Stagehand extract + Zod）

        从匹配的元素列表中，按字段定义提取结构化数据。

        Args:
            selector: 元素列表定位符（如 "li.product" / "tr.data-row"）
            fields: 字段定义 {"字段名": "CSS子选择器或提取方式"}
                    提取方式：".class" → textContent, "@attr" → 属性值, "$html" → innerHTML
            strategy: 定位策略

        Returns:
            {"count": N, "items": [{...}, ...]}
        """
        await self._ensure_browser()
        loc = self._resolve_locator(selector, strategy)
        count = await loc.count()
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
                            item[field_name] = await loc.nth(i).inner_html()
                        elif prop == "text":
                            item[field_name] = await loc.nth(i).inner_text()
                    else:
                        child_loc = loc.nth(i).locator(extractor)
                        item[field_name] = await child_loc.text_content()
                except Exception:
                    item[field_name] = None
            items.append(item)
        return {"count": count, "items": items}

    async def screenshot(self, path: Optional[str] = None, full_page: bool = False, selector: Optional[str] = None, strategy: str = "auto") -> dict[str, Any]:
        """截图

        Args:
            path: 保存路径；不指定则返回 base64 编码
            full_page: 是否截取完整页面（滚动长截图）
            selector: 可选，截取指定元素

        Returns:
            {"status": "ok", "path": "..."} 或 {"status": "ok", "base64": "..."}
        """
        await self._ensure_browser()
        try:
            if selector:
                loc = self._resolve_locator(selector, strategy)
                if path:
                    await loc.screenshot(path=path)
                    return {"status": "ok", "path": path}
                else:
                    buf = await loc.screenshot()
                    return {"status": "ok", "base64": base64.b64encode(buf).decode()}
            else:
                if path:
                    await self.page.screenshot(path=path, full_page=full_page)
                    return {"status": "ok", "path": path, "full_page": full_page}
                else:
                    buf = await self.page.screenshot(full_page=full_page)
                    return {"status": "ok", "base64": base64.b64encode(buf).decode(), "full_page": full_page}
        except Exception as e:
            return {"status": "error", "error": str(e)[:200]}

    # ================================================================
    # 4. 元素查询
    # ================================================================

    async def find_elements(self, selector: str, strategy: str = "auto") -> list[dict[str, Any]]:
        """查找元素列表，返回每个元素的摘要信息

        Args:
            selector: 元素定位符
            strategy: 定位策略

        Returns:
            [{"index": 0, "tag": "a", "text": "...", "href": "...", "visible": true}, ...]
        """
        await self._ensure_browser()
        loc = self._resolve_locator(selector, strategy)
        count = await loc.count()
        results: list[dict[str, Any]] = []
        for i in range(count):
            el = loc.nth(i)
            tag = await el.evaluate("el => el.tagName.toLowerCase()")
            text = (await el.text_content() or "")[:100]
            visible = await el.is_visible()
            info: dict[str, Any] = {"index": i, "tag": tag, "text": text, "visible": visible}
            # 提取常用属性
            for attr in ["href", "src", "id", "class", "value", "name", "type", "placeholder", "role", "aria-label"]:
                val = await el.get_attribute(attr)
                if val:
                    info[attr] = val[:100]
            results.append(info)
        return results

    async def find_by_text(self, text: str, exact: bool = False) -> list[dict[str, Any]]:
        """按可见文本查找元素

        Args:
            text: 要查找的文本
            exact: 是否精确匹配
        """
        await self._ensure_browser()
        loc = self.page.get_by_text(text, exact=exact)
        return await self._summarize_locator(loc)

    async def find_by_role(self, role: str, name: Optional[str] = None) -> list[dict[str, Any]]:
        """按 ARIA 角色查找元素

        Args:
            role: ARIA 角色（如 "button", "link", "textbox", "checkbox", "heading"）
            name: 可选，可访问名称
        """
        await self._ensure_browser()
        loc = self.page.get_by_role(role, name=name) if name else self.page.get_by_role(role)
        return await self._summarize_locator(loc)

    async def _summarize_locator(self, loc: Any) -> list[dict[str, Any]]:
        """将 Locator 结果转为摘要列表"""
        count = await loc.count()
        results: list[dict[str, Any]] = []
        for i in range(count):
            el = loc.nth(i)
            tag = await el.evaluate("el => el.tagName.toLowerCase()")
            text = (await el.text_content() or "")[:100]
            visible = await el.is_visible()
            results.append({"index": i, "tag": tag, "text": text, "visible": visible})
        return results

    async def wait_for_element(self, selector: str, strategy: str = "auto", state: str = "visible", timeout: int = 10000) -> dict[str, Any]:
        """等待元素达到指定状态

        Args:
            selector: 元素定位符
            state: "visible" / "hidden" / "attached" / "detached"
            timeout: 超时毫秒

        Returns:
            {"status": "ok"|"timeout", "selector": selector}
        """
        await self._ensure_browser()
        try:
            loc = self._resolve_locator(selector, strategy)
            await loc.wait_for(state=state, timeout=timeout)
            return {"status": "ok", "selector": selector}
        except Exception as e:
            return {"status": "timeout", "selector": selector, "error": str(e)[:200]}

    # ================================================================
    # 5. JS 注入
    # ================================================================

    async def evaluate(self, expression: str, arg: Any = None) -> Any:
        """在页面上下文执行 JS 表达式

        通过 CDP 在 V8 引擎层执行，不经过 DevTools 面板，
        不受页面反调试手段影响。

        Args:
            expression: JS 表达式或箭头函数
            arg: 可选参数，传入 JS 函数

        Returns:
            JS 执行结果（可序列化值）
        """
        await self._ensure_browser()
        return await self.page.evaluate(expression, arg)

    async def evaluate_on(self, selector: str, expression: str, strategy: str = "auto", arg: Any = None) -> Any:
        """在匹配的首个元素上执行 JS

        Args:
            selector: 元素定位符
            expression: JS 箭头函数，首参为元素（如 el => el.value）
        """
        await self._ensure_browser()
        loc = self._resolve_locator(selector, strategy)
        return await loc.evaluate(expression, arg)

    async def add_script(self, content: Optional[str] = None, url: Optional[str] = None) -> dict[str, Any]:
        """注入 <script> 标签到当前页面

        Args:
            content: JS 代码内容
            url: 外部脚本 URL
        """
        await self._ensure_browser()
        try:
            if url:
                await self.page.add_script_tag(url=url)
            elif content:
                await self.page.add_script_tag(content=content)
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "error": str(e)[:200]}

    async def expose_function(self, name: str, callback: Any) -> dict[str, Any]:
        """将 Python 函数暴露到页面 JS 上下文

        页面 JS 可通过 window[name](...) 调用 Python 函数。

        Args:
            name: 在 window 上注册的函数名
            callback: Python 回调函数
        """
        await self._ensure_browser()
        try:
            await self._context.expose_function(name, callback)
            return {"status": "ok", "name": name}
        except Exception as e:
            return {"status": "error", "name": name, "error": str(e)[:200]}

    # ================================================================
    # 6. 标签页管理
    # ================================================================

    async def new_tab(self, url: Optional[str] = None) -> dict[str, Any]:
        """新建标签页

        Args:
            url: 可选，新标签页打开的 URL
        """
        await self._ensure_browser()
        try:
            new_page = await self._context.new_page()
            self._tabs.append(new_page)
            self._page = new_page  # 切换到新标签
            if url:
                await self.goto(url)
            return {"status": "ok", "tab_index": len(self._tabs) - 1, "url": url or "about:blank"}
        except Exception as e:
            return {"status": "error", "error": str(e)[:200]}

    async def switch_tab(self, index: int) -> dict[str, Any]:
        """切换到指定标签页

        Args:
            index: 标签页索引（0-based）
        """
        await self._ensure_browser()
        if 0 <= index < len(self._tabs):
            self._page = self._tabs[index]
            await self._page.bring_to_front()
            return {"status": "ok", "tab_index": index, "url": self._page.url}
        return {"status": "error", "error": f"标签页索引 {index} 超出范围（共 {len(self._tabs)} 个）"}

    async def close_tab(self, index: Optional[int] = None) -> dict[str, Any]:
        """关闭标签页

        Args:
            index: 要关闭的标签页索引；不指定则关闭当前标签
        """
        await self._ensure_browser()
        target_idx = index if index is not None else self._tabs.index(self._page)
        if 0 <= target_idx < len(self._tabs):
            tab = self._tabs[target_idx]
            await tab.close()
            self._tabs.pop(target_idx)
            if self._tabs:
                self._page = self._tabs[0]  # 切回第一个标签
            else:
                self._page = None
            return {"status": "ok", "closed_index": target_idx, "remaining": len(self._tabs)}
        return {"status": "error", "error": "无可关闭的标签页"}

    async def get_tabs(self) -> list[dict[str, Any]]:
        """获取所有标签页信息

        Returns:
            [{"index": 0, "url": "...", "title": "...", "active": true}, ...]
        """
        await self._ensure_browser()
        tabs: list[dict[str, Any]] = []
        for i, tab in enumerate(self._tabs):
            try:
                title = await tab.title()
            except Exception:
                title = ""
            tabs.append({
                "index": i,
                "url": tab.url,
                "title": title,
                "active": tab == self._page,
            })
        return tabs

    # ================================================================
    # 7. 辅助方法
    # ================================================================

    async def get_page_snapshot(self) -> str:
        """获取页面 ARIA 快照（YAML 格式，含 ref 引用）

        适合 LLM Agent 理解页面结构。
        """
        await self._ensure_browser()
        try:
            return await self.page.accessibility.snapshot(interesting_only=True) or ""
        except Exception:
            return ""

    async def get_links(self) -> list[dict[str, str]]:
        """提取页面所有链接

        Returns:
            [{"text": "...", "href": "..."}, ...]
        """
        await self._ensure_browser()
        return await self.page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]')).map(a => ({
                text: (a.textContent || '').trim().substring(0, 100),
                href: a.href,
            })).filter(l => l.href)
        """)

    async def get_forms(self) -> list[dict[str, Any]]:
        """提取页面所有表单及其字段

        Returns:
            [{"action": "...", "method": "...", "fields": [{"name": "...", "type": "...", "label": "..."}]}]
        """
        await self._ensure_browser()
        return await self.page.evaluate("""
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


# ================================================================
# 全局单例
# ================================================================

_instance: BrowserTool | None = None


def get_browser_tool() -> BrowserTool:
    """获取全局 BrowserTool 单例"""
    global _instance
    if _instance is None:
        _instance = BrowserTool()
    return _instance


async def close_browser_tool() -> None:
    """关闭全局 BrowserTool 实例（应用关闭时调用）"""
    global _instance
    if _instance is not None:
        await _instance.close()
        _instance = None
