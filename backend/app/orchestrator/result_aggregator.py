# ADR-014 Phase 3: 子议题结果聚合器（Result Aggregator）
# 将各子议题的产出聚合为最终交付物
from __future__ import annotations

from typing import Any

from app.logging_config import get_logger

from .topic_decomposer import SubTopic, TopicDecomposition, get_subtopic_execution_order

logger = get_logger("orchestrator.result_aggregator")


def _format_subtopic_result(subtopic: SubTopic, result: dict[str, Any]) -> str:
    """格式化单个子议题的产出为文本摘要"""
    lines = [
        f"## {subtopic.title}",
        f"类型: {subtopic.topic_type}",
    ]
    if subtopic.key_questions:
        lines.append(f"关键问题: {', '.join(subtopic.key_questions)}")

    # 提取产出内容
    artifact = result.get("artifact", {})
    if isinstance(artifact, dict):
        # PRD 结构
        if "prd" in artifact:
            prd = artifact["prd"]
            if isinstance(prd, dict):
                lines.append(f"目标: {prd.get('goal', 'N/A')}")
                lines.append(f"范围: {prd.get('scope', 'N/A')}")
        # 设计文档
        if "design_doc" in artifact:
            lines.append(f"设计文档: {str(artifact['design_doc'])[:500]}")
        # 通用产出
        if "content" in artifact:
            lines.append(f"内容: {str(artifact['content'])[:500]}")
    else:
        lines.append(f"产出: {str(artifact)[:500]}")

    # 决策记录
    decisions = result.get("decisions", [])
    if decisions:
        lines.append(f"决策: {len(decisions)} 项")

    return "\n".join(lines)


def aggregate_sequential(
    decomposition: TopicDecomposition,
    subtopic_results: list[dict[str, Any]],
) -> str:
    """顺序聚合：按依赖顺序拼接各子议题产出

    Args:
        decomposition: 议题拆分结果
        subtopic_results: 各子议题的执行结果列表
            每项: {"subtopic_id": "...", "title": "...", "result": {...}}

    Returns:
        聚合后的文本摘要
    """
    ordered = get_subtopic_execution_order(decomposition)
    id_to_result = {r.get("subtopic_id", ""): r for r in subtopic_results}

    sections: list[str] = [f"# {decomposition.root_topic}", ""]
    for i, subtopic in enumerate(ordered, 1):
        result = id_to_result.get(subtopic.id, {})
        inner_result = result.get("result", result)
        sections.append(f"### 子议题 {i}")
        sections.append(_format_subtopic_result(subtopic, inner_result))
        sections.append("")

    return "\n".join(sections)


def aggregate_hierarchical(
    decomposition: TopicDecomposition,
    subtopic_results: list[dict[str, Any]],
) -> str:
    """层级聚合：按依赖树组织，依赖方的产出包含被依赖方的摘要

    Args:
        decomposition: 议题拆分结果
        subtopic_results: 各子议题的执行结果列表

    Returns:
        聚合后的文本摘要
    """
    ordered = get_subtopic_execution_order(decomposition)
    id_to_result = {r.get("subtopic_id", ""): r for r in subtopic_results}
    id_to_subtopic = {s.id: s for s in decomposition.subtopics}

    # 构建反向邻接表（from → [to, ...]），即我被谁依赖
    # edge (from_id, to_id) 表示 to_id 依赖 from_id，所以 from_id 的 dependents 包含 to_id
    dependents: dict[str, list[str]] = {s.id: [] for s in decomposition.subtopics}
    for from_id, to_id in decomposition.edges:
        dependents[from_id].append(to_id)

    # 找到根节点（没有依赖任何其他子议题的节点）
    roots = [s for s in ordered if not s.depends_on]

    sections: list[str] = [f"# {decomposition.root_topic}", ""]

    def render_subtopic(sid: str, depth: int) -> None:
        subtopic = id_to_subtopic.get(sid)
        if not subtopic:
            return
        indent = "  " * depth
        result = id_to_result.get(sid, {})
        inner_result = result.get("result", result)
        lines = _format_subtopic_result(subtopic, inner_result)
        for line in lines.split("\n"):
            sections.append(f"{indent}{line}")
        sections.append("")

        # 递归渲染依赖此子议题的子议题
        for dep_id in dependents.get(sid, []):
            render_subtopic(dep_id, depth + 1)

    for root in roots:
        render_subtopic(root.id, 0)

    return "\n".join(sections)


def aggregate_results(
    decomposition: TopicDecomposition,
    subtopic_results: list[dict[str, Any]],
) -> str:
    """根据聚合策略聚合子议题结果

    ADR-014 Phase 3: 聚合器入口函数，由 produce 阶段调用。
    根据 decomposition.aggregation_strategy 选择聚合方式。

    Args:
        decomposition: 议题拆分结果
        subtopic_results: 各子议题的执行结果列表

    Returns:
        聚合后的文本摘要，作为最终产出的上下文
    """
    if not subtopic_results:
        logger.warning("聚合时无子议题结果")
        return f"# {decomposition.root_topic}\n\n（无子议题产出）"

    strategy = decomposition.aggregation_strategy

    if strategy == "hierarchical":
        return aggregate_hierarchical(decomposition, subtopic_results)
    else:
        # sequential 和 parallel 都用顺序聚合（parallel 在当前 MVP 中不并行执行）
        return aggregate_sequential(decomposition, subtopic_results)


def build_aggregation_context(
    decomposition: TopicDecomposition | None,
    subtopic_results: list[dict[str, Any]],
) -> str:
    """构建子议题聚合上下文，注入到 produce 阶段的 prompt 中

    如果没有议题拆分，返回空字符串（不影响原有 produce 行为）。

    Args:
        decomposition: 议题拆分结果（None 表示未拆分）
        subtopic_results: 各子议题的执行结果

    Returns:
        聚合上下文文本，空字符串表示无拆分
    """
    if decomposition is None or not decomposition.subtopics:
        return ""

    if not subtopic_results:
        return ""

    aggregated = aggregate_results(decomposition, subtopic_results)

    return f"""
## 子议题聚合结果
以下为各子议题的执行产出聚合，请基于此内容生成最终交付物：

{aggregated}

## 要求
- 将上述子议题产出整合为一份连贯的最终文档
- 保持各子议题的核心结论和建议
- 消除重复内容，统一术语和格式
- 确保最终文档的逻辑连贯性
"""
