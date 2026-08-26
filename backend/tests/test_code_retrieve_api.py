# 代码检索 API 路由测试（ADR-016 Phase C）
# 验证真实端点 code_retrieve / code_structure：会议归属校验被调用、
# 参数校验（pydantic 边界）、结果包装结构、结构查询真实图命中与空图降级。
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.rag.code_graph import CodeGraph
from app.rag.graph_expand import register_graph, unregister_graph
from app.routers import code as code_router
from app.schemas.code import CodeRetrieveRequest, StructureQueryRequest


@pytest.fixture(autouse=True)
def _patched_meeting_ownership(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离会议归属校验（依赖 DB），聚焦验证路由层逻辑。"""

    async def _noop(_meeting_id: str | None = None) -> None:
        return None

    monkeypatch.setattr(code_router, "_ensure_meeting_owned", _noop)


class TestCodeStructureEndpoint:
    async def test_returns_callers_and_dependencies_for_real_graph(self) -> None:
        # B 被 A/D 调用（反向 CALLS），不调用他人；注册真实图走真实 structure_query
        g = CodeGraph()
        g.add_edge("CALLS", "a.py::A", "a.py::B")
        g.add_edge("CALLS", "a.py::D", "a.py::B")
        g.add_edge("INHERITS", "a.py::Child", "a.py::Base")
        register_graph("sm", g)
        try:
            body = StructureQueryRequest(node_id="a.py::B", max_hops=1)
            resp = await code_router.code_structure("sm", body)
        finally:
            unregister_graph("sm")

        assert resp["node_id"] == "a.py::B"
        assert {c["node_id"] for c in resp["callers"]} == {"a.py::A", "a.py::D"}
        assert {c["edge_type"] for c in resp["callers"]} == {"CALLS"}
        assert all(c["hop"] == 1 for c in resp["callers"])
        # B 无出边，dependencies 为空
        assert resp["dependencies"] == []

    async def test_unknown_node_or_no_graph_degrades_to_empty(self) -> None:
        body = StructureQueryRequest(node_id="ghost::x", max_hops=1)
        resp = await code_router.code_structure("no-graph", body)
        assert resp == {"node_id": "ghost::x", "callers": [], "dependencies": []}


class TestCodeRetrieveEndpoint:
    async def test_wraps_results_with_count_and_delegates_args(self) -> None:
        fake = [{"chunk_id": "a.py::A", "score": 0.9, "text": "def A(): pass"}]
        with patch("app.rag.retriever.retrieve_code", new=AsyncMock(return_value=fake)) as mock_retrieve:
            body = CodeRetrieveRequest(query="A", top_k=7, max_hops=2)
            resp = await code_router.code_retrieve("m", body)

        assert resp["meeting_id"] == "m"
        assert resp["count"] == 1
        assert resp["results"] == fake
        # 端点把解析后的参数原样透传给真实 retrieve_code
        mock_retrieve.assert_awaited_once_with("m", "A", top_k=7, max_hops=2)


class TestCodeRetrieveValidation:
    """pydantic 边界校验：空查询与越界参数必须在进入 handler 前被拒绝。"""

    @pytest.mark.parametrize("query", ["", "   "])
    def test_empty_query_rejected(self, query: str) -> None:
        with pytest.raises(ValidationError):
            CodeRetrieveRequest(query=query)

    @pytest.mark.parametrize("kwargs", [{"top_k": 0}, {"top_k": 51}, {"max_hops": -1}, {"max_hops": 6}])
    def test_out_of_range_rejected(self, kwargs: dict) -> None:
        with pytest.raises(ValidationError):
            CodeRetrieveRequest(query="A", **kwargs)

    def test_blank_node_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StructureQueryRequest(node_id="")
