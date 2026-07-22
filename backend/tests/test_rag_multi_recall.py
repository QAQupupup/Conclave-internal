"""多路召回回归测试

验证：
1. 多路召回并发执行（asyncio.gather，不是串行）
2. 单路召回异常隔离（一路失败不影响其他路）
3. 所有异常/回退都有日志输出
4. _extract_json 多种格式兼容
5. query_rewriter 异常分类处理（超时/HTTP/解析/未知）
6. reranker 异常的最终防线回退

这些测试用于后续版本回归验证，确保审计日志和异常处理不被退化。
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.rag.query_rewriter import _extract_json, rewrite_query
from app.rag.retriever import _safe_search, retrieve_for_conflict
from app.rag.store import Chunk

# ── 测试 fixtures ──────────────────────────────────────────


def _make_chunk(chunk_id: str, text: str) -> Chunk:
    """构造测试用 chunk"""
    return Chunk(
        chunk_id=chunk_id,
        doc_id="doc1",
        section="test",
        text=text,
        char_start=0,
        char_end=len(text),
        source="test",
        prev_id="",
        next_id="",
    )


def _make_store(chunks: list[Chunk]) -> MagicMock:
    """构造 mock store，all_chunks 返回指定 chunks"""
    store = MagicMock()
    store.all_chunks.return_value = chunks
    store.get_neighbor_context.return_value = ""
    return store


# ── 1. _safe_search 异常隔离测试 ──────────────────────────


class TestSafeSearchExceptionIsolation:
    """验证单路召回异常不阻塞其他路"""

    @pytest.mark.asyncio
    async def test_normal_search_returns_results(self):
        """正常搜索返回结果"""
        store = MagicMock()
        chunk = _make_chunk("c1", "测试文本")
        store.search = AsyncMock(return_value=[(chunk, 0.9)])

        results = await _safe_search(store, "query", 10, "route_0")

        assert len(results) == 1
        assert results[0][0].chunk_id == "c1"

    @pytest.mark.asyncio
    async def test_exception_returns_empty_list(self):
        """store.search 抛异常时返回空列表，不传播异常"""
        store = MagicMock()
        store.search = AsyncMock(side_effect=RuntimeError("Qdrant connection refused"))

        results = await _safe_search(store, "query", 10, "route_0")

        assert results == []

    @pytest.mark.asyncio
    async def test_exception_logs_warning(self, caplog):
        """异常时打 warning 日志，包含路由名和错误信息"""
        store = MagicMock()
        store.search = AsyncMock(side_effect=RuntimeError("connection refused"))

        with caplog.at_level(logging.WARNING, logger="app.rag.retriever"):
            await _safe_search(store, "query", 10, "multi_query_1")

        assert any("multi_query_1" in record.message and "RuntimeError" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_one_route_failure_does_not_block_others(self):
        """验证 gather 中一路失败不影响其他路"""
        chunk_a = _make_chunk("a", "文本A")
        chunk_c = _make_chunk("c", "文本C")

        # 3 路：第 1 路正常，第 2 路异常，第 3 路正常
        store = MagicMock()
        store.search = AsyncMock(
            side_effect=[
                [(chunk_a, 0.9)],  # route 0
                RuntimeError("timeout"),  # route 1
                [(chunk_c, 0.8)],  # route 2
            ]
        )
        store.get_neighbor_context.return_value = ""

        tasks = [_safe_search(store, f"q{i}", 10, f"route_{i}") for i in range(3)]
        results = await asyncio.gather(*tasks)

        assert len(results[0]) == 1  # route 0 正常
        assert results[1] == []  # route 1 异常→空
        assert len(results[2]) == 1  # route 2 正常


# ── 2. retrieve_for_conflict 并发 + 日志测试 ────────────────


class TestRetrieveForConflictConcurrency:
    """验证多路召回并发执行和全链路日志"""

    @pytest.mark.asyncio
    async def test_concurrent_search_not_sequential(self):
        """验证多路搜索是并发的（通过时间戳检测）"""
        chunk = _make_chunk("c1", "测试")
        store = _make_store([chunk])

        call_times: list[float] = []

        async def mock_search(query, top_k):
            import time

            call_times.append(time.monotonic())
            await asyncio.sleep(0.1)  # 模拟延迟
            return [(chunk, 0.9)]

        store.search = mock_search

        with (
            patch("app.rag.retriever.get_store", return_value=store),
            patch("app.rag.retriever.rewrite_query", return_value=["q1", "q2", "q3"]),
            patch("app.rag.retriever.hyde_retrieve", return_value=[]),
            patch("app.rag.retriever.get_reranker") as mock_reranker_cls,
        ):
            mock_reranker = AsyncMock()
            mock_reranker.rerank = AsyncMock(return_value=[(0, 0.95)])
            mock_reranker_cls.return_value = mock_reranker

            await retrieve_for_conflict("meeting1", "conflict", top_k=3)

        # 如果是并发，3 路的调用时间应该非常接近（差值 < 0.05s）
        # 如果是串行，相邻调用差值应 >= 0.1s
        assert len(call_times) == 3
        max_gap = max(call_times[i + 1] - call_times[i] for i in range(len(call_times) - 1))
        assert max_gap < 0.05, f"多路召回不是并发执行，调用间隔 {max_gap:.3f}s"

    @pytest.mark.asyncio
    async def test_all_routes_empty_logs_warning(self, caplog):
        """所有路召回为空时打 warning 日志"""
        store = _make_store([_make_chunk("c1", "测试")])

        with (
            patch("app.rag.retriever.get_store", return_value=store),
            patch("app.rag.retriever.rewrite_query", return_value=["q1"]),
            patch("app.rag.retriever.hyde_retrieve", return_value=[]),
            patch("app.rag.retriever._safe_search", return_value=[]),
            caplog.at_level(logging.WARNING, logger="app.rag.retriever"),
        ):
            result = await retrieve_for_conflict("m1", "conflict", top_k=3)

        assert result == []
        assert any("所有路召回均为空" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_reranker_exception_fallback_to_base_sort(self, caplog):
        """Reranker 异常时回退到初始分数排序"""
        chunk = _make_chunk("c1", "测试文本")
        store = _make_store([chunk])

        with (
            patch("app.rag.retriever.get_store", return_value=store),
            patch("app.rag.retriever.rewrite_query", return_value=["q1"]),
            patch("app.rag.retriever.hyde_retrieve", return_value=[]),
            patch("app.rag.retriever._safe_search", return_value=[(chunk, 0.9)]),
            patch("app.rag.retriever.get_reranker") as mock_reranker_cls,
        ):
            mock_reranker = AsyncMock()
            mock_reranker.rerank = AsyncMock(side_effect=RuntimeError("API down"))
            mock_reranker_cls.return_value = mock_reranker

            with caplog.at_level(logging.ERROR, logger="app.rag.retriever"):
                result = await retrieve_for_conflict("m1", "conflict", top_k=3)

        # 回退到 base 排序，返回 1 条
        assert len(result) == 1
        assert any("Reranker 重排异常" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_info_logs_for_audit_trail(self, caplog):
        """验证关键步骤都有 info 日志（审计追踪）"""
        chunk = _make_chunk("c1", "测试文本")
        store = _make_store([chunk])

        with (
            patch("app.rag.retriever.get_store", return_value=store),
            patch("app.rag.retriever.rewrite_query", return_value=["q1", "q2"]),
            patch("app.rag.retriever.hyde_retrieve", return_value=[]),
            patch("app.rag.retriever._safe_search", return_value=[(chunk, 0.9)]),
            patch("app.rag.retriever.get_reranker") as mock_reranker_cls,
        ):
            mock_reranker = AsyncMock()
            mock_reranker.rerank = AsyncMock(return_value=[(0, 0.95)])
            mock_reranker_cls.return_value = mock_reranker

            with caplog.at_level(logging.INFO, logger="app.rag.retriever"):
                await retrieve_for_conflict("m1", "conflict", top_k=3)

        messages = [r.message for r in caplog.records]
        assert any("retrieve_for_conflict 开始" in m for m in messages)
        assert any("查询改写完成" in m for m in messages)
        assert any("多路召回合并去重" in m for m in messages)
        assert any("Reranker 重排完成" in m for m in messages)
        assert any("retrieve_for_conflict 完成" in m for m in messages)


# ── 3. _extract_json 健壮性测试 ────────────────────────────


class TestExtractJsonRobustness:
    """验证 _extract_json 对各种 LLM 输出格式的兼容性"""

    def test_pure_json(self):
        """纯 JSON 直接解析"""
        result = _extract_json('{"queries": ["q1", "q2"]}')
        assert result == {"queries": ["q1", "q2"]}

    def test_markdown_code_block(self):
        """markdown 代码块包裹"""
        result = _extract_json('```json\n{"queries": ["q1"]}\n```')
        assert result == {"queries": ["q1"]}

    def test_text_before_json(self):
        """JSON 前有解释性文本"""
        result = _extract_json('好的，结果如下：\n{"queries": ["q1", "q2"]}')
        assert result == {"queries": ["q1", "q2"]}

    def test_text_after_json(self):
        """JSON 后有解释性文本"""
        result = _extract_json('{"queries": ["q1"]}\n以上是改写结果。')
        assert result == {"queries": ["q1"]}

    def test_multiline_json(self):
        """多行 JSON"""
        result = _extract_json('{\n  "queries": [\n    "q1",\n    "q2"\n  ]\n}')
        assert result == {"queries": ["q1", "q2"]}

    def test_trailing_comma_in_object(self):
        """对象内尾随逗号"""
        result = _extract_json('{"queries": ["q1", "q2"],}')
        assert result == {"queries": ["q1", "q2"]}

    def test_trailing_comma_in_array(self):
        """数组内尾随逗号"""
        result = _extract_json('{"queries": ["q1", "q2",],}')
        assert result == {"queries": ["q1", "q2"]}

    def test_empty_string(self):
        """空字符串"""
        assert _extract_json("") is None

    def test_none_input(self):
        """None 输入"""
        assert _extract_json(None) is None

    def test_no_json_found(self):
        """无 JSON 内容"""
        assert _extract_json("这是一段纯文本，没有 JSON") is None

    def test_json_array(self):
        """JSON 数组"""
        result = _extract_json('["q1", "q2"]')
        assert result == ["q1", "q2"]

    def test_json_array_with_prefix(self):
        """带前缀的 JSON 数组"""
        result = _extract_json('结果：["q1", "q2"]')
        assert result == ["q1", "q2"]


# ── 4. query_rewriter 异常分类测试 ────────────────────────


class TestQueryRewriterExceptionHandling:
    """验证 query_rewriter 对不同异常的分类处理和日志"""

    @pytest.mark.asyncio
    async def test_llm_not_configured_returns_original(self):
        """LLM 未配置时返回原始查询"""
        with (
            patch("app.tenants.context.get_tenant_id", return_value=""),
            patch("app.tenants.settings_override.resolve_llm_config", return_value=("", "", "")),
        ):
            result = await rewrite_query("原始查询")

        assert result == ["原始查询"]

    @pytest.mark.asyncio
    async def test_timeout_returns_original_with_log(self, caplog):
        """超时异常返回原始查询 + warning 日志"""
        with (
            patch("app.tenants.context.get_tenant_id", return_value=""),
            patch("app.tenants.settings_override.resolve_llm_config", return_value=("http://api", "key", "model")),
            patch("httpx.AsyncClient") as mock_client_cls,
            caplog.at_level(logging.WARNING, logger="app.rag.query_rewriter"),
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client_cls.return_value = mock_client

            result = await rewrite_query("原始查询")

        assert result == ["原始查询"]
        assert any("超时" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_http_error_returns_original_with_log(self, caplog):
        """HTTP 错误返回原始查询 + warning 日志"""
        mock_response = MagicMock()
        mock_response.status_code = 429

        with (
            patch("app.tenants.context.get_tenant_id", return_value=""),
            patch("app.tenants.settings_override.resolve_llm_config", return_value=("http://api", "key", "model")),
            patch("httpx.AsyncClient") as mock_client_cls,
            caplog.at_level(logging.WARNING, logger="app.rag.query_rewriter"),
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(
                side_effect=httpx.HTTPStatusError("rate limited", request=MagicMock(), response=mock_response)
            )
            mock_client_cls.return_value = mock_client

            result = await rewrite_query("原始查询")

        assert result == ["原始查询"]
        assert any("HTTP 错误" in r.message and "429" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_json_parse_failure_returns_original_with_log(self, caplog):
        """JSON 解析失败返回原始查询 + warning 日志"""
        with (
            patch("app.tenants.context.get_tenant_id", return_value=""),
            patch("app.tenants.settings_override.resolve_llm_config", return_value=("http://api", "key", "model")),
        ):
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"choices": [{"message": {"content": "这不是JSON"}}]}

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.post = AsyncMock(return_value=mock_resp)
                mock_client_cls.return_value = mock_client

                with caplog.at_level(logging.WARNING, logger="app.rag.query_rewriter"):
                    result = await rewrite_query("原始查询")

        assert result == ["原始查询"]
        assert any("JSON 解析失败" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_successful_rewrite_logs_info(self, caplog):
        """成功改写时打 info 日志"""
        with (
            patch("app.tenants.context.get_tenant_id", return_value=""),
            patch("app.tenants.settings_override.resolve_llm_config", return_value=("http://api", "key", "model")),
        ):
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"choices": [{"message": {"content": '{"queries": ["改写1", "改写2"]}'}}]}

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.post = AsyncMock(return_value=mock_resp)
                mock_client_cls.return_value = mock_client

                with caplog.at_level(logging.INFO, logger="app.rag.query_rewriter"):
                    result = await rewrite_query("原始查询")

        assert len(result) == 3  # 原始 + 2 改写
        assert any("查询改写成功" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_response_structure_error_returns_original_with_log(self, caplog):
        """响应结构异常（KeyError/IndexError）返回原始查询 + warning 日志"""
        with (
            patch("app.tenants.context.get_tenant_id", return_value=""),
            patch("app.tenants.settings_override.resolve_llm_config", return_value=("http://api", "key", "model")),
        ):
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            # 缺少 choices 字段
            mock_resp.json.return_value = {"error": "invalid"}

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.post = AsyncMock(return_value=mock_resp)
                mock_client_cls.return_value = mock_client

                with caplog.at_level(logging.WARNING, logger="app.rag.query_rewriter"):
                    result = await rewrite_query("原始查询")

        assert result == ["原始查询"]
        assert any("响应解析失败" in r.message for r in caplog.records)
