import asyncio
import contextlib
import logging
from typing import Any

from . import _STEALTH_JS  # 开源版为空字符串，不注入反检测脚本

logger = logging.getLogger("app.tools.playwright.session_pool")


class SessionPool:
    """浏览器 Context 池：按 session_key 分配持久化 Context。

    设计目标：
    - 同一 Agent（由 session_key 标识）的所有搜索复用同一个 BrowserContext
    - Context 保持 Cookie / localStorage / 搜索历史，保证话题一致性
    - 当 Context 故障（连接断开、超时等）时自动切换为新 Context
    - 浏览器重启时清空所有 Context（因为旧的 Context 已失效）

    Lifecycle:
        pool = SessionPool()
        ctx = await pool.get(agent_id, browser, **kwargs)
        # ... 使用 ctx 进行多次搜索 ...
        await pool.invalidate(agent_id)  # 出问题时切换
        await pool.cleanup()  # 应用关闭时
    """

    def __init__(self) -> None:
        self._contexts: dict[str, Any] = {}  # session_key → BrowserContext
        self._lock = asyncio.Lock()

    async def get(
        self,
        session_key: str,
        browser: Any,
        **ctx_kwargs: Any,
    ) -> Any:
        """获取或创建 session_key 对应的 Context。

        如果已有健康的 Context 则直接返回；否则创建新 Context 并注入反检测脚本。
        """
        if session_key in self._contexts:
            ctx = self._contexts[session_key]
            # 健康检查：尝试获取 pages（轻量操作，不会触发网络请求）
            try:
                _ = ctx.pages
                return ctx
            except Exception:
                logger.warning("SessionPool: session_key=%s 的 Context 已失效，重建...", session_key[:20])
                # 尝试关闭旧 Context（best-effort）
                with contextlib.suppress(Exception):
                    await ctx.close()
                del self._contexts[session_key]

        async with self._lock:
            # 双重检查（可能其他协程已创建）
            if session_key in self._contexts:
                return self._contexts[session_key]

            ctx = await browser.new_context(**ctx_kwargs)
            if _STEALTH_JS:  # 开源版为空字符串时跳过
                await ctx.add_init_script(_STEALTH_JS)
            self._contexts[session_key] = ctx
            logger.info("SessionPool: 创建新 Context (session_key=%s, total=%d)", session_key[:20], len(self._contexts))
            return ctx

    async def invalidate(self, session_key: str) -> None:
        """标记 session_key 的 Context 为无效，下次 get() 将创建新的。"""
        if session_key in self._contexts:
            ctx = self._contexts.pop(session_key)
            with contextlib.suppress(Exception):
                await ctx.close()
            logger.info(
                "SessionPool: 销毁 Context (session_key=%s, remaining=%d)", session_key[:20], len(self._contexts)
            )

    def clear(self) -> None:
        """清空所有 Context 引用（不关闭，浏览器已重启时 context 自动失效）。"""
        self._contexts.clear()

    def get_stats(self) -> tuple[int, list[str]]:
        """返回 (会话数, 会话键列表)，供外部监控使用。

        不暴露内部数据结构，保持封装性。
        """
        return len(self._contexts), list(self._contexts.keys())

    async def cleanup(self) -> None:
        """关闭所有 Context 并清空。"""
        for key in list(self._contexts.keys()):
            with contextlib.suppress(Exception):
                await self._contexts[key].close()
        self._contexts.clear()
        logger.info("SessionPool: 已清理全部 Context")
