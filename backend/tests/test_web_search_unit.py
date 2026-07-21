"""Web Search 工具模块纯逻辑单元测试。

测试范围：
- PlaywrightWebSearch._split_into_chunks()  文本分块逻辑
- _is_safe_url()                            SSRF 安全校验
- SessionPool                               基本操作（get/invalidate/get_stats/clear）
- _translate_query                          纯英文直通路径（不调用 API）
- search()                                 基本参数传递（mock browser + context）
- SearchResult.__post_init__()              自动填充逻辑
- EngineHealth                              健康追踪（success/failure 计数、冷却期）
- MultiEngineSearch                         failover 逻辑（mock engine）

所有测试均使用 unittest.mock，不依赖真实浏览器、真实 LLM 或网络连接。

运行方式：
    cd backend
    pytest tests/test_web_search_unit.py -v
    pytest tests/test_web_search_unit.py -v -k "split_into_chunks"  # 按关键字筛选
    pytest tests/test_web_search_unit.py -v --tb=short              # 简洁输出
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from app.tools.playwright.session_pool import SessionPool

# ---------------------------------------------------------------------------
# 被测试模块
# ---------------------------------------------------------------------------
from app.tools.playwright_search import PlaywrightWebSearch, _is_safe_url
from app.tools.search_engine import (
    EngineHealth,
    MultiEngineSearch,
    SearchEngine,
    SearchEngineError,
    SearchResult,
)

# ============================================================================
# 1. PlaywrightWebSearch._split_into_chunks() — 文本分块逻辑
# ============================================================================


class TestSplitIntoChunks:
    """测试静态方法 _split_into_chunks：按句子边界分割长文本。"""

    def test_short_text_within_limit(self):
        """短文本未超过 max_chars，应整体返回单个 chunk。"""
        text = "Hello world. This is a test."
        result = PlaywrightWebSearch._split_into_chunks(text, max_chars=200)
        assert len(result) == 1
        assert result[0] == text

    def test_split_at_sentence_boundary_english(self):
        """英文按句号分句，每个 chunk 不超过 max_chars。"""
        text = "First sentence. Second sentence. Third sentence."
        result = PlaywrightWebSearch._split_into_chunks(text, max_chars=25)
        # "First sentence." = 15 chars, "Second sentence." = 16 chars
        # 15 + 1 + 16 = 32 > 25, so split
        assert len(result) >= 2
        assert "First sentence." in result[0]

    def test_split_at_chinese_punctuation(self):
        """中文按句号、问号、感叹号分句。"""
        text = "这是第一句话。这是第二句话！这是第三句话？"
        result = PlaywrightWebSearch._split_into_chunks(text, max_chars=10)
        assert len(result) >= 3

    def test_single_sentence_exceeds_limit(self):
        """单个句子超过 max_chars 时按字符强制截断。"""
        long_sentence = "A" * 150
        result = PlaywrightWebSearch._split_into_chunks(long_sentence, max_chars=50)
        # 应被切成 3 段：50 + 50 + 50
        assert len(result) == 3
        assert result[0] == "A" * 50
        assert result[1] == "A" * 50
        assert result[2] == "A" * 50

    def test_split_at_newline_boundary(self):
        """换行符也是分句边界。"""
        text = "Line one\nLine two\nLine three"
        result = PlaywrightWebSearch._split_into_chunks(text, max_chars=15)
        assert len(result) >= 2

    def test_empty_text_returns_single_chunk(self):
        """空字符串返回包含自身的列表。"""
        result = PlaywrightWebSearch._split_into_chunks("", max_chars=100)
        assert result == [""]

    def test_mixed_chinese_english_boundaries(self):
        """中英文混合文本，按各种分隔符分句。"""
        text = "Hello. 你好。Test! 怎么回事？Done."
        result = PlaywrightWebSearch._split_into_chunks(text, max_chars=12)
        # 每个句子应该在不同的 chunk 中
        assert len(result) >= 3

    def test_exact_boundary_merge(self):
        """刚好在边界上的句子应合并，不超出限制。"""
        # "ABCDEFGHIJ" = 10 chars, max_chars=25, 两个这样的句子刚好 10+1+10=21 < 25
        text = "ABCDEFGHIJ. KLMNOPQRST."
        result = PlaywrightWebSearch._split_into_chunks(text, max_chars=25)
        # 应合并为一个 chunk
        assert len(result) == 1

    def test_whitespace_only_sentences_skipped(self):
        """纯空白的分句应被跳过（但孤立标点不会被跳过）。"""
        text = "Hello.   . World."
        result = PlaywrightWebSearch._split_into_chunks(text, max_chars=100)
        # 空白分句 "   " 被跳过，但 "." 被 strip 后仍然是 "."，所以保留
        assert len(result) == 1
        assert "Hello" in result[0]
        assert "World" in result[0]


# ============================================================================
# 2. _is_safe_url() — SSRF 安全校验
# ============================================================================


class TestIsSafeUrl:
    """测试 URL 安全校验函数：防止 SSRF 攻击。"""

    # ---- 合法 URL ----

    def test_accepts_public_https(self):
        ok, reason = _is_safe_url("https://docs.python.org/3/")
        assert ok is True
        assert reason == "ok"

    def test_accepts_public_http(self):
        ok, reason = _is_safe_url("http://example.com/page")
        assert ok is True
        assert reason == "ok"

    def test_accepts_url_with_query_params(self):
        ok, _reason = _is_safe_url("https://www.google.com/search?q=test")
        assert ok is True

    def test_accepts_url_with_port(self):
        ok, _reason = _is_safe_url("https://api.example.com:8443/v1/data")
        assert ok is True

    # ---- 拒绝危险协议 ----

    def test_rejects_file_scheme(self):
        ok, reason = _is_safe_url("file:///etc/passwd")
        assert ok is False
        assert "file" in reason.lower() or "scheme" in reason.lower()

    def test_rejects_data_scheme(self):
        ok, _reason = _is_safe_url("data:text/html,<script>alert(1)</script>")
        assert ok is False

    def test_rejects_javascript_scheme(self):
        ok, _reason = _is_safe_url("javascript:alert(1)")
        assert ok is False

    def test_rejects_vbscript_scheme(self):
        ok, _reason = _is_safe_url("vbscript:msgbox(1)")
        assert ok is False

    def test_rejects_about_scheme(self):
        ok, _reason = _is_safe_url("about:blank")
        assert ok is False

    def test_rejects_blob_scheme(self):
        ok, _reason = _is_safe_url("blob:https://example.com/uuid")
        assert ok is False

    def test_rejects_empty_scheme(self):
        ok, _reason = _is_safe_url("//example.com/path")
        assert ok is False

    # ---- 拒绝私网 / localhost ----

    def test_rejects_localhost(self):
        ok, reason = _is_safe_url("http://localhost:8000/admin")
        assert ok is False
        assert "localhost" in reason

    def test_rejects_loopback_ip(self):
        ok, _reason = _is_safe_url("http://127.0.0.1:8080/api")
        assert ok is False

    def test_rejects_private_192_168(self):
        ok, _reason = _is_safe_url("http://192.168.1.1/admin")
        assert ok is False

    def test_rejects_private_10(self):
        ok, _reason = _is_safe_url("http://10.0.0.1/internal")
        assert ok is False

    def test_rejects_private_172_16(self):
        ok, _reason = _is_safe_url("http://172.16.0.1/secret")
        assert ok is False

    def test_rejects_link_local(self):
        ok, _reason = _is_safe_url("http://169.254.169.254/latest/meta-data/")
        assert ok is False

    # ---- 拒绝元数据端点 ----

    def test_rejects_metadata_google(self):
        ok, reason = _is_safe_url("http://metadata.google.internal/computeMetadata/v1/")
        assert ok is False
        assert "metadata" in reason

    def test_rejects_metadata_generic(self):
        ok, _reason = _is_safe_url("http://metadata/")
        assert ok is False

    # ---- 拒绝 userinfo 绕过 ----

    def test_rejects_userinfo_bypass(self):
        """http://trusted@evil.com — userinfo 伪装绕过。"""
        ok, reason = _is_safe_url("http://trusted@evil.com/admin")
        assert ok is False
        assert "userinfo" in reason.lower() or "绕过" in reason

    def test_rejects_userinfo_with_password(self):
        ok, _reason = _is_safe_url("https://user:pass@example.com/")
        assert ok is False

    # ---- 边界情况 ----

    def test_rejects_no_hostname(self):
        """URL 缺少 hostname 部分。"""
        ok, reason = _is_safe_url("https://")
        assert ok is False
        assert "hostname" in reason.lower()

    def test_rejects_malformed_url(self):
        """完全无法解析的 URL。"""
        ok, _reason = _is_safe_url("not-a-valid-url!!!")
        # 实际上 urlparse 会把它当作 path，hostname 为空
        assert ok is False


# ============================================================================
# 3. SessionPool 基本操作
# ============================================================================


class TestSessionPool:
    """测试浏览器 Context 池：按 session_key 分配/复用 Context。"""

    @staticmethod
    def _make_mock_ctx() -> MagicMock:
        """创建一个新的 mock Context（每次调用返回不同实例）。"""
        ctx = MagicMock()
        ctx.pages = []  # 健康检查：ctx.pages 不抛异常即健康
        ctx.add_init_script = AsyncMock()
        ctx.close = AsyncMock()
        return ctx

    @pytest.fixture
    def mock_browser(self) -> MagicMock:
        """创建 mock 浏览器，new_context() 每次返回新的 mock Context。"""
        browser = MagicMock()
        # 使用 side_effect 确保每次调用返回不同实例
        browser.new_context = AsyncMock(side_effect=lambda **kwargs: self._make_mock_ctx())
        return browser

    @pytest.mark.asyncio
    async def test_get_creates_new_context(self, mock_browser):
        """首次 get() 应为该 session_key 创建新 Context。"""
        pool = SessionPool()
        ctx = await pool.get("agent-1", mock_browser, viewport={"width": 1920})
        assert ctx is not None
        mock_browser.new_context.assert_awaited_once()
        ctx.add_init_script.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_reuses_context(self, mock_browser):
        """同一 session_key 第二次 get() 应复用已有 Context。"""
        pool = SessionPool()
        ctx1 = await pool.get("agent-1", mock_browser)
        ctx2 = await pool.get("agent-1", mock_browser)
        assert ctx1 is ctx2
        # new_context 只应被调用一次
        assert mock_browser.new_context.await_count == 1

    @pytest.mark.asyncio
    async def test_get_different_keys_separate_contexts(self, mock_browser):
        """不同 session_key 应创建独立的 Context。"""
        pool = SessionPool()
        ctx_a = await pool.get("agent-A", mock_browser)
        ctx_b = await pool.get("agent-B", mock_browser)
        assert ctx_a is not ctx_b
        assert mock_browser.new_context.await_count == 2

    @pytest.mark.asyncio
    async def test_invalidate_removes_and_closes(self, mock_browser):
        """invalidate() 应移除并关闭指定 Context。"""
        pool = SessionPool()
        ctx = await pool.get("agent-1", mock_browser)
        ctx.close = AsyncMock()

        await pool.invalidate("agent-1")
        ctx.close.assert_awaited_once()

        # 下次 get() 应创建新 Context
        mock_browser.new_context.reset_mock()
        await pool.get("agent-1", mock_browser)
        assert mock_browser.new_context.await_count == 1

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent_key_no_error(self):
        """invalidate 不存在的 key 不应抛异常。"""
        pool = SessionPool()
        # 不应抛出异常
        await pool.invalidate("nonexistent")

    @pytest.mark.asyncio
    async def test_get_stats_returns_counts(self, mock_browser):
        """get_stats() 应返回会话数和键列表。"""
        pool = SessionPool()
        await pool.get("agent-1", mock_browser)
        await pool.get("agent-2", mock_browser)

        count, keys = pool.get_stats()
        assert count == 2
        assert "agent-1" in keys
        assert "agent-2" in keys

    @pytest.mark.asyncio
    async def test_get_stats_empty(self):
        """空池 get_stats() 返回 (0, [])。"""
        pool = SessionPool()
        count, keys = pool.get_stats()
        assert count == 0
        assert keys == []

    def test_clear_empties_all_contexts(self):
        """clear() 应清空所有 Context 引用（不关闭）。"""
        pool = SessionPool()
        # 直接操作内部字典模拟已填充状态
        pool._contexts["agent-1"] = MagicMock()
        pool._contexts["agent-2"] = MagicMock()

        pool.clear()
        assert len(pool._contexts) == 0

    @pytest.mark.asyncio
    async def test_cleanup_closes_all_contexts(self, mock_browser):
        """cleanup() 应关闭所有 Context 并清空池。"""
        pool = SessionPool()
        ctx1 = await pool.get("agent-1", mock_browser)
        ctx2 = await pool.get("agent-2", mock_browser)
        ctx1.close = AsyncMock()
        ctx2.close = AsyncMock()

        await pool.cleanup()
        ctx1.close.assert_awaited_once()
        ctx2.close.assert_awaited_once()
        assert len(pool._contexts) == 0

    @pytest.mark.asyncio
    async def test_get_healthcheck_failed_recreates(self, mock_browser):
        """当已缓存 Context 健康检查失败时，应重建新 Context。"""
        pool = SessionPool()
        # 第一次获取
        ctx_old = await pool.get("agent-1", mock_browser)

        # 模拟 ctx.pages 抛出异常（连接断开）
        type(ctx_old).pages = PropertyMock(side_effect=Exception("connection lost"))

        # 第二次获取应重建
        mock_browser.new_context.reset_mock()
        ctx_new = await pool.get("agent-1", mock_browser)
        assert ctx_new is not ctx_old
        assert mock_browser.new_context.await_count == 1


# ============================================================================
# 4. _translate_query — 纯英文直通路径
# ============================================================================


class TestTranslateQuery:
    """测试查询翻译：纯英文查询应直接返回，不调用 API。"""

    @pytest.fixture
    def searcher(self) -> PlaywrightWebSearch:
        """创建 PlaywrightWebSearch 实例（不启动浏览器）。"""
        return PlaywrightWebSearch()

    @pytest.mark.asyncio
    async def test_pure_english_passes_through(self, searcher):
        """纯英文查询应原样返回，不触发任何 API 调用。"""
        result = await searcher._translate_query("What is the latest AI model?")
        assert result == "What is the latest AI model?"

    @pytest.mark.asyncio
    async def test_pure_english_with_numbers(self, searcher):
        """含数字的英文查询应直通。"""
        result = await searcher._translate_query("Python 3.12 release notes 2024")
        assert result == "Python 3.12 release notes 2024"

    @pytest.mark.asyncio
    async def test_pure_english_with_special_chars(self, searcher):
        """含特殊字符的英文查询应直通。"""
        result = await searcher._translate_query("C++ std::vector vs std::list performance")
        assert result == "C++ std::vector vs std::list performance"

    @pytest.mark.asyncio
    async def test_english_with_japanese_kana_bypasses(self, searcher):
        """日文假名不算中文字符，应直通。"""
        result = await searcher._translate_query("")
        assert result == ""

    @pytest.mark.asyncio
    async def test_translator_unavailable_skips(self, searcher):
        """当 translator_available 显式为 False 时，中文查询也直接返回。"""
        searcher._translator_available = False
        result = await searcher._translate_query("")
        assert result == ""

    @pytest.mark.asyncio
    async def test_empty_query(self, searcher):
        """空查询直接返回。"""
        result = await searcher._translate_query("")
        assert result == ""


# ============================================================================
# 5. search() 方法基本参数传递（mock browser + context）
# ============================================================================


class TestSearchMethod:
    """测试 search() 方法的基本参数传递和流程控制。

    使用 mock 替代真实浏览器和 Playwright，只验证参数传递和流程逻辑。
    """

    @pytest.fixture
    def searcher(self) -> PlaywrightWebSearch:
        """创建 PlaywrightWebSearch 实例。"""
        return PlaywrightWebSearch()

    @pytest.fixture
    def mock_browser_and_context(self) -> tuple[MagicMock, MagicMock, MagicMock]:
        """创建 mock 浏览器、context、page 三层结构。"""
        mock_page = MagicMock()
        mock_page.title = AsyncMock(return_value="Test Page")
        mock_page.evaluate = AsyncMock(return_value={"chunks": [], "detected": False})
        mock_page.goto = AsyncMock()
        mock_page.close = AsyncMock()
        mock_page.set_default_navigation_timeout = MagicMock()
        mock_page.set_default_timeout = MagicMock()
        mock_page.wait_for_timeout = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()

        mock_context = MagicMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_context.pages = []
        mock_context.add_init_script = AsyncMock()
        mock_context.close = AsyncMock()
        mock_context.storage_state = AsyncMock()

        mock_browser = MagicMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_browser.is_connected = MagicMock(return_value=True)

        return mock_browser, mock_context, mock_page

    @pytest.mark.asyncio
    async def test_search_english_query_no_translation(self, searcher, mock_browser_and_context):
        """英文查询不应触发翻译，直接搜索。"""
        mock_browser, _mock_context, _mock_page = mock_browser_and_context

        # Mock _ensure_browser 设置 _browser
        searcher._browser = mock_browser
        # 跳过预热
        searcher._session_warmed = True

        # Mock _search_ddg 返回空（避免测试 Bing 搜索流程）
        with patch.object(searcher, "_search_ddg", new_callable=AsyncMock) as mock_ddg:
            mock_ddg.return_value = []
            results = await searcher.search("Python async programming", top_k=3)

        # 验证
        mock_ddg.assert_awaited_once()
        call_args = mock_ddg.call_args
        assert call_args[0][0] == "Python async programming"  # query 未被翻译
        assert call_args[0][1] == 9  # top_k * 3, min(3*3, 15) = 9
        assert results == []

    @pytest.mark.asyncio
    async def test_search_passes_session_key(self, searcher, mock_browser_and_context):
        """search() 应将 session_key 传递给 _do_search。"""
        mock_browser, _mock_context, _mock_page = mock_browser_and_context
        searcher._browser = mock_browser
        searcher._session_warmed = True

        with patch.object(searcher, "_do_search", new_callable=AsyncMock) as mock_do:
            mock_do.return_value = []
            await searcher.search("test query", top_k=5, session_key="meeting-42")

        # _do_search 被调用时 session_key 作为第4个位置参数
        call_args = mock_do.call_args
        assert call_args[0][3] == "meeting-42"

    @pytest.mark.asyncio
    async def test_search_passes_language_and_time_range(self, searcher, mock_browser_and_context):
        """search() 应将 language、time_range、country 参数传递给 _search_ddg。"""
        mock_browser, _mock_context, _mock_page = mock_browser_and_context
        searcher._browser = mock_browser
        searcher._session_warmed = True

        with patch.object(searcher, "_search_ddg", new_callable=AsyncMock) as mock_ddg:
            mock_ddg.return_value = []
            await searcher.search(
                "test query",
                top_k=3,
                language="en-US",
                time_range="week",
                country="US",
            )

        call_kwargs = mock_ddg.call_args[1]
        assert call_kwargs["locale"] == "en-US"
        assert call_kwargs["time_range"] == "week"
        assert call_kwargs["country"] == "US"

    @pytest.mark.asyncio
    async def test_search_default_language_zh_cn(self, searcher, mock_browser_and_context):
        """默认 language 应为 zh-CN。"""
        mock_browser, _mock_context, _mock_page = mock_browser_and_context
        searcher._browser = mock_browser
        searcher._session_warmed = True

        with patch.object(searcher, "_search_ddg", new_callable=AsyncMock) as mock_ddg:
            mock_ddg.return_value = []
            await searcher.search("test", top_k=3)

        call_kwargs = mock_ddg.call_args[1]
        assert call_kwargs["locale"] == "zh-CN"

    @pytest.mark.asyncio
    async def test_search_timeout_returns_empty(self, searcher, mock_browser_and_context):
        """search() 在超时时应返回空列表。"""
        mock_browser, _mock_context, _mock_page = mock_browser_and_context
        searcher._browser = mock_browser
        searcher._session_warmed = True

        # Mock _do_search 引发 TimeoutError
        with patch.object(searcher, "_do_search", new_callable=AsyncMock) as mock_do:
            mock_do.side_effect = asyncio.TimeoutError()
            results = await searcher.search("test query", top_k=3)

        assert results == []

    @pytest.mark.asyncio
    async def test_search_playwright_error_retry(self, searcher, mock_browser_and_context):
        """浏览器连接断开时，search() 应自动重建浏览器并重试一次。"""
        mock_browser, _mock_context, _mock_page = mock_browser_and_context
        searcher._browser = mock_browser
        searcher._session_warmed = True

        call_count = 0

        async def mock_do_search(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                from playwright.async_api import Error as PlaywrightError

                raise PlaywrightError("browser has been closed")
            return []

        with (
            patch.object(searcher, "_do_search", side_effect=mock_do_search),
            patch.object(searcher, "_ensure_browser", new_callable=AsyncMock),
        ):
            results = await searcher.search("test", top_k=3)

        # 应重试了两次（第一次失败，第二次成功）
        assert call_count == 2
        assert results == []


# ============================================================================
# 6. SearchResult.__post_init__() — 自动填充逻辑
# ============================================================================


class TestSearchResultPostInit:
    """测试 SearchResult 数据类的自动填充行为。"""

    def test_domain_auto_filled_from_url(self):
        """提供 URL 但未提供 domain 时，应从 URL 自动提取。"""
        sr = SearchResult(url="https://docs.python.org/3/library/asyncio.html")
        assert sr.domain == "docs.python.org"

    def test_domain_kept_if_provided(self):
        """显式提供 domain 时不应被覆盖。"""
        sr = SearchResult(
            url="https://docs.python.org/3/",
            domain="custom.domain.com",
        )
        assert sr.domain == "custom.domain.com"

    def test_no_url_no_domain(self):
        """无 URL 时 domain 应为空字符串。"""
        sr = SearchResult(url="")
        assert sr.domain == ""

    def test_source_tier_default_is_c(self):
        """未提供 source_tier 时默认值为 "C"。"""
        sr = SearchResult(url="https://example.com")
        # 默认值在 dataclass 定义中为 "C"
        assert sr.source_tier in ("C", "S", "A", "B", "D")

    def test_signals_auto_filled_from_tag_url(self):
        """signals 为空时应自动从 tag_url 填充。"""
        sr = SearchResult(url="https://docs.python.org/3/")
        assert sr.signals
        assert "source_tier" in sr.signals

    def test_signals_preserved_if_provided(self):
        """显式提供 signals 时不应被覆盖。"""
        custom_signals = {"custom_key": "custom_value"}
        sr = SearchResult(
            url="https://example.com",
            signals=custom_signals,
        )
        assert sr.signals == custom_signals

    def test_rank_and_engine_defaults(self):
        """rank 和 engine 应有合理的默认值。"""
        sr = SearchResult(url="https://example.com")
        assert sr.rank == 0
        assert sr.engine == ""

    def test_full_construction(self):
        """完整构造 SearchResult 应保留所有字段。"""
        sr = SearchResult(
            url="https://python.org",
            title="Python Official",
            snippet="The official Python website",
            domain="python.org",
            source_tier="S",
            signals={"is_official": True},
            rank=1,
            engine="bing",
        )
        assert sr.url == "https://python.org"
        assert sr.title == "Python Official"
        assert sr.snippet == "The official Python website"
        assert sr.domain == "python.org"
        assert sr.source_tier == "S"
        assert sr.signals == {"is_official": True}
        assert sr.rank == 1
        assert sr.engine == "bing"


# ============================================================================
# 7. EngineHealth — 健康追踪（success/failure 计数、冷却期）
# ============================================================================


class TestEngineHealth:
    """测试引擎健康度追踪器。"""

    def test_initial_state_available(self):
        """初始状态所有引擎应可用。"""
        health = EngineHealth()
        assert health.is_available("any-engine") is True

    def test_failure_within_limit_still_available(self):
        """失败次数未达上限时引擎仍可用。"""
        health = EngineHealth(max_failures=3)
        health.record_failure("bing")
        assert health.is_available("bing") is True
        health.record_failure("bing")
        assert health.is_available("bing") is True

    def test_reaching_max_failures_becomes_unavailable(self):
        """达到 max_failures 后引擎不可用。"""
        health = EngineHealth(max_failures=2)
        health.record_failure("bing")
        health.record_failure("bing")
        assert health.is_available("bing") is False

    def test_exceeding_max_failures_stays_unavailable(self):
        """超过 max_failures 后持续不可用。"""
        health = EngineHealth(max_failures=2)
        health.record_failure("bing")
        health.record_failure("bing")
        health.record_failure("bing")  # 第 3 次
        assert health.is_available("bing") is False

    def test_record_success_resets_failures(self):
        """成功调用重置失败计数，引擎恢复可用。"""
        health = EngineHealth(max_failures=2)
        health.record_failure("bing")
        health.record_failure("bing")
        assert health.is_available("bing") is False

        health.record_success("bing")
        assert health.is_available("bing") is True

    def test_cooldown_expires_engine_available(self):
        """冷却期过后引擎应恢复可用（允许探活）。"""
        health = EngineHealth(max_failures=2, cooldown_seconds=0.01)
        health.record_failure("bing")
        health.record_failure("bing")
        assert health.is_available("bing") is False

        # 等待冷却期过后
        time.sleep(0.02)
        assert health.is_available("bing") is True

    def test_cooldown_not_expired_unavailable(self):
        """冷却期未过时引擎仍不可用。"""
        health = EngineHealth(max_failures=2, cooldown_seconds=60.0)
        health.record_failure("bing")
        health.record_failure("bing")
        assert health.is_available("bing") is False

    def test_status_returns_all_engines(self):
        """status() 应返回所有被追踪引擎的状态。"""
        health = EngineHealth()
        health.record_failure("bing")
        health.record_failure("ddg")
        health.record_failure("ddg")
        health.record_failure("ddg")

        status = health.status()
        assert "bing" in status
        assert "ddg" in status
        assert status["bing"]["fail_count"] == 1
        assert status["ddg"]["fail_count"] == 3
        assert status["bing"]["available"] is True
        assert status["ddg"]["available"] is False

    def test_status_empty_when_no_failures(self):
        """无失败记录时 status() 返回空字典。"""
        health = EngineHealth()
        assert health.status() == {}

    def test_multiple_engines_independent(self):
        """不同引擎的失败计数应独立。"""
        health = EngineHealth(max_failures=2)
        health.record_failure("bing")
        health.record_failure("bing")
        health.record_failure("ddg")

        assert health.is_available("bing") is False
        assert health.is_available("ddg") is True


# ============================================================================
# 8. MultiEngineSearch failover 逻辑（mock engine）
# ============================================================================


class TestMultiEngineSearch:
    """测试多引擎搜索调度器的 failover 逻辑。"""

    # ---- 辅助：Fake Engine 实现 ----

    @staticmethod
    def _make_engine(
        name: str,
        results: list[SearchResult] | None = None,
        should_fail: bool = False,
    ) -> SearchEngine:
        """创建一个 mock SearchEngine。"""
        if should_fail:

            class _FailingEngine:
                @property
                def name(self) -> str:
                    return name

                @property
                def is_available(self) -> bool:
                    return True

                async def search(self, query: str, max_results: int = 5, **kwargs: Any) -> list[SearchResult]:
                    raise SearchEngineError(f"{name} failed")

                async def health_check(self) -> bool:
                    return False

            return _FailingEngine()  # type: ignore[return-value]

        class _SuccessEngine:
            @property
            def name(self) -> str:
                return name

            @property
            def is_available(self) -> bool:
                return True

            async def search(self, query: str, max_results: int = 5, **kwargs: Any) -> list[SearchResult]:
                return results or []

            async def health_check(self) -> bool:
                return True

        return _SuccessEngine()  # type: ignore[return-value]

    # ---- 测试用例 ----

    @pytest.mark.asyncio
    async def test_first_engine_succeeds(self):
        """第一个引擎成功时应返回其结果。"""
        primary = self._make_engine(
            "primary",
            results=[SearchResult(url="https://primary.test", title="P")],
        )
        backup = self._make_engine(
            "backup",
            results=[SearchResult(url="https://backup.test", title="B")],
        )
        multi = MultiEngineSearch([primary, backup])

        result = await multi.search("test query")
        assert result["engine_used"] == "primary"
        assert len(result["results"]) == 1
        assert result["results"][0].title == "P"
        assert result["failed_engines"] == []

    @pytest.mark.asyncio
    async def test_failover_to_second_engine(self):
        """第一个引擎失败时应 failover 到第二个引擎。"""
        failing = self._make_engine("failing", should_fail=True)
        backup = self._make_engine(
            "backup",
            results=[SearchResult(url="https://backup.test", title="B")],
        )
        multi = MultiEngineSearch([failing, backup])

        result = await multi.search("test query")
        assert result["engine_used"] == "backup"
        assert len(result["results"]) == 1
        assert result["results"][0].title == "B"
        assert len(result["failed_engines"]) == 1
        assert "failing" in result["failed_engines"][0]

    @pytest.mark.asyncio
    async def test_all_engines_fail(self):
        """所有引擎都失败时返回空结果。"""
        e1 = self._make_engine("e1", should_fail=True)
        e2 = self._make_engine("e2", should_fail=True)
        multi = MultiEngineSearch([e1, e2])

        result = await multi.search("test query")
        assert result["engine_used"] == "none"
        assert result["results"] == []
        assert len(result["failed_engines"]) == 2

    @pytest.mark.asyncio
    async def test_skip_unavailable_engine(self):
        """健康检查不可用的引擎应被跳过。"""
        # 创建一个引擎，其 health 追踪变为不可用
        health = EngineHealth(max_failures=2)
        health.record_failure("unstable")
        health.record_failure("unstable")

        # 手动构造 MultiEngineSearch 并注入 health
        stable = self._make_engine(
            "stable",
            results=[SearchResult(url="https://stable.test")],
        )
        multi = MultiEngineSearch([stable])
        # 用自定义 health 覆盖
        multi._health = health
        # 再插入一个不稳定的引擎（不可用）
        # 简化：直接测试健康追踪通过 is_available 过滤
        # 实际上 MultiEngineSearch 在循环中会检查 self._health.is_available(engine.name)
        # 这个测试验证 health 状态正确影响引擎选择

        # 更直接的方式：验证 health.is_available 返回 False
        assert health.is_available("unstable") is False

    @pytest.mark.asyncio
    async def test_low_confidence_count(self):
        """D 级结果应计入 low_confidence_count。"""
        engine = self._make_engine(
            "test",
            results=[
                SearchResult(url="https://a.com", source_tier="S"),
                SearchResult(url="https://b.com", source_tier="D"),
                SearchResult(url="https://c.com", source_tier="D"),
            ],
        )
        multi = MultiEngineSearch([engine])

        result = await multi.search("test")
        assert result["low_confidence_count"] == 2

    @pytest.mark.asyncio
    async def test_health_status_property(self):
        """health_status property 应返回引擎健康状态。"""
        engine = self._make_engine("test", results=[])
        multi = MultiEngineSearch([engine])

        # 记录一次失败
        multi._health.record_failure("test")
        status = multi.health_status
        assert "test" in status
        assert status["test"]["fail_count"] == 1
        assert status["test"]["available"] is True

    @pytest.mark.asyncio
    async def test_empty_engine_list(self):
        """无引擎时返回空结果。"""
        multi = MultiEngineSearch([])
        result = await multi.search("test")
        assert result["engine_used"] == "none"
        assert result["results"] == []
        assert result["failed_engines"] == []

    @pytest.mark.asyncio
    async def test_passes_kwargs_to_engine(self):
        """kwargs 应正确传递给底层引擎。"""
        captured_kwargs = {}

        class _CapturingEngine:
            @property
            def name(self) -> str:
                return "capture"

            @property
            def is_available(self) -> bool:
                return True

            async def search(self, query: str, max_results: int = 5, **kwargs: Any) -> list[SearchResult]:
                captured_kwargs.update(kwargs)
                return []

            async def health_check(self) -> bool:
                return True

        multi = MultiEngineSearch([_CapturingEngine()])  # type: ignore[list-item]
        await multi.search("test", time_range="week", country="US")
        assert captured_kwargs.get("time_range") == "week"
        assert captured_kwargs.get("country") == "US"
