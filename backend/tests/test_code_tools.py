# Agent 代码工具注册与执行测试（[P1 修复] 代码检索/结构查询接入工作流）
# 验证真实函数：create_default_tool_registry / _clamp_int / _summarize_result
# 覆盖正向 + 非正向（空参/无索引降级/参数越界）+ 回归（摘要分类）维度。
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.orchestrator.react_loop import (
    _clamp_int,
    _summarize_result,
    create_default_tool_registry,
)


class TestClampInt:
    """LLM 参数收敛：类型错误/越界一律兜底，不让工具调用炸掉。"""

    def test_valid_int_passthrough(self) -> None:
        assert _clamp_int(7, 5, 1, 50) == 7

    def test_string_number_parsed(self) -> None:
        assert _clamp_int("12", 5, 1, 50) == 12

    def test_invalid_falls_back_to_default(self) -> None:
        """非正向：无法解析的值回退默认值。"""
        assert _clamp_int("abc", 5, 1, 50) == 5
        assert _clamp_int(None, 5, 1, 50) == 5

    def test_out_of_range_clamped(self) -> None:
        """非正向：越界值收敛到边界。"""
        assert _clamp_int(999, 5, 1, 50) == 50
        assert _clamp_int(-3, 1, 0, 5) == 0


class TestCodeToolsRegistered:
    """注册表必须包含代码工具（全阶段共用同一注册表）。"""

    def test_registry_contains_code_tools(self) -> None:
        registry = create_default_tool_registry()
        names = {t["name"] for t in registry.get_available_tools()}
        assert "code.retrieve" in names
        assert "code.structure" in names

    def test_code_tools_have_descriptions_and_params(self) -> None:
        registry = create_default_tool_registry()
        tools = {t["name"]: t for t in registry.get_available_tools()}
        assert "query" in tools["code.retrieve"]["parameters"]
        assert "node_id" in tools["code.structure"]["parameters"]
        assert tools["code.retrieve"]["description"]
        assert tools["code.structure"]["description"]


class TestCodeRetrieveTool:
    """code.retrieve：语义检索 + 图扩展的工具包装行为。"""

    async def test_retrieve_returns_results(self) -> None:
        registry = create_default_tool_registry()
        fake = [{"chunk_id": "a.py::f", "content": "def f(): ..."}]
        with patch("app.rag.retriever.retrieve_code", new=AsyncMock(return_value=fake)) as mock_rc:
            result = await registry.execute("code.retrieve", {"meeting_id": "m-1", "query": "登录校验", "top_k": 3})
        assert result.success is True
        assert result.result["status"] == "ok"
        assert result.result["count"] == 1
        mock_rc.assert_awaited_once_with("m-1", "登录校验", top_k=3, max_hops=1)

    async def test_empty_query_rejected(self) -> None:
        """非正向：空查询直接返回 error，不打穿到检索层。"""
        registry = create_default_tool_registry()
        with patch("app.rag.retriever.retrieve_code", new=AsyncMock()) as mock_rc:
            result = await registry.execute("code.retrieve", {"meeting_id": "m-1", "query": "   "})
        assert result.result["status"] == "error"
        mock_rc.assert_not_awaited()

    async def test_no_code_meeting_degrades_to_empty(self) -> None:
        """非正向：会议无代码索引 → 空列表降级，调用本身仍成功。"""
        registry = create_default_tool_registry()
        with patch("app.rag.retriever.retrieve_code", new=AsyncMock(return_value=[])):
            result = await registry.execute("code.retrieve", {"meeting_id": "m-empty", "query": "任意查询"})
        assert result.success is True
        assert result.result["count"] == 0
        assert result.result["results"] == []

    async def test_out_of_range_top_k_clamped(self) -> None:
        """非正向：LLM 传越界 top_k → 收敛到上限 50。"""
        registry = create_default_tool_registry()
        with patch("app.rag.retriever.retrieve_code", new=AsyncMock(return_value=[])) as mock_rc:
            await registry.execute("code.retrieve", {"meeting_id": "m-1", "query": "q", "top_k": 999})
        mock_rc.assert_awaited_once_with("m-1", "q", top_k=50, max_hops=1)

    async def test_step_callback_emitted(self) -> None:
        """tool.step 监控回放：检索开始/完成两个步骤事件都要发射。"""
        registry = create_default_tool_registry()
        step_cb = AsyncMock()
        with patch("app.rag.retriever.retrieve_code", new=AsyncMock(return_value=[{"x": 1}])):
            await registry.execute(
                "code.retrieve",
                {"meeting_id": "m-1", "query": "q", "_step_callback": step_cb},
            )
        step_types = [c.args[0] for c in step_cb.await_args_list]
        assert "code_search_started" in step_types
        assert "code_search_done" in step_types


class TestCodeStructureTool:
    """code.structure：调用关系查询的工具包装行为。"""

    async def test_structure_returns_callers_and_deps(self) -> None:
        registry = create_default_tool_registry()
        fake = {
            "node_id": "a.py::f",
            "callers": [{"node_id": "b.py::g", "hop": 1, "edge_type": "CALLS", "via": None}],
            "dependencies": [],
        }
        with patch("app.rag.graph_expand.structure_query", return_value=fake) as mock_sq:
            result = await registry.execute("code.structure", {"meeting_id": "m-1", "node_id": "a.py::f"})
        assert result.success is True
        assert result.result["status"] == "ok"
        assert len(result.result["callers"]) == 1
        mock_sq.assert_called_once_with("m-1", "a.py::f", max_hops=1)

    async def test_empty_node_id_rejected(self) -> None:
        """非正向：空 node_id 直接返回 error。"""
        registry = create_default_tool_registry()
        with patch("app.rag.graph_expand.structure_query") as mock_sq:
            result = await registry.execute("code.structure", {"meeting_id": "m-1", "node_id": ""})
        assert result.result["status"] == "error"
        mock_sq.assert_not_called()

    async def test_unknown_node_degrades_to_empty(self) -> None:
        """非正向：节点不存在 → 空 callers/dependencies，不报错。"""
        registry = create_default_tool_registry()
        fake = {"node_id": "ghost", "callers": [], "dependencies": []}
        with patch("app.rag.graph_expand.structure_query", return_value=fake):
            result = await registry.execute("code.structure", {"meeting_id": "m-1", "node_id": "ghost"})
        assert result.success is True
        assert result.result["callers"] == []
        assert result.result["dependencies"] == []


class TestSummarizeCodeResults:
    """事件摘要：代码工具结果不能被误判为浏览器动作。"""

    def test_code_retrieve_summary(self) -> None:
        summary = _summarize_result({"status": "ok", "count": 3, "results": []}, "code.retrieve")
        assert summary == {"type": "code_results", "count": 3}

    def test_code_structure_summary(self) -> None:
        summary = _summarize_result(
            {"status": "ok", "node_id": "a.py::f", "callers": [1, 2], "dependencies": [3]},
            "code.structure",
        )
        assert summary["type"] == "code_structure"
        assert summary["callers"] == 2
        assert summary["dependencies"] == 1

    def test_code_summary_not_misclassified_as_browser(self) -> None:
        """回归：status=ok 的 code.retrieve 不得落入 browser_action 分支。"""
        summary = _summarize_result({"status": "ok", "count": 1, "results": []}, "code.retrieve")
        assert summary.get("type") != "browser_action"
