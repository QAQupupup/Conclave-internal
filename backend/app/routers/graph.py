"""知识图谱 API：从会议/消息中提取节点和边。

返回前端 GraphData 格式：{nodes: [...], edges: [...]}
节点类型：topic/claim/evidence/conflict/source/agent
边类型：supports/contradicts/relates_to/proposed_by/derived_from/has_conflict

多租户隔离：非 system_admin 用户只能看到所属租户的会议数据。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import text

from app.db.engine import async_session_factory
from app.rbac.enforcer import SYSTEM_DOMAIN
from app.services.knowledge_graph import get_materialized_graph

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graph", tags=["graph"])

# 节点/边类型白名单
NODE_TYPES = {"topic", "claim", "evidence", "conflict", "source", "agent"}
EDGE_TYPES = {"supports", "contradicts", "relates_to", "proposed_by", "derived_from", "has_conflict"}


def _get_auth_context(request: Request) -> tuple[str, str | None, int | None, bool]:
    """从 request.state.auth_user 提取认证上下文。

    返回 (uid, username, tenant_id, is_system_admin)。
    未认证抛出 401。
    """
    auth_user = getattr(request.state, "auth_user", None)
    if not auth_user:
        raise HTTPException(status_code=401, detail="未认证")
    uid = auth_user.get("uid") or auth_user.get("user_id")
    username = auth_user.get("username")
    tenant_id = auth_user.get("tenant_id")
    domain = auth_user.get("domain", "")
    roles = auth_user.get("roles", ())
    is_system_admin = domain == SYSTEM_DOMAIN and ("system_admin" in roles or "system_owner" in roles)

    if not uid:
        raise HTTPException(status_code=401, detail="未认证")
    tid = int(tenant_id) if tenant_id is not None else None
    return str(uid), username, tid, is_system_admin


@router.get("/overview")
async def get_graph(
    request: Request,
    meeting_id: str | None = Query(default=None, description="可选会议 ID，不传则返回最近会议的聚合图谱"),
) -> dict[str, Any]:
    """获取知识图谱数据。

    当 meeting_id 提供时，返回该会议的论点图谱；
    否则返回最近 20 个会议的聚合图谱（按主题聚合）。
    """
    uid, _username, tenant_id, is_system_admin = _get_auth_context(request)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()
    seen_edges: set[str] = set()

    def add_node(nid: str, ntype: str, label: str, size: int = 16, meta: dict | None = None) -> None:
        if nid in seen_nodes:
            return
        if ntype not in NODE_TYPES:
            ntype = "topic"
        if len(label) > 80:
            label = label[:77] + "..."
        nodes.append(
            {
                "id": nid,
                "type": ntype,
                "label": label,
                "x": 0,
                "y": 0,
                "vx": 0,
                "vy": 0,
                "size": size,
                "meta": meta or {},
            }
        )
        seen_nodes.add(nid)

    def add_edge(source: str, target: str, etype: str, weight: float = 1.0) -> None:
        eid = f"{source}->{target}:{etype}"
        if eid in seen_edges:
            return
        if etype not in EDGE_TYPES:
            etype = "relates_to"
        edges.append(
            {
                "id": eid,
                "source": source,
                "target": target,
                "type": etype,
                "weight": weight,
            }
        )
        seen_edges.add(eid)

    def _build_tenant_filter(params: dict[str, Any], alias: str = "m") -> tuple[str, dict[str, Any]]:
        """构建多租户 WHERE 条件。系统管理员不限租户。"""
        if is_system_admin:
            return "", params
        if tenant_id is None:
            # 无租户的普通用户只能看到自己创建的会议
            return f"AND {alias}.owner_username = :uname", {**params, "uname": _username or uid}
        return f"AND {alias}.tenant_id = :tid", {**params, "tid": tenant_id}

    async with async_session_factory() as session:
        # 确定要查询的会议范围
        if meeting_id:
            mid = meeting_id.strip()
            if not mid:
                raise HTTPException(status_code=400, detail="无效的会议 ID")

            tenant_cond, params = _build_tenant_filter({"mid": mid})
            meetings_res = await session.execute(
                text(f"SELECT id, topic FROM meetings m WHERE m.id = :mid {tenant_cond}"),
                params,
            )
            meeting_rows = meetings_res.mappings().all()
            if not meeting_rows:
                raise HTTPException(status_code=404, detail="会议不存在或无权限访问")
        else:
            tenant_cond, params = _build_tenant_filter({})
            meetings_res = await session.execute(
                text(
                    f"SELECT id, topic FROM meetings m "
                    f"WHERE m.status != 'deleted' {tenant_cond} "
                    f"ORDER BY m.created_at DESC LIMIT 20"
                ),
                params,
            )
            meeting_rows = meetings_res.mappings().all()

        if not meeting_rows:
            return {"nodes": [], "edges": []}

        meeting_ids = [r["id"] for r in meeting_rows]

        # 1. 会议本身作为 topic 节点
        for m in meeting_rows:
            add_node(
                f"meeting-{m['id']}",
                "topic",
                m["topic"] or f"会议 #{m['id'][:8]}",
                size=28,
                meta={"meeting_id": m["id"]},
            )

        # 2. 从 messages 中提取 Agent 节点和 proposed_by 边
        # 使用参数化查询 = ANY(:ids) 替代 f-string IN 拼接
        messages_res = await session.execute(
            text(
                """
                SELECT m.id, m.meeting_id, m.agent_role, m.content, m.created_at
                FROM messages m
                WHERE m.meeting_id = ANY(:mids)
                ORDER BY m.created_at ASC
                LIMIT 500
                """
            ),
            {"mids": meeting_ids},
        )
        msg_rows = messages_res.mappings().all()

        # 收集出现的角色（非 user/system/assistant 的视为 agent）
        agent_roles: dict[str, int] = {}
        for msg in msg_rows:
            role = (msg["agent_role"] or "").strip()
            if role and role not in ("user", "system", "assistant"):
                agent_roles[role] = agent_roles.get(role, 0) + 1

        for role_name, count in agent_roles.items():
            add_node(f"agent-{role_name}", "agent", role_name, size=20, meta={"message_count": count})

        for msg in msg_rows:
            role = (msg["agent_role"] or "").strip()
            if role and role not in ("user", "system", "assistant"):
                add_edge(f"agent-{role}", f"meeting-{msg['meeting_id']}", "proposed_by", weight=0.5)

        # 3. 从文档/来源提取 source 节点（documents 表可能不存在，做容错）
        try:
            docs_res = await session.execute(
                text(
                    """
                    SELECT DISTINCT d.id, d.filename, d.meeting_id
                    FROM documents d
                    WHERE d.meeting_id = ANY(:mids)
                    LIMIT 50
                    """
                ),
                {"mids": meeting_ids},
            )
            for doc in docs_res.mappings().all():
                fn = doc["filename"] or f"文档 #{doc['id'][:8]}"
                add_node(f"source-{doc['id']}", "source", fn, size=10)
                add_edge(f"source-{doc['id']}", f"meeting-{doc['meeting_id']}", "derived_from", weight=0.3)
        except Exception as e:
            # documents 表可能不存在或结构不同，非致命错误
            logger.debug("Graph: documents 查询跳过（表可能不存在）: %s", e)

        # 4. 当指定单个会议时，从 content 中提取"主张"节点
        if meeting_id and msg_rows:
            claim_idx = 0
            for msg in msg_rows:
                content = (msg["content"] or "").strip()
                role = (msg["agent_role"] or "").strip()
                if not content or role in ("user", "system"):
                    continue
                if claim_idx >= 15:
                    break
                sentences = [s.strip() for s in re.split(r"[。！？!?\n]", content) if s.strip()]
                for sent in sentences[:2]:
                    if len(sent) < 5:
                        continue
                    cid = f"claim-{msg['id']}-{claim_idx}"
                    add_node(cid, "claim", sent, size=14, meta={"message_id": msg["id"]})
                    add_edge(cid, f"meeting-{msg['meeting_id']}", "relates_to", weight=0.7)
                    if role and role not in ("user", "system", "assistant"):
                        add_edge(f"agent-{role}", cid, "proposed_by", weight=0.8)
                    claim_idx += 1
                    if claim_idx >= 15:
                        break

        # 5. 多会议场景：按时间顺序连接会议（meeting_ids 已按 created_at DESC 排列）
        if not meeting_id and len(meeting_ids) > 1:
            # 按时间正序连接（从旧到新），meeting_ids 是 DESC，需反转
            chronological = list(reversed(meeting_ids))
            for i in range(len(chronological) - 1):
                add_edge(
                    f"meeting-{chronological[i]}",
                    f"meeting-{chronological[i + 1]}",
                    "relates_to",
                    weight=0.2,
                )

    # 6. [GraphRAG-lite] 合并物化语义边（conflicts→contradicts、evidence→supports）
    #    仅在有租户上下文时读取，避免跨租户泄露。seen_nodes/seen_edges 自动去重。
    if tenant_id is not None or is_system_admin:
        try:
            mat_nodes, mat_edges = await get_materialized_graph(meeting_id, tenant_id)
            for n in mat_nodes:
                add_node(n["id"], n["type"], n["label"], size=n.get("size", 14), meta=n.get("meta"))
            for edge in mat_edges:
                add_edge(edge["source"], edge["target"], edge["type"], weight=edge.get("weight", 1.0))
        except Exception as e:
            logger.debug("Graph: 物化边读取跳过: %s", e)

    return {"nodes": nodes, "edges": edges}
