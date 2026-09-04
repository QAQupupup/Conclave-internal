"""产物发布编排（ADR-017 Phase 1，Publish 模式 D2）。

职责：把会议运行态的 ``state.artifact``（工作副本）单向幂等发布到
``artifacts`` 表。运行态永远以 ``state.artifact`` 为准，本表只是发布快照；
发布失败只记日志、不阻断会议终态（可由补偿重试）。

大产物红线（ADR-017）：序列化超过阈值的产物不写 content 列，
只存 summary + content_ref 指针，防止 TOAST 膨胀。
"""

from __future__ import annotations

import json
from typing import Any

from app.dao import artifact_dao
from app.domain.meeting import MeetingState
from app.events import bus, make_event
from app.observability.log_bus import log_bus

# 大产物阈值：超过该字节数（JSON 序列化后）不写 content 列。
# 200KB：足以容纳绝大多数结构化文档（ADR/报告/PRD），
# 同时把代码类大产物（deployable_service/test_suite）挡在 DB 之外。
LARGE_ARTIFACT_BYTES = 200 * 1024

# 嵌套结构提取顺序（与 meeting_dao._extract_artifact_summary 保持一致）
# ADR-017 Phase 1：追加三种新产出类型（produce 模板输出同为嵌套结构）
_NESTED_KEYS = (
    "design_doc",
    "comprehensive",
    "research_report",
    "business_report",
    "feasibility_report",
    "adr",
    "test_suite",
)


def extract_artifact_summary(artifact: dict[str, Any] | None) -> str:
    """从 artifact 中提取简洁摘要文本（供下游会议注入 prompt）。

    与 ``meeting_dao._extract_artifact_summary`` 逻辑同源：
    优先顶层 title/overview/summary/executive_summary/verdict，
    其次尝试嵌套结构（design_doc 等）。
    """
    if not artifact:
        return "（无产出）"
    parts: list[str] = []
    for key in ("title", "overview", "summary", "executive_summary", "verdict"):
        value = artifact.get(key)
        if value:
            parts.append(str(value))
    if not parts:
        for key in _NESTED_KEYS:
            inner = artifact.get(key, {})
            if isinstance(inner, dict):
                for inner_key in ("title", "overview", "summary"):
                    value = inner.get(inner_key)
                    if value:
                        parts.append(str(value))
                if parts:
                    break
    return " | ".join(parts) if parts else "（无产出摘要）"


def _extract_title(artifact: dict[str, Any], artifact_type: str) -> str | None:
    """从 artifact 中提取标题（顶层 title 优先，其次嵌套类型键内 title）。"""
    title = artifact.get("title")
    if title:
        return str(title)[:500]
    inner = artifact.get(artifact_type)
    if isinstance(inner, dict) and inner.get("title"):
        return str(inner["title"])[:500]
    return None


async def publish_meeting_artifact(state: MeetingState) -> dict[str, Any] | None:
    """会议成功终态后发布产物入表（幂等）。

    - ``state.artifact`` 为空 → 不发布，返回 None
    - 版本号经 ``next_version`` 计算（同会议同类型递增），parent_id 指向上一版
    - 大产物只存 summary + content_ref（workspace 相对路径）
    - 血缘：``state.source_artifact_ids`` 随产物入库

    Returns:
        发布后的产物 dict；不发布时返回 None。

    Raises:
        Exception: 数据库写入异常由调用方（publish_and_notify）兜底，
            本函数保持"要么发布成功、要么抛错"的单一语义。
    """
    artifact = state.artifact
    if not artifact or not isinstance(artifact, dict):
        log_bus.info(
            "artifact publish 跳过：会议无产出",
            logger="services.artifact_service",
            extra={"meeting_id": state.meeting_id},
        )
        return None

    artifact_type = state.deliverable_type
    summary = extract_artifact_summary(artifact)
    title = _extract_title(artifact, artifact_type)

    # 大产物分流：超阈值不写 content 列，只存指针（ADR-017 红线）
    content: dict[str, Any] | None
    content_ref: str | None = None
    try:
        serialized_len = len(json.dumps(artifact, ensure_ascii=False, default=str).encode())
    except (TypeError, ValueError):
        serialized_len = LARGE_ARTIFACT_BYTES + 1  # 无法序列化 → 按大产物处理
    if serialized_len > LARGE_ARTIFACT_BYTES:
        content = None
        content_ref = f"{state.meeting_id}/"
    else:
        content = artifact

    version, parent_id = await artifact_dao.next_version(state.meeting_id, artifact_type)
    published = await artifact_dao.publish_artifact(
        meeting_id=state.meeting_id,
        artifact_type=artifact_type,
        version=version,
        title=title,
        summary=summary,
        content=content,
        content_ref=content_ref,
        parent_id=parent_id,
        source_artifact_ids=list(getattr(state, "source_artifact_ids", []) or []),
        created_by=getattr(state, "owner_username", None),
    )
    log_bus.info(
        f"产物已发布: type={artifact_type}, version={version}, id={published['id']}",
        logger="services.artifact_service",
        extra={
            "meeting_id": state.meeting_id,
            "artifact_id": published["id"],
            "type": artifact_type,
            "version": version,
        },
    )
    return published


# 血缘递归深度上限：防成环血缘无限遍历与大图爆炸（T1.11）。
# 10 层足以覆盖「可行性报告 → ADR → 服务」级别的真实链路。
MAX_LINEAGE_DEPTH = 10


def _lineage_node(artifact: dict[str, Any], depth: int) -> dict[str, Any]:
    """从产物 dict 提取血缘节点字段（不含 content，控制响应体积）。"""
    return {
        "id": artifact["id"],
        "type": artifact["type"],
        "title": artifact.get("title"),
        "version": artifact.get("version"),
        "meeting_id": artifact.get("meeting_id"),
        "created_at": artifact.get("created_at"),
        "depth": depth,
    }


async def get_lineage(root_id: str) -> dict[str, Any] | None:
    """查询产物上游血缘：沿 source_artifact_ids 逐层 BFS。

    - 根产物不存在/跨租户 → 返回 None（路由层转 404）
    - 深度上限 ``MAX_LINEAGE_DEPTH`` 防环；visited 集合防重复访问
    - 不存在/跨租户的上游静默跳过（与 DAO 租户语义一致，不建悬空边）

    Returns:
        ``{root_id, depth_limit, truncated, nodes, edges}``；
        edges 方向为 child（下游）→ parent（上游）。
    """
    root = await artifact_dao.get_artifact(root_id)
    if root is None:
        return None

    nodes: list[dict[str, Any]] = [_lineage_node(root, 0)]
    edges: list[dict[str, str]] = []
    visited: set[str] = {root_id}
    frontier: list[dict[str, Any]] = [root]
    depth = 0
    truncated = False
    while frontier:
        # 收集本层待访问的上游 id（去重保序）
        wanted = list(
            dict.fromkeys(
                src for art in frontier for src in (art.get("source_artifact_ids") or []) if src not in visited
            )
        )
        if not wanted:
            break
        if depth >= MAX_LINEAGE_DEPTH:
            truncated = True
            break
        depth += 1
        sources = await artifact_dao.get_artifacts_by_ids(wanted)
        if not sources:
            break
        by_id = {s["id"]: s for s in sources}
        # 只为实际可取回（同租户）的上游建边：
        # 新上游在本层 by_id 中；已访问过的上游（菱形血缘）在 visited 中
        for art in frontier:
            for src in art.get("source_artifact_ids") or []:
                if src in by_id or src in visited:
                    edges.append({"child_id": art["id"], "parent_id": src})
        frontier = []
        for src_art in sources:
            if src_art["id"] not in visited:
                visited.add(src_art["id"])
                nodes.append(_lineage_node(src_art, depth))
                frontier.append(src_art)

    return {
        "root_id": root_id,
        "depth_limit": MAX_LINEAGE_DEPTH,
        "truncated": truncated,
        "nodes": nodes,
        "edges": edges,
    }


async def publish_and_notify(state: MeetingState) -> dict[str, Any] | None:
    """终态挂钩统一入口：发布产物 + 广播事件，异常只记日志不抛出。

    供 runner（标准六阶段 DONE）与 instant（即时模式 DONE）两个终态路径
    调用。Publish 是快照动作，失败不应使会议僵死（017 任务清单 I7）。
    """
    try:
        published = await publish_meeting_artifact(state)
    except Exception as exc:
        log_bus.error(
            f"产物发布失败（不阻断会议终态）: {exc}",
            logger="services.artifact_service",
            extra={"meeting_id": state.meeting_id, "error": str(exc)[:500]},
        )
        return None
    if published is not None:
        await bus.publish(
            make_event(
                "artifact.published",
                state.meeting_id,
                {
                    "meeting_id": state.meeting_id,
                    "artifact_id": published["id"],
                    "type": published["type"],
                    "version": published["version"],
                },
            )
        )
    return published
