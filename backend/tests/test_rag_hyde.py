"""M1.3: RAG 检索策略增强 - HyDE 测试

验证：
- _clean_hypothetical_doc 正确清理 markdown 标记和前缀
- generate_hypothetical_document 在 LLM 不可用时返回空字符串
- hyde_retrieve 集成 store.search（假设文档作为查询）
- retrieve_for_conflict 正确合并 HyDE 和 Multi-Query 结果
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.rag.hyde import (
    _clean_hypothetical_doc,
    generate_hypothetical_document,
    hyde_retrieve,
)
from app.rag.retriever import _build_chunk_dict, retrieve_for_conflict

# ── _clean_hypothetical_doc 测试 ────────────────────────────


class TestCleanHypotheticalDoc:
    """测试假设文档清理函数"""

    def test_strips_markdown_headers(self):
        """去掉 markdown 标题标记。"""
        text = "## 技术方案\n系统应支持异步处理。"
        cleaned = _clean_hypothetical_doc(text)
        assert not cleaned.startswith("#")
        assert "技术方案" in cleaned

    def test_strips_code_blocks(self):
        """去掉 markdown 代码块。"""
        text = "```python\nasync def foo():\n    pass\n```\n这是文档。"
        cleaned = _clean_hypothetical_doc(text)
        assert "```" not in cleaned
        assert "这是文档" in cleaned

    def test_strips_answer_prefix(self):
        """去掉 "答：" 前缀。"""
        text = "答：系统应支持异步处理。"
        cleaned = _clean_hypothetical_doc(text)
        assert not cleaned.startswith("答")
        assert "系统应支持异步处理" in cleaned

    def test_strips_doc_prefix(self):
        """去掉 "假设文档：" 前缀。"""
        text = "假设文档：这是一段技术描述。"
        cleaned = _clean_hypothetical_doc(text)
        assert not cleaned.startswith("假设文档")
        assert "技术描述" in cleaned

    def test_compresses_extra_newlines(self):
        """压缩多余空行。"""
        text = "段落一\n\n\n\n\n段落二"
        cleaned = _clean_hypothetical_doc(text)
        assert "\n\n\n" not in cleaned

    def test_empty_string(self):
        """空字符串返回空字符串。"""
        assert _clean_hypothetical_doc("") == ""

    def test_plain_text_unchanged(self):
        """纯文本不被修改。"""
        text = "系统应支持异步任务处理以解耦耗时操作。"
        cleaned = _clean_hypothetical_doc(text)
        assert cleaned == text


# ── generate_hypothetical_document 测试 ───────────────────


class TestGenerateHypotheticalDocument:
    """测试 HyDE 假设文档生成"""

    @pytest.mark.asyncio
    async def test_llm_not_configured_returns_empty(self):
        """LLM 未配置时返回空字符串。"""
        with patch("app.config.settings") as mock_settings:
            mock_settings.llm_base_url = ""
            mock_settings.llm_api_key = ""
            mock_settings.llm_model = "test"
            result = await generate_hypothetical_document("测试查询")
            assert result == ""

    @pytest.mark.asyncio
    async def test_llm_success(self):
        """LLM 正常返回时生成假设文档。"""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "系统应支持异步任务队列，使用 Redis 作为消息中间件。"}}]
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.config.settings") as mock_settings,
            patch("app.tenants.context.get_tenant_id", return_value="test-tenant"),
            patch("app.tenants.settings_override.resolve_llm_config", return_value=("http://api", "key", "model")),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            mock_settings.llm_base_url = "http://api"
            mock_settings.llm_api_key = "key"
            mock_settings.llm_model = "model"
            result = await generate_hypothetical_document("如何实现异步任务？")
            assert result != ""
            assert "异步任务" in result

    @pytest.mark.asyncio
    async def test_llm_failure_returns_empty(self):
        """LLM 调用失败时返回空字符串。"""
        with (
            patch("app.config.settings") as mock_settings,
            patch("app.tenants.context.get_tenant_id", return_value="test-tenant"),
            patch("app.tenants.settings_override.resolve_llm_config", return_value=("http://api", "key", "model")),
            patch("httpx.AsyncClient", side_effect=Exception("网络不可达")),
        ):
            mock_settings.llm_base_url = "http://api"
            mock_settings.llm_api_key = "key"
            mock_settings.llm_model = "model"
            result = await generate_hypothetical_document("测试")
            assert result == ""


# ── hyde_retrieve 测试 ─────────────────────────────────────


class TestHyDERetrieve:
    """测试 HyDE 检索流程"""

    @pytest.mark.asyncio
    async def test_hyde_retrieve_with_results(self):
        """HyDE 生成文档并检索到结果。"""
        mock_chunk = MagicMock()
        mock_chunk.chunk_id = "chunk-1"
        mock_store = AsyncMock()
        mock_store.search = AsyncMock(return_value=[(mock_chunk, 0.85)])

        with patch("app.rag.hyde.generate_hypothetical_document", return_value="假设文档内容"):
            results = await hyde_retrieve(mock_store, "测试查询", top_k=5)
            assert len(results) == 1
            assert results[0][0] == mock_chunk
            assert results[0][1] == 0.85

    @pytest.mark.asyncio
    async def test_hyde_retrieve_empty_doc(self):
        """假设文档为空时返回空列表。"""
        mock_store = AsyncMock()
        with patch("app.rag.hyde.generate_hypothetical_document", return_value=""):
            results = await hyde_retrieve(mock_store, "测试查询", top_k=5)
            assert results == []
            mock_store.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_hyde_retrieve_store_failure(self):
        """store.search 失败时返回空列表。"""
        mock_store = AsyncMock()
        mock_store.search = AsyncMock(side_effect=Exception("存储不可用"))
        with patch("app.rag.hyde.generate_hypothetical_document", return_value="假设文档"):
            results = await hyde_retrieve(mock_store, "测试", top_k=5)
            assert results == []


# ── _build_chunk_dict 测试 ─────────────────────────────────


class TestBuildChunkDict:
    """测试 chunk 字典构建辅助函数"""

    def test_build_chunk_dict_basic(self):
        """基本字段正确构建。"""
        mock_chunk = MagicMock()
        mock_chunk.to_dict.return_value = {"chunk_id": "c1", "text": "内容", "doc_id": "d1"}
        mock_chunk.summary.return_value = "摘要..."
        mock_chunk.text = "完整内容" * 50
        mock_chunk.chunk_id = "c1"

        mock_store = MagicMock()
        mock_store.get_neighbor_context.return_value = "邻居内容"

        d = _build_chunk_dict(mock_chunk, 0.92, mock_store)
        assert d["chunk_id"] == "c1"
        assert d["score"] == 0.92
        assert d["summary"] == "摘要..."
        assert d["full_length"] == 200  # "完整内容" * 50 = 200 chars
        assert d["expandable"] is True
        assert "neighbor_context" in d

    def test_build_chunk_dict_no_neighbor(self):
        """邻居上下文不比 chunk 长时不附加。"""
        mock_chunk = MagicMock()
        mock_chunk.to_dict.return_value = {"chunk_id": "c1", "text": "内容"}
        mock_chunk.summary.return_value = "内容..."
        mock_chunk.text = "短内容"
        mock_chunk.chunk_id = "c1"

        mock_store = MagicMock()
        mock_store.get_neighbor_context.return_value = "短"  # 比 chunk.text 短

        d = _build_chunk_dict(mock_chunk, 0.5, mock_store)
        assert "neighbor_context" not in d


# ── retrieve_for_conflict HyDE 集成测试 ────────────────────


class TestRetrieveForConflictHyDE:
    """测试 retrieve_for_conflict 正确集成 HyDE"""

    @pytest.mark.asyncio
    async def test_hyde_results_merged_with_multiquery(self):
        """HyDE 检索结果与 Multi-Query 结果合并去重。"""
        # Mock store
        mock_chunk_a = MagicMock()
        mock_chunk_a.chunk_id = "chunk-a"
        mock_chunk_a.to_dict.return_value = {"chunk_id": "chunk-a", "text": "文档A", "doc_id": "d1"}
        mock_chunk_a.summary.return_value = "文档A摘要"
        mock_chunk_a.text = "文档A内容"

        mock_chunk_b = MagicMock()
        mock_chunk_b.chunk_id = "chunk-b"
        mock_chunk_b.to_dict.return_value = {"chunk_id": "chunk-b", "text": "文档B", "doc_id": "d2"}
        mock_chunk_b.summary.return_value = "文档B摘要"
        mock_chunk_b.text = "文档B内容"

        mock_store = MagicMock()
        mock_store.all_chunks.return_value = [mock_chunk_a, mock_chunk_b]
        mock_store.get_neighbor_context.return_value = ""

        # Multi-query 返回 chunk-a，HyDE 返回 chunk-b
        mock_store.search = AsyncMock(
            side_effect=[
                [(mock_chunk_a, 0.8)],  # query 1
                [(mock_chunk_a, 0.7)],  # query 2 (dup, lower score)
                [(mock_chunk_b, 0.9)],  # query 3
            ]
        )

        # Mock reranker
        mock_reranker = AsyncMock()
        mock_reranker.rerank = AsyncMock(return_value=[(0, 0.95), (1, 0.80)])

        with (
            patch("app.rag.retriever.get_store", return_value=mock_store),
            patch("app.rag.retriever.get_reranker", return_value=mock_reranker),
            patch("app.rag.retriever.rewrite_query", return_value=["q1", "q2", "q3"]),
            patch("app.rag.retriever.hyde_retrieve", return_value=[(mock_chunk_b, 0.85)]),
        ):
            results = await retrieve_for_conflict("meeting-1", "冲突描述", top_k=5)

        # 应有结果返回（chunk-a 和 chunk-b 合并后重排）
        assert len(results) >= 1
        # reranker 被调用
        mock_reranker.rerank.assert_called_once()

    @pytest.mark.asyncio
    async def test_hyde_failure_does_not_break_retrieval(self):
        """HyDE 失败时 Multi-Query 仍正常工作。"""
        mock_chunk = MagicMock()
        mock_chunk.chunk_id = "chunk-1"
        mock_chunk.to_dict.return_value = {"chunk_id": "chunk-1", "text": "内容", "doc_id": "d1"}
        mock_chunk.summary.return_value = "摘要"
        mock_chunk.text = "内容"

        mock_store = MagicMock()
        mock_store.all_chunks.return_value = [mock_chunk]
        mock_store.get_neighbor_context.return_value = ""
        mock_store.search = AsyncMock(return_value=[(mock_chunk, 0.8)])

        mock_reranker = AsyncMock()
        mock_reranker.rerank = AsyncMock(return_value=[(0, 0.9)])

        with (
            patch("app.rag.retriever.get_store", return_value=mock_store),
            patch("app.rag.retriever.get_reranker", return_value=mock_reranker),
            patch("app.rag.retriever.rewrite_query", return_value=["原始查询"]),
            # HyDE 返回空列表（模拟 LLM 不可用）
            patch("app.rag.retriever.hyde_retrieve", return_value=[]),
        ):
            results = await retrieve_for_conflict("meeting-1", "冲突", top_k=5)

        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_empty_store_returns_empty(self):
        """空向量库返回空列表。"""
        mock_store = MagicMock()
        mock_store.all_chunks.return_value = []

        with patch("app.rag.retriever.get_store", return_value=mock_store):
            results = await retrieve_for_conflict("meeting-1", "冲突", top_k=5)
            assert results == []

    @pytest.mark.asyncio
    async def test_hyde_and_multiquery_dedup(self):
        """HyDE 和 Multi-Query 检索到同一 chunk 时去重，保留最高分。"""
        mock_chunk = MagicMock()
        mock_chunk.chunk_id = "chunk-dup"
        mock_chunk.to_dict.return_value = {"chunk_id": "chunk-dup", "text": "内容", "doc_id": "d1"}
        mock_chunk.summary.return_value = "摘要"
        mock_chunk.text = "内容"

        mock_store = MagicMock()
        mock_store.all_chunks.return_value = [mock_chunk]
        mock_store.get_neighbor_context.return_value = ""
        # Multi-Query 检索到该 chunk，分数 0.7
        mock_store.search = AsyncMock(return_value=[(mock_chunk, 0.7)])

        mock_reranker = AsyncMock()
        mock_reranker.rerank = AsyncMock(return_value=[(0, 0.9)])

        with (
            patch("app.rag.retriever.get_store", return_value=mock_store),
            patch("app.rag.retriever.get_reranker", return_value=mock_reranker),
            patch("app.rag.retriever.rewrite_query", return_value=["原始查询"]),
            # HyDE 也检索到同一 chunk，但分数更高 0.9
            patch("app.rag.retriever.hyde_retrieve", return_value=[(mock_chunk, 0.9)]),
        ):
            results = await retrieve_for_conflict("meeting-1", "冲突", top_k=5)

        # 只有一个结果（去重后）
        assert len(results) == 1
        # 应保留 HyDE 的更高分
        assert results[0]["score"] == 0.9
