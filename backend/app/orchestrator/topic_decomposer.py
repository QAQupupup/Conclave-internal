# ADR-014 Phase 3: 议题拆分器（Topic Decomposer）
# 将复杂议题拆分为子议题 DAG，每个子议题标注类型并走对应工作流模板
from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from app.logging_config import get_logger

logger = get_logger("orchestrator.topic_decomposer")

# ---------- 拆分约束 ----------
MAX_SUBTOPICS = 5  # 最多 5 个子议题（防止过度拆分）
MAX_DEPENDENCY_DEPTH = 3  # 依赖链深度不超过 3 层


class SubTopic(BaseModel):
    """子议题节点"""

    id: str  # 子议题 ID（如 "sub-1"）
    title: str  # 子议题标题
    topic_type: str  # analysis | design | build | research | report
    key_questions: list[str] = Field(default_factory=list)  # 子议题的关键问题
    depends_on: list[str] = Field(default_factory=list)  # 依赖的其他子议题 ID
    assigned_roles: list[str] = Field(default_factory=list)  # 建议参与角色
    workflow_template: str = "standard"  # 使用的工作流模板 ID


class TopicDecomposition(BaseModel):
    """议题拆分结果（DAG）"""

    root_topic: str  # 原始议题
    subtopics: list[SubTopic] = Field(default_factory=list)  # 子议题列表（DAG 节点）
    edges: list[tuple[str, str]] = Field(default_factory=list)  # 依赖边 (from_id, to_id)
    aggregation_strategy: str = "sequential"  # 聚合策略：sequential | parallel | hierarchical


# ---------- DAG 校验 ----------


def _build_adjacency_list(decomposition: TopicDecomposition) -> dict[str, list[str]]:
    """构建邻接表（from → [to, to, ...]）"""
    adj: dict[str, list[str]] = {s.id: [] for s in decomposition.subtopics}
    for from_id, to_id in decomposition.edges:
        if from_id in adj:
            adj[from_id].append(to_id)
    return adj


def _detect_cycle(decomposition: TopicDecomposition) -> bool:
    """检测 DAG 中是否有环（DFS 三色标记法）"""
    adj = _build_adjacency_list(decomposition)
    color: dict[str, int] = {s.id: 0 for s in decomposition.subtopics}  # 0=white, 1=gray, 2=black

    def dfs(node: str) -> bool:
        if color.get(node, 0) == 1:
            return True  # 灰色节点 = 回边 = 有环
        if color.get(node, 0) == 2:
            return False  # 黑色节点 = 已完成
        color[node] = 1
        for neighbor in adj.get(node, []):
            if dfs(neighbor):
                return True
        color[node] = 2
        return False

    return any(color[node_id] == 0 and dfs(node_id) for node_id in color)


def _max_depth(decomposition: TopicDecomposition) -> int:
    """计算 DAG 的最大依赖链深度"""
    adj = _build_adjacency_list(decomposition)
    depth_cache: dict[str, int] = {}

    def get_depth(node: str) -> int:
        if node in depth_cache:
            return depth_cache[node]
        neighbors = adj.get(node, [])
        if not neighbors:
            depth_cache[node] = 1
            return 1
        depth_cache[node] = 1 + max(get_depth(n) for n in neighbors)
        return depth_cache[node]

    if not decomposition.subtopics:
        return 0
    return max(get_depth(s.id) for s in decomposition.subtopics)


def validate_decomposition(decomposition: TopicDecomposition) -> tuple[bool, str]:
    """校验议题拆分结果是否合法

    Returns:
        (is_valid, reason) — 合法时 reason 为空字符串
    """
    # 1. 子议题数量
    if len(decomposition.subtopics) == 0:
        return False, "无子议题"
    if len(decomposition.subtopics) > MAX_SUBTOPICS:
        return False, f"子议题数量 {len(decomposition.subtopics)} 超过上限 {MAX_SUBTOPICS}"

    # 2. ID 唯一性
    ids = [s.id for s in decomposition.subtopics]
    if len(set(ids)) != len(ids):
        return False, "子议题 ID 不唯一"

    # 3. 依赖引用合法性
    id_set = set(ids)
    for s in decomposition.subtopics:
        for dep in s.depends_on:
            if dep not in id_set:
                return False, f"子议题 {s.id} 依赖了不存在的子议题 {dep}"

    # 4. 边引用合法性
    for from_id, to_id in decomposition.edges:
        if from_id not in id_set or to_id not in id_set:
            return False, f"依赖边 ({from_id}, {to_id}) 引用了不存在的子议题"

    # 5. 无环检测
    if _detect_cycle(decomposition):
        return False, "依赖图存在环（循环依赖）"

    # 6. 依赖链深度
    depth = _max_depth(decomposition)
    if depth > MAX_DEPENDENCY_DEPTH:
        return False, f"依赖链深度 {depth} 超过上限 {MAX_DEPENDENCY_DEPTH}"

    return True, ""


def topological_sort(decomposition: TopicDecomposition) -> list[str]:
    """拓扑排序：返回按依赖顺序排列的子议题 ID 列表

    被依赖的子议题排在前面，依赖方排在后面。
    """
    adj = _build_adjacency_list(decomposition)
    in_degree: dict[str, int] = {s.id: 0 for s in decomposition.subtopics}

    for _from_id, to_id in decomposition.edges:
        in_degree[to_id] = in_degree.get(to_id, 0) + 1

    # Kahn's algorithm
    queue = [sid for sid, deg in in_degree.items() if deg == 0]
    result: list[str] = []

    while queue:
        node = queue.pop(0)
        result.append(node)
        for neighbor in adj.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return result


# ---------- LLM 拆分 ----------

_DECOMPOSE_PROMPT = """[系统] 你是议题拆分专家。将复杂议题拆分为可独立处理的子议题。

## 议题
{topic}

## 澄清信息
- 关键问题: {key_questions}
- 团队配置: {team_config}

## 拆分规则
1. 最多 {max_subtopics} 个子议题
2. 每个子议题必须可独立执行
3. 子议题间可声明依赖（被依赖方先执行）
4. 依赖链深度不超过 {max_depth} 层
5. 为每个子议题分配合适的类型和角色

## 子议题类型
- analysis: 商业分析、市场调研、数据洞察
- design: 架构设计、系统设计、方案设计
- build: 可部署服务、工程实现、代码生成
- research: 技术调研、文献综述、可行性研究
- report: 通用报告（不属于以上类型时选此）

## 输出 JSON
{{
  "root_topic": "原始议题",
  "subtopics": [
    {{
      "id": "sub-1",
      "title": "子议题标题",
      "topic_type": "analysis|design|build|research|report",
      "key_questions": ["问题1", "问题2"],
      "depends_on": [],
      "assigned_roles": ["product_architect", "engineer"],
      "workflow_template": "standard|design|build|research|analysis"
    }}
  ],
  "edges": [["sub-1", "sub-2"]],
  "aggregation_strategy": "sequential|parallel|hierarchical"
}}

只输出 JSON，不要其他内容。"""


async def decompose_topic(
    topic: str,
    key_questions: list[str],
    team_config: list[dict[str, Any]],
    model: str = "",
) -> TopicDecomposition | None:
    """调用 LLM 将复杂议题拆分为子议题 DAG

    ADR-014 Phase 3: 在 clarify 阶段后，若 complexity == "full"，
    调用本函数执行议题拆分。拆分结果经过 DAG 校验后存入 MeetingState。

    Args:
        topic: 澄清后的议题文本
        key_questions: clarify 阶段提取的关键问题
        team_config: clarify 阶段配置的团队角色
        model: 指定使用的 LLM 模型（空=使用默认）

    Returns:
        拆分结果 TopicDecomposition，拆分失败或校验不通过返回 None
    """
    from app.agents.compute import ThinkRequest, execute_think
    from app.orchestrator.nodes._helpers import _resolve_model_for_call

    resolved_model = model or _resolve_model_for_call(
        MeetingStatePlaceholder(),  # type: ignore[arg-type]
        role="moderator",
        stage="clarify",
    )

    prompt = _DECOMPOSE_PROMPT.format(
        topic=topic,
        key_questions=", ".join(key_questions[:5]) if key_questions else "无",
        team_config=", ".join(t.get("role", "?") for t in team_config) if team_config else "默认",
        max_subtopics=MAX_SUBTOPICS,
        max_depth=MAX_DEPENDENCY_DEPTH,
    )

    try:
        resp = await execute_think(
            ThinkRequest(
                agent_role="moderator",
                stage="clarify",
                prompt=prompt,
                schema_hint="topic_decomposition",
                temperature=0,
                model=resolved_model,
            )
        )

        result = resp.result if isinstance(resp.result, dict) else {}

        decomposition = TopicDecomposition(
            root_topic=result.get("root_topic", topic),
            subtopics=[
                SubTopic(**s) for s in result.get("subtopics", []) if isinstance(s, dict) and "id" in s and "title" in s
            ],
            edges=[tuple(e) for e in result.get("edges", []) if isinstance(e, list) and len(e) == 2],
            aggregation_strategy=result.get("aggregation_strategy", "sequential"),
        )

        # 校验拆分结果
        is_valid, reason = validate_decomposition(decomposition)
        if not is_valid:
            logger.warning("议题拆分校验失败: %s", reason)
            return None

        logger.info(
            "议题拆分完成: %d 个子议题, 策略=%s",
            len(decomposition.subtopics),
            decomposition.aggregation_strategy,
        )
        return decomposition

    except Exception as e:
        logger.error("议题拆分异常: %s", e, exc_info=True)
        return None


# ---------- 辅助 ----------


class MeetingStatePlaceholder:
    """占位符，用于 _resolve_model_for_call 的参数兼容

    decompose_topic 在 clarify 阶段调用，此时还没有完整的 MeetingState，
    但 _resolve_model_for_call 只读取 model_override/resolved_models 字段。
    """

    model_override: str = ""
    resolved_models: ClassVar[dict[str, str]] = {}


def get_subtopic_execution_order(decomposition: TopicDecomposition) -> list[SubTopic]:
    """获取按依赖顺序排列的子议题列表（拓扑排序）

    Returns:
        按执行顺序排列的 SubTopic 列表
    """
    ordered_ids = topological_sort(decomposition)
    id_to_subtopic = {s.id: s for s in decomposition.subtopics}
    return [id_to_subtopic[sid] for sid in ordered_ids if sid in id_to_subtopic]


def should_decompose(complexity: str, workflow_template: str) -> bool:
    """判断是否需要执行议题拆分

    ADR-014 Phase 3: 仅当 complexity == "full" 且使用非 standard 模板时拆分。
    standard 模板保持原有行为（不拆分）。

    Args:
        complexity: clarify 阶段输出的复杂度
        workflow_template: 已选择的工作流模板 ID

    Returns:
        True 表示需要拆分
    """
    if complexity != "full":
        return False
    # standard 模板 = 默认六阶段，不需要拆分；非 standard 模板需要拆分
    return workflow_template != "standard"
