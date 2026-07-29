# ADR-014 Phase 3: 议题拆分器测试套件
from __future__ import annotations

from app.orchestrator.result_aggregator import (
    aggregate_hierarchical,
    aggregate_results,
    aggregate_sequential,
    build_aggregation_context,
)
from app.orchestrator.topic_decomposer import (
    MAX_DEPENDENCY_DEPTH,
    MAX_SUBTOPICS,
    SubTopic,
    TopicDecomposition,
    _detect_cycle,
    _max_depth,
    get_subtopic_execution_order,
    should_decompose,
    topological_sort,
    validate_decomposition,
)

# ---------- 数据模型测试 ----------


class TestSubTopic:
    def test_default_values(self):
        """SubTopic 默认值正确"""
        s = SubTopic(id="sub-1", title="测试子议题", topic_type="analysis")
        assert s.id == "sub-1"
        assert s.title == "测试子议题"
        assert s.topic_type == "analysis"
        assert s.key_questions == []
        assert s.depends_on == []
        assert s.assigned_roles == []
        assert s.workflow_template == "standard"

    def test_with_dependencies(self):
        """SubTopic 支持依赖声明"""
        s = SubTopic(
            id="sub-2",
            title="依赖前一个的子议题",
            topic_type="design",
            depends_on=["sub-1"],
            assigned_roles=["product_architect", "engineer"],
            workflow_template="design",
        )
        assert s.depends_on == ["sub-1"]
        assert len(s.assigned_roles) == 2
        assert s.workflow_template == "design"


class TestTopicDecomposition:
    def test_empty_decomposition(self):
        """空拆分结果"""
        d = TopicDecomposition(root_topic="测试议题")
        assert d.root_topic == "测试议题"
        assert d.subtopics == []
        assert d.edges == []
        assert d.aggregation_strategy == "sequential"

    def test_with_subtopics(self):
        """带子议题的拆分结果"""
        d = TopicDecomposition(
            root_topic="构建可部署服务",
            subtopics=[
                SubTopic(id="sub-1", title="架构设计", topic_type="design"),
                SubTopic(id="sub-2", title="工程实现", topic_type="build", depends_on=["sub-1"]),
            ],
            edges=[("sub-1", "sub-2")],
            aggregation_strategy="hierarchical",
        )
        assert len(d.subtopics) == 2
        assert d.edges == [("sub-1", "sub-2")]
        assert d.aggregation_strategy == "hierarchical"


# ---------- DAG 校验测试 ----------


class TestValidateDecomposition:
    def test_valid_simple(self):
        """合法的简单拆分（无依赖）"""
        d = TopicDecomposition(
            root_topic="测试",
            subtopics=[
                SubTopic(id="sub-1", title="A", topic_type="analysis"),
                SubTopic(id="sub-2", title="B", topic_type="design"),
            ],
        )
        is_valid, reason = validate_decomposition(d)
        assert is_valid, f"Expected valid, got: {reason}"
        assert reason == ""

    def test_valid_with_dependencies(self):
        """合法的带依赖拆分"""
        d = TopicDecomposition(
            root_topic="测试",
            subtopics=[
                SubTopic(id="sub-1", title="A", topic_type="research"),
                SubTopic(id="sub-2", title="B", topic_type="design", depends_on=["sub-1"]),
                SubTopic(id="sub-3", title="C", topic_type="build", depends_on=["sub-2"]),
            ],
            edges=[("sub-1", "sub-2"), ("sub-2", "sub-3")],
        )
        is_valid, reason = validate_decomposition(d)
        assert is_valid, f"Expected valid, got: {reason}"

    def test_empty_subtopics_invalid(self):
        """无子议题不合法"""
        d = TopicDecomposition(root_topic="测试")
        is_valid, reason = validate_decomposition(d)
        assert not is_valid
        assert "无子议题" in reason

    def test_too_many_subtopics(self):
        """超过最大子议题数"""
        subtopics = [SubTopic(id=f"sub-{i}", title=f"子议题{i}", topic_type="report") for i in range(MAX_SUBTOPICS + 1)]
        d = TopicDecomposition(root_topic="测试", subtopics=subtopics)
        is_valid, reason = validate_decomposition(d)
        assert not is_valid
        assert "超过上限" in reason

    def test_duplicate_ids(self):
        """ID 不唯一"""
        d = TopicDecomposition(
            root_topic="测试",
            subtopics=[
                SubTopic(id="sub-1", title="A", topic_type="analysis"),
                SubTopic(id="sub-1", title="B", topic_type="design"),
            ],
        )
        is_valid, reason = validate_decomposition(d)
        assert not is_valid
        assert "不唯一" in reason

    def test_invalid_dependency_reference(self):
        """依赖了不存在的子议题"""
        d = TopicDecomposition(
            root_topic="测试",
            subtopics=[
                SubTopic(id="sub-1", title="A", topic_type="analysis", depends_on=["sub-99"]),
            ],
        )
        is_valid, reason = validate_decomposition(d)
        assert not is_valid
        assert "不存在" in reason

    def test_cycle_detection(self):
        """循环依赖检测"""
        d = TopicDecomposition(
            root_topic="测试",
            subtopics=[
                SubTopic(id="sub-1", title="A", topic_type="analysis", depends_on=["sub-2"]),
                SubTopic(id="sub-2", title="B", topic_type="design", depends_on=["sub-1"]),
            ],
            edges=[("sub-1", "sub-2"), ("sub-2", "sub-1")],
        )
        is_valid, reason = validate_decomposition(d)
        assert not is_valid
        assert "环" in reason

    def test_max_depth_exceeded(self):
        """依赖链深度超过限制"""
        # 构建深度为 MAX_DEPENDENCY_DEPTH + 1 的链
        subtopics = []
        edges = []
        for i in range(MAX_DEPENDENCY_DEPTH + 2):
            deps = [f"sub-{i}"] if i > 0 else []
            subtopics.append(SubTopic(id=f"sub-{i + 1}", title=f"子议题{i + 1}", topic_type="report", depends_on=deps))
            if i > 0:
                edges.append((f"sub-{i}", f"sub-{i + 1}"))
        d = TopicDecomposition(root_topic="测试", subtopics=subtopics, edges=edges)
        is_valid, reason = validate_decomposition(d)
        assert not is_valid
        assert "深度" in reason

    def test_max_depth_at_limit(self):
        """依赖链深度刚好等于限制（合法）"""
        # 构建深度为 MAX_DEPENDENCY_DEPTH 的链（MAX_DEPENDENCY_DEPTH 个节点，深度 = 节点数）
        subtopics = []
        edges = []
        for i in range(MAX_DEPENDENCY_DEPTH):
            deps = [f"sub-{i}"] if i > 0 else []
            subtopics.append(SubTopic(id=f"sub-{i + 1}", title=f"子议题{i + 1}", topic_type="report", depends_on=deps))
            if i > 0:
                edges.append((f"sub-{i}", f"sub-{i + 1}"))
        d = TopicDecomposition(root_topic="测试", subtopics=subtopics, edges=edges)
        is_valid, reason = validate_decomposition(d)
        assert is_valid, f"Expected valid at limit, got: {reason}"


# ---------- 环检测测试 ----------


class TestCycleDetection:
    def test_no_cycle_simple(self):
        """无环（简单图）"""
        d = TopicDecomposition(
            root_topic="测试",
            subtopics=[
                SubTopic(id="a", title="A", topic_type="analysis"),
                SubTopic(id="b", title="B", topic_type="design"),
            ],
        )
        assert not _detect_cycle(d)

    def test_no_cycle_chain(self):
        """无环（链式依赖）"""
        d = TopicDecomposition(
            root_topic="测试",
            subtopics=[
                SubTopic(id="a", title="A", topic_type="analysis"),
                SubTopic(id="b", title="B", topic_type="design"),
                SubTopic(id="c", title="C", topic_type="build"),
            ],
            edges=[("a", "b"), ("b", "c")],
        )
        assert not _detect_cycle(d)

    def test_cycle_two_nodes(self):
        """两节点环"""
        d = TopicDecomposition(
            root_topic="测试",
            subtopics=[
                SubTopic(id="a", title="A", topic_type="analysis"),
                SubTopic(id="b", title="B", topic_type="design"),
            ],
            edges=[("a", "b"), ("b", "a")],
        )
        assert _detect_cycle(d)

    def test_cycle_three_nodes(self):
        """三节点环"""
        d = TopicDecomposition(
            root_topic="测试",
            subtopics=[
                SubTopic(id="a", title="A", topic_type="analysis"),
                SubTopic(id="b", title="B", topic_type="design"),
                SubTopic(id="c", title="C", topic_type="build"),
            ],
            edges=[("a", "b"), ("b", "c"), ("c", "a")],
        )
        assert _detect_cycle(d)


# ---------- 深度计算测试 ----------


class TestMaxDepth:
    def test_single_node(self):
        """单节点深度为 1"""
        d = TopicDecomposition(
            root_topic="测试",
            subtopics=[SubTopic(id="a", title="A", topic_type="analysis")],
        )
        assert _max_depth(d) == 1

    def test_chain_depth(self):
        """链式依赖深度"""
        d = TopicDecomposition(
            root_topic="测试",
            subtopics=[
                SubTopic(id="a", title="A", topic_type="analysis"),
                SubTopic(id="b", title="B", topic_type="design"),
                SubTopic(id="c", title="C", topic_type="build"),
            ],
            edges=[("a", "b"), ("b", "c")],
        )
        assert _max_depth(d) == 3

    def test_empty(self):
        """空图深度为 0"""
        d = TopicDecomposition(root_topic="测试")
        assert _max_depth(d) == 0


# ---------- 拓扑排序测试 ----------


class TestTopologicalSort:
    def test_no_dependencies(self):
        """无依赖的拓扑排序"""
        d = TopicDecomposition(
            root_topic="测试",
            subtopics=[
                SubTopic(id="a", title="A", topic_type="analysis"),
                SubTopic(id="b", title="B", topic_type="design"),
            ],
        )
        result = topological_sort(d)
        assert set(result) == {"a", "b"}
        assert len(result) == 2

    def test_chain_order(self):
        """链式依赖的拓扑顺序"""
        d = TopicDecomposition(
            root_topic="测试",
            subtopics=[
                SubTopic(id="a", title="A", topic_type="analysis"),
                SubTopic(id="b", title="B", topic_type="design"),
                SubTopic(id="c", title="C", topic_type="build"),
            ],
            edges=[("a", "b"), ("b", "c")],
        )
        result = topological_sort(d)
        assert result == ["a", "b", "c"]

    def test_parallel_order(self):
        """并行子议题的拓扑顺序"""
        d = TopicDecomposition(
            root_topic="测试",
            subtopics=[
                SubTopic(id="a", title="A", topic_type="analysis"),
                SubTopic(id="b", title="B", topic_type="design"),
                SubTopic(id="c", title="C", topic_type="build", depends_on=["a", "b"]),
            ],
            edges=[("a", "c"), ("b", "c")],
        )
        result = topological_sort(d)
        # a 和 b 都在 c 前面
        assert result.index("a") < result.index("c")
        assert result.index("b") < result.index("c")


# ---------- should_decompose 测试 ----------


class TestShouldDecompose:
    def test_simple_not_decompose(self):
        """simple 复杂度不拆分"""
        assert not should_decompose("simple", "standard")

    def test_standard_not_decompose(self):
        """standard 复杂度不拆分"""
        assert not should_decompose("standard", "standard")

    def test_full_standard_not_decompose(self):
        """full + standard 模板不拆分"""
        assert not should_decompose("full", "standard")

    def test_full_design_should_decompose(self):
        """full + design 模板应拆分"""
        assert should_decompose("full", "design")

    def test_full_build_should_decompose(self):
        """full + build 模板应拆分"""
        assert should_decompose("full", "build")

    def test_full_research_should_decompose(self):
        """full + research 模板应拆分"""
        assert should_decompose("full", "research")

    def test_full_analysis_should_decompose(self):
        """full + analysis 模板应拆分"""
        assert should_decompose("full", "analysis")


# ---------- get_subtopic_execution_order 测试 ----------


class TestExecutionOrder:
    def test_returns_subtopic_objects(self):
        """返回 SubTopic 对象列表"""
        d = TopicDecomposition(
            root_topic="测试",
            subtopics=[
                SubTopic(id="a", title="A", topic_type="analysis"),
                SubTopic(id="b", title="B", topic_type="design", depends_on=["a"]),
            ],
            edges=[("a", "b")],
        )
        order = get_subtopic_execution_order(d)
        assert len(order) == 2
        assert all(isinstance(s, SubTopic) for s in order)
        assert order[0].id == "a"
        assert order[1].id == "b"

    def test_order_respects_dependencies(self):
        """执行顺序遵守依赖"""
        d = TopicDecomposition(
            root_topic="测试",
            subtopics=[
                SubTopic(id="c", title="C", topic_type="build", depends_on=["a", "b"]),
                SubTopic(id="a", title="A", topic_type="analysis"),
                SubTopic(id="b", title="B", topic_type="design", depends_on=["a"]),
            ],
            edges=[("a", "b"), ("a", "c"), ("b", "c")],
        )
        order = get_subtopic_execution_order(d)
        ids = [s.id for s in order]
        assert ids.index("a") < ids.index("b")
        assert ids.index("b") < ids.index("c")


# ---------- 结果聚合器测试 ----------


class TestResultAggregator:
    def _make_results(self, decomposition: TopicDecomposition) -> list[dict]:
        """构造模拟子议题结果"""
        results = []
        for s in decomposition.subtopics:
            results.append(
                {
                    "subtopic_id": s.id,
                    "title": s.title,
                    "result": {
                        "artifact": {"content": f"{s.title}的产出内容"},
                        "decisions": [{"id": "d1", "summary": "决策1"}],
                    },
                }
            )
        return results

    def test_sequential_aggregation(self):
        """顺序聚合"""
        d = TopicDecomposition(
            root_topic="构建可部署服务",
            subtopics=[
                SubTopic(id="sub-1", title="架构设计", topic_type="design"),
                SubTopic(id="sub-2", title="工程实现", topic_type="build", depends_on=["sub-1"]),
            ],
            edges=[("sub-1", "sub-2")],
            aggregation_strategy="sequential",
        )
        results = self._make_results(d)
        text = aggregate_sequential(d, results)
        assert "构建可部署服务" in text
        assert "架构设计" in text
        assert "工程实现" in text
        # sub-1 应在 sub-2 前面
        assert text.index("架构设计") < text.index("工程实现")

    def test_hierarchical_aggregation(self):
        """层级聚合"""
        d = TopicDecomposition(
            root_topic="构建可部署服务",
            subtopics=[
                SubTopic(id="sub-1", title="架构设计", topic_type="design"),
                SubTopic(id="sub-2", title="工程实现", topic_type="build", depends_on=["sub-1"]),
            ],
            edges=[("sub-1", "sub-2")],
            aggregation_strategy="hierarchical",
        )
        results = self._make_results(d)
        text = aggregate_hierarchical(d, results)
        assert "构建可部署服务" in text
        assert "架构设计" in text
        assert "工程实现" in text

    def test_aggregate_results_dispatch(self):
        """aggregate_results 根据策略分派"""
        d = TopicDecomposition(
            root_topic="测试",
            subtopics=[SubTopic(id="a", title="A", topic_type="analysis")],
            aggregation_strategy="sequential",
        )
        results = self._make_results(d)
        text = aggregate_results(d, results)
        assert "测试" in text
        assert "A" in text

    def test_aggregate_results_empty(self):
        """空结果聚合"""
        d = TopicDecomposition(
            root_topic="测试",
            subtopics=[SubTopic(id="a", title="A", topic_type="analysis")],
        )
        text = aggregate_results(d, [])
        assert "无子议题产出" in text

    def test_build_aggregation_context_no_decomposition(self):
        """无拆分时返回空字符串"""
        ctx = build_aggregation_context(None, [])
        assert ctx == ""

    def test_build_aggregation_context_with_results(self):
        """有拆分有结果时返回上下文"""
        d = TopicDecomposition(
            root_topic="测试议题",
            subtopics=[
                SubTopic(id="a", title="子议题A", topic_type="analysis"),
                SubTopic(id="b", title="子议题B", topic_type="design"),
            ],
        )
        results = self._make_results(d)
        ctx = build_aggregation_context(d, results)
        assert "子议题聚合结果" in ctx
        assert "子议题A" in ctx
        assert "子议题B" in ctx
        assert "最终交付物" in ctx

    def test_build_aggregation_context_empty_subtopics(self):
        """空子议题列表返回空字符串"""
        d = TopicDecomposition(root_topic="测试")
        ctx = build_aggregation_context(d, [])
        assert ctx == ""


# ---------- 模型序列化测试 ----------


class TestSerialization:
    def test_subtopic_serialization(self):
        """SubTopic 序列化/反序列化"""
        s = SubTopic(
            id="sub-1",
            title="测试",
            topic_type="design",
            key_questions=["Q1", "Q2"],
            depends_on=["sub-0"],
            assigned_roles=["engineer"],
            workflow_template="design",
        )
        data = s.model_dump()
        s2 = SubTopic(**data)
        assert s2.id == s.id
        assert s2.title == s.title
        assert s2.key_questions == s.key_questions
        assert s2.depends_on == s.depends_on

    def test_decomposition_serialization(self):
        """TopicDecomposition 序列化/反序列化（模拟 state 存储）"""
        d = TopicDecomposition(
            root_topic="测试议题",
            subtopics=[
                SubTopic(id="sub-1", title="A", topic_type="analysis"),
                SubTopic(id="sub-2", title="B", topic_type="design", depends_on=["sub-1"]),
            ],
            edges=[("sub-1", "sub-2")],
            aggregation_strategy="hierarchical",
        )
        # 序列化为 dict（存入 MeetingState.topic_decomposition）
        data = d.model_dump()
        # 反序列化（runner 中从 state 读取）
        d2 = TopicDecomposition(**data)
        assert d2.root_topic == d.root_topic
        assert len(d2.subtopics) == len(d.subtopics)
        assert d2.edges == d.edges
        assert d2.aggregation_strategy == d.aggregation_strategy
