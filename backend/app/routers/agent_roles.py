# Agent 角色管理：CRUD + 议题驱动自动生成
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from app.db_legacy import (
    delete_agent_role,
    get_agent_role,
    list_agent_roles,
    save_agent_role,
)
from app.models import AgentRole, AgentRoleListResponse
from app.schemas.agent_role import (
    CreateRoleRequest,
    GenerateRolesRequest,
    GenerateRolesResponse,
    UpsertRoleResponse,
)

router = APIRouter(prefix="/agent-roles", tags=["agent-roles"])


# ---------- 内置角色种子数据 ----------

BUILTIN_ROLES = [
    {
        "id": "moderator",
        "display_name": "主持人",
        "perspective": "推进流程、澄清议题、识别冲突、维持规则",
        "expertise_domains": ["会议管理", "冲突调解", "流程控制"],
        "risk_appetite": "balanced",
        "default_stance": "neutral",
        "evidence_preference": "policies",
        "prompt_template": (
            "你是 Conclave 会议主持人。职责是推进流程、澄清议题、识别冲突、维持规则。"
            "决策偏置：保持中立，重流程合规与冲突暴露。"
        ),
        "background_brief": "经验丰富的会议主持人，善于引导讨论并确保各方观点被充分表达。",
    },
    {
        "id": "product_architect",
        "display_name": "产品架构师",
        "perspective": "目标、用户价值、系统边界、接口约束",
        "expertise_domains": ["产品设计", "系统架构", "需求分析"],
        "risk_appetite": "conservative",
        "default_stance": "value-first",
        "evidence_preference": "goals",
        "prompt_template": (
            "你是产品架构师。关注目标、用户价值、系统边界、接口约束。"
            "决策偏置：先谈价值与约束，再谈实现；重证据引用；适度保守。"
        ),
        "background_brief": "10年产品架构经验，主导过多个大型系统的架构设计，擅长平衡业务需求与技术约束。",
    },
    {
        "id": "engineer",
        "display_name": "工程师",
        "perspective": "可行性、实现风险、测试边界",
        "expertise_domains": ["后端开发", "系统设计", "代码质量"],
        "risk_appetite": "conservative",
        "default_stance": "feasibility-first",
        "evidence_preference": "constraints",
        "prompt_template": (
            "你是工程师，兼负 QA 视角。关注可行性、实现风险、测试边界。决策偏置：先质疑可行性，再谈方案；重执行细节。"
        ),
        "background_brief": "全栈工程师，擅长快速原型开发与性能优化，对代码可维护性有执念。",
    },
    {
        "id": "security_expert",
        "display_name": "安全专家",
        "perspective": "认证、授权、数据安全、注入防护",
        "expertise_domains": ["网络安全", "数据保护", "合规审计"],
        "risk_appetite": "conservative",
        "default_stance": "risk-first",
        "evidence_preference": "risk",
        "prompt_template": ("你是安全专家。关注认证、授权、数据安全、注入防护。决策偏置：先找安全漏洞，重风险。"),
        "background_brief": "资深安全工程师，曾在多家金融科技公司负责安全架构设计，对OWASP十大漏洞了如指掌。",
    },
    {
        "id": "data_engineer",
        "display_name": "数据工程师",
        "perspective": "数据模型、存储、迁移、一致性",
        "expertise_domains": ["数据库设计", "ETL", "数据治理"],
        "risk_appetite": "balanced",
        "default_stance": "data-first",
        "evidence_preference": "constraints",
        "prompt_template": ("你是数据工程师。关注数据模型、存储、迁移、一致性。决策偏置：重数据完整性。"),
        "background_brief": "数据工程专家，精通SQL与NoSQL数据库选型，对数据一致性和查询性能有深刻理解。",
    },
    {
        "id": "ux_designer",
        "display_name": "UX设计师",
        "perspective": "交互流程、可用性、错误处理",
        "expertise_domains": ["用户体验", "交互设计", "可用性测试"],
        "risk_appetite": "balanced",
        "default_stance": "user-first",
        "evidence_preference": "goals",
        "prompt_template": ("你是用户体验设计师。关注交互流程、可用性、错误处理。决策偏置：重用户视角。"),
        "background_brief": "UX设计师，擅长将复杂系统简化，让非技术用户也能顺畅使用产品。",
    },
]


async def _init_builtin_roles() -> int:
    """初始化内置角色到数据库（仅当数据库为空时）"""
    existing = await list_agent_roles()
    if existing:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    count = 0
    for r in BUILTIN_ROLES:
        await save_agent_role(
            {
                **r,
                "is_builtin": 1,
                "is_active": 1,
                "created_at": now,
                "updated_at": now,
            }
        )
        count += 1
    return count


# ---------- 端点 ----------


@router.get("", response_model=AgentRoleListResponse)
async def list_roles(active_only: bool = False) -> AgentRoleListResponse:
    """列出所有角色"""
    await _init_builtin_roles()
    rows = await list_agent_roles(active_only=active_only)
    roles = [AgentRole.from_db_row(r) for r in rows]
    return AgentRoleListResponse(roles=roles, total=len(roles))


@router.get("/{role_id}", response_model=AgentRole)
async def get_role(role_id: str) -> AgentRole:
    """取单个角色"""
    await _init_builtin_roles()
    row = await get_agent_role(role_id)
    if row is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    return AgentRole.from_db_row(row)


@router.post("", response_model=UpsertRoleResponse)
async def create_role(req: CreateRoleRequest) -> UpsertRoleResponse:
    """创建新角色"""
    row = await get_agent_role(req.id)
    if row is not None:
        raise HTTPException(status_code=409, detail="角色 ID 已存在")
    now = datetime.now(timezone.utc).isoformat()
    role_dict = {
        "id": req.id,
        "display_name": req.display_name,
        "perspective": req.perspective,
        "expertise_domains": req.expertise_domains,
        "risk_appetite": req.risk_appetite,
        "default_stance": req.default_stance,
        "evidence_preference": req.evidence_preference,
        "model_override": req.model_override,
        "background_brief": req.background_brief,
        "prompt_template": req.prompt_template,
        "is_builtin": 0,
        "is_active": 1,
        "created_at": now,
        "updated_at": now,
    }
    await save_agent_role(role_dict)
    saved = await get_agent_role(req.id)
    return UpsertRoleResponse(role=AgentRole.from_db_row(saved or role_dict))


@router.put("/{role_id}", response_model=UpsertRoleResponse)
async def update_role(role_id: str, req: CreateRoleRequest) -> UpsertRoleResponse:
    """更新角色"""
    existing = await get_agent_role(role_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    now = datetime.now(timezone.utc).isoformat()
    role_dict = {
        "id": role_id,
        "display_name": req.display_name,
        "perspective": req.perspective,
        "expertise_domains": req.expertise_domains,
        "risk_appetite": req.risk_appetite,
        "default_stance": req.default_stance,
        "evidence_preference": req.evidence_preference,
        "model_override": req.model_override,
        "background_brief": req.background_brief,
        "prompt_template": req.prompt_template,
        "is_builtin": existing["is_builtin"],
        "is_active": existing["is_active"],
        "created_at": existing["created_at"],
        "updated_at": now,
    }
    await save_agent_role(role_dict)
    saved = await get_agent_role(role_id)
    return UpsertRoleResponse(role=AgentRole.from_db_row(saved or role_dict))


@router.delete("/{role_id}")
async def remove_role(role_id: str) -> dict[str, Any]:
    """删除角色"""
    deleted = await delete_agent_role(role_id)
    if not deleted:
        row = await get_agent_role(role_id)
        if row is None:
            raise HTTPException(status_code=404, detail="角色不存在")
        raise HTTPException(status_code=403, detail="内置角色不可删除")
    return {"role_id": role_id, "deleted": True}


@router.post("/generate", response_model=GenerateRolesResponse)
async def generate_roles(req: GenerateRolesRequest) -> GenerateRolesResponse:
    """根据议题自动生成角色阵容"""
    await _init_builtin_roles()

    from app.agents.llm import RealLLM
    from app.config import settings

    if not settings.use_real_llm:
        # 无 LLM 时返回内置角色兜底
        rows = await list_agent_roles(active_only=True)
        roles = [AgentRole.from_db_row(r) for r in rows]
        return GenerateRolesResponse(
            roles=roles,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    # 构建 prompt：要求 LLM 生成 2-3 个角色
    prompt = f"""根据以下议题，生成 2-3 个专业角色来参与辩论。每个角色应覆盖不同的专业视角。

议题：{req.topic}

要求：
1. 默认包含 2 个核心角色：product_architect（产品架构师）和 engineer（工程师）
2. 仅在议题明显涉及安全、数据、设计等特定领域时，才额外添加对应角色
3. 每个角色需包含：id（英文标识）、display_name（中文名）、perspective（核心视角）、
   expertise_domains（专业领域关键词列表）、risk_appetite（conservative/balanced/aggressive）、
   default_stance（默认立场）、evidence_preference（证据偏好）、
   background_brief（一句话背景介绍）、prompt_template（角色prompt）
4. 角色之间应有互补性，避免过度重叠

返回纯 JSON 数组，格式如下：
[{{"id":"...","display_name":"...","perspective":"...","expertise_domains":["..."],"risk_appetite":"...","default_stance":"...","evidence_preference":"...","background_brief":"...","prompt_template":"..."}}]
只返回 JSON 数组，不要其他内容。"""

    try:
        llm = RealLLM()
        result = await llm.complete(prompt)
        # RealLLM 无 schema_hint 时会把非 dict 结果包装为 {"result": ...}
        raw = result["result"] if isinstance(result, dict) and "result" in result and len(result) == 1 else result

        # 解析 LLM 返回的 JSON
        roles_data: Any
        if isinstance(raw, list):
            roles_data = raw
        elif isinstance(raw, str):
            raw = raw.strip()
            if raw.startswith("```"):
                lines = raw.split("\n")
                raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            roles_data = json.loads(raw)
        else:
            roles_data = raw

        if not isinstance(roles_data, list):
            raise ValueError("LLM 返回的不是数组")

        roles = []
        for r_data in roles_data[:5]:  # 最多 5 个
            role_id = r_data.get("id", f"gen-{uuid.uuid4().hex[:8]}")
            roles.append(
                AgentRole(
                    id=role_id,
                    display_name=r_data.get("display_name", "未知角色"),
                    perspective=r_data.get("perspective", ""),
                    expertise_domains=r_data.get("expertise_domains", []),
                    risk_appetite=r_data.get("risk_appetite", "balanced"),
                    default_stance=r_data.get("default_stance", ""),
                    evidence_preference=r_data.get("evidence_preference", "balanced"),
                    background_brief=r_data.get("background_brief", ""),
                    prompt_template=r_data.get("prompt_template", ""),
                )
            )

        return GenerateRolesResponse(
            roles=roles,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as e:
        import logging

        logging.getLogger("agent_roles").warning("角色生成失败，回退到内置角色: %s", e)
        rows = await list_agent_roles(active_only=True)
        roles = [AgentRole.from_db_row(r) for r in rows]
        return GenerateRolesResponse(
            roles=roles,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
