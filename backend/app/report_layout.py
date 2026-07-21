"""报告布局规范 (Report Layout Spec)

后端根据 deliverable_type 生成 layout spec，前端按 spec 通用渲染。
前端不再硬编码模板，所有章节结构、组件类型、字段映射由后端驱动。

Schema 结构:
{
  "type": "research_report",          # 产出类型
  "title": "研究报告标题",              # 报告标题（可被前端覆盖）
  "subtitle": "副标题",                 # 报告副标题
  "sections": [                        # 有序章节列表
    {
      "id": "summary",                 # 章节唯一标识（用于锚点跳转）
      "title": "执行摘要",              # 章节标题
      "icon": "summary",               # 可选：章节图标标识
      "blocks": [                      # 章节内的内容块（有序）
        {
          "type": "paragraph",         # 块类型：见 SUPPORTED_BLOCK_TYPES
          "data": {
            "text": "摘要内容..."
          }
        },
        {
          "type": "list",
          "data": {
            "items": ["项1", "项2"],
            "ordered": false           # 是否有序列表
          }
        },
        {
          "type": "findings",          # 研究发现卡片组
          "data": {
            "items": [
              {"num": "01", "topic": "...", "detail": "...", "trace": {...}, "sources": [...]}
            ]
          }
        },
        {
          "type": "code",
          "data": {
            "code": "...",
            "lang": "PYTHON"            # PYTHON | YAML | DOCKER | JSON | BASH
          }
        },
        {
          "type": "api_table",          # RESTful API 端点表格
          "data": {
            "endpoints": ["GET /api/users - 获取用户列表", "POST /api/users - 创建用户"]
          }
        },
        {
          "type": "kpi_grid",           # 关键指标卡片网格
          "data": {
            "items": [{"label": "...", "value": "...", "unit": "...", "trend": "..."}]
          }
        },
        {
          "type": "conflicts",          # 冲突与裁决卡片
          "data": {
            "items": [{"summary": "...", "sideA": "...", "sideB": "...", "verdict": "a|b|compromise", "rationale": "...", "trace": {...}}]
          }
        },
        {
          "type": "risks",              # 风险评估列表
          "data": {
            "items": [{"level": "high|mid|low", "desc": "..."}]
          }
        },
        {
          "type": "timeline",           # 时间线
          "data": {
            "items": [{"date": "...", "text": "..."}]
          }
        },
        {
          "type": "data_model",          # 数据模型实体
          "data": {
            "entities": [{"entity": "...", "fields": ["id [PK]", "name"]}]
          }
        },
        {
          "type": "test_groups",         # 测试用例分组
          "data": {
            "tests": [{"name": "test_register_...", "result": "pass|fail", "time": "0.12s"}]
          }
        },
        {
          "type": "file_tree",           # 文件树
          "data": {
            "items": [{"name": "...", "type": "dir|file", "indent": 0}]
          }
        },
        {
          "type": "field",               # 单字段键值对
          "data": {
            "label": "title",
            "value": "..."
          }
        },
        {
          "type": "team_config",         # 团队配置
          "data": {
            "items": [{"role": "...", "stance": "..."}]
          }
        },
        {
          "type": "attachments",          # 附件列表
          "data": {
            "items": [{"filename": "...", "size": 12345}]
          }
        }
      ]
    }
  ],
  "meta": {                             # 可选：元信息
    "meeting_id": "...",
    "status": "done",
    "generated_at": "2026-07-16T15:08:00Z"
  },
  "confidence": {                       # 可选：阶段置信度
    "clarify": "high",
    "discuss": "high",
    ...
  }
}

支持的 block 类型 (SUPPORTED_BLOCK_TYPES):
  paragraph    - 段落文本
  list         - 列表（有序/无序）
  findings     - 研究发现卡片组
  code         - 代码块（带语法高亮）
  api_table    - RESTful API 端点表格
  kpi_grid     - 关键指标卡片网格
  conflicts    - 冲突与裁决卡片
  risks        - 风险评估列表
  timeline    - 时间线
  data_model   - 数据模型实体
  test_groups  - 测试用例分组
  file_tree    - 文件树
  field        - 单字段键值对
  team_config  - 团队配置
  attachments  - 附件列表
  raw          - 原始文本（Markdown 等待前端处理）
"""

from __future__ import annotations

from typing import Any

SUPPORTED_BLOCK_TYPES = frozenset(
    {
        "paragraph",
        "list",
        "findings",
        "code",
        "api_table",
        "kpi_grid",
        "conflicts",
        "risks",
        "timeline",
        "data_model",
        "test_groups",
        "file_tree",
        "field",
        "team_config",
        "attachments",
        "raw",
    }
)


def build_report_layout(
    deliverable_type: str,
    artifact: dict[str, Any],
    meeting_meta: dict[str, Any] | None = None,
    confidence: dict[str, str] | None = None,
    decisions: list[dict] | None = None,
    adopted_claims: list[str] | None = None,
    key_questions: list[str] | None = None,
    team_config: list[dict] | None = None,
    conflicts: list[dict] | None = None,
    llm_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """根据产出类型和 artifact 数据，构建前端可通用渲染的 report layout spec。

    参数:
        deliverable_type: 9 种产出类型之一
        artifact: produce 阶段产出的原始 artifact dict
        meeting_meta: 会议元信息 (meeting_id, status, generated_at, topic)
        confidence: 各阶段置信度
        decisions: 仲裁决策记录
        adopted_claims: 采纳主张列表
        key_questions: 关键问题列表
        team_config: 团队配置列表
        conflicts: 冲突列表
        llm_trace: LLM 调用追踪信息

    返回:
        完整的 report layout spec dict
    """
    builder = _LAYOUT_BUILDERS.get(deliverable_type)
    if builder is None:
        builder = _build_generic_layout

    layout = builder(
        artifact,
        {
            "meeting_meta": meeting_meta or {},
            "confidence": confidence or {},
            "decisions": decisions or [],
            "adopted_claims": adopted_claims or [],
            "key_questions": key_questions or [],
            "team_config": team_config or [],
            "conflicts": conflicts or [],
            "llm_trace": llm_trace or {},
        },
    )

    layout["type"] = deliverable_type
    layout.setdefault("sections", [])
    return layout


# ─── 通用回退布局 ───
def _build_generic_layout(artifact: dict, ctx: dict) -> dict:
    """未知类型的通用回退：遍历 artifact 所有 key，每个 key 作为一个章节"""
    sections = []
    for key, value in artifact.items():
        if key in ("execution", "refine_info", "net_auth", "deployment_dir", "deployment", "review"):
            continue
        if isinstance(value, dict):
            blocks = []
            for field, val in value.items():
                if isinstance(val, str):
                    blocks.append({"type": "field", "data": {"label": field, "value": val}})
                elif isinstance(val, list):
                    blocks.append({"type": "list", "data": {"items": [str(v) for v in val], "ordered": False}})
                elif isinstance(val, dict):
                    blocks.append({"type": "raw", "data": {"text": str(val)}})
            sections.append({"id": key, "title": key.replace("_", " ").title(), "blocks": blocks})
        elif isinstance(value, str) and len(value) > 100:
            sections.append(
                {
                    "id": key,
                    "title": key.replace("_", " ").title(),
                    "blocks": [{"type": "code", "data": {"code": value, "lang": "TEXT"}}],
                }
            )

    _append_appendix_section(sections, ctx)
    return {"title": artifact.get("title", "未命名报告"), "subtitle": "", "sections": sections}


# ─── prd_openapi ───
def _build_prd_openapi_layout(artifact: dict, ctx: dict) -> dict:
    prd = artifact.get("prd", {})
    meta = ctx["meeting_meta"]
    sections = [
        {
            "id": "summary",
            "title": "执行摘要",
            "blocks": [
                {"type": "paragraph", "data": {"text": prd.get("goal", "")}},
                {"type": "list", "data": {"items": ctx["adopted_claims"], "ordered": False}},
            ],
        },
        {
            "id": "key_questions",
            "title": "关键问题",
            "blocks": [
                {"type": "list", "data": {"items": ctx["key_questions"], "ordered": True}},
            ],
        },
        {
            "id": "team_config",
            "title": "团队配置",
            "blocks": [
                {"type": "team_config", "data": {"items": ctx["team_config"]}},
            ],
        },
        {
            "id": "conflicts",
            "title": "冲突与裁决",
            "blocks": [
                {"type": "conflicts", "data": {"items": _enrich_conflicts(ctx["conflicts"], ctx["decisions"])}},
            ],
        },
        {
            "id": "prd",
            "title": "最终产出 — PRD",
            "blocks": [
                {"type": "field", "data": {"label": "title", "value": prd.get("title", "")}},
                {"type": "field", "data": {"label": "goal", "value": prd.get("goal", "")}},
                {"type": "field", "data": {"label": "scope", "value": prd.get("scope", "")}},
                {
                    "type": "list",
                    "data": {"items": prd.get("assumptions", []), "ordered": False},
                },
                {
                    "type": "list",
                    "data": {"items": prd.get("constraints", []), "ordered": False},
                },
                {"type": "api_table", "data": {"endpoints": prd.get("api_endpoints", [])}},
                {"type": "list", "data": {"items": prd.get("open_questions", []), "ordered": False}},
            ],
        },
        {
            "id": "openapi",
            "title": "OpenAPI 规范",
            "blocks": [
                {"type": "code", "data": {"code": artifact.get("openapi", ""), "lang": "YAML"}},
            ],
        },
        {
            "id": "attachments",
            "title": "附件",
            "blocks": [
                {"type": "attachments", "data": {"items": artifact.get("attachments", [])}},
            ],
        },
    ]
    _append_appendix_section(sections, ctx)
    return {"title": prd.get("title", ""), "subtitle": meta.get("topic", ""), "sections": sections}


# ─── research_report ───
def _build_research_report_layout(artifact: dict, ctx: dict) -> dict:
    r = artifact.get("research_report", {})
    meta = ctx["meeting_meta"]
    findings = r.get("findings", [])
    finding_items = [
        {
            "num": f"{i + 1:02d}",
            "topic": f.get("topic", ""),
            "detail": f.get("detail", ""),
            "trace": f.get("trace"),
            "sources": [f.get("source", "")] if f.get("source") else [],
        }
        for i, f in enumerate(findings)
    ]
    sections = [
        {
            "id": "summary",
            "title": "执行摘要",
            "blocks": [
                {"type": "paragraph", "data": {"text": r.get("summary", "")}},
                {"type": "list", "data": {"items": ctx["adopted_claims"], "ordered": False}},
            ],
        },
        {
            "id": "findings",
            "title": "研究发现",
            "blocks": [{"type": "findings", "data": {"items": finding_items}}],
        },
        {
            "id": "analysis",
            "title": "分析",
            "blocks": [
                {"type": "paragraph", "data": {"text": r.get("analysis", "")}},
            ],
        },
        {
            "id": "recommendations",
            "title": "建议",
            "blocks": [
                {"type": "list", "data": {"items": r.get("recommendations", []), "ordered": True}},
            ],
        },
        {
            "id": "attachments",
            "title": "附件",
            "blocks": [
                {"type": "attachments", "data": {"items": artifact.get("attachments", [])}},
            ],
        },
    ]
    _append_appendix_section(sections, ctx)
    return {"title": r.get("title", ""), "subtitle": meta.get("topic", ""), "sections": sections}


# ─── business_report ───
def _build_business_report_layout(artifact: dict, ctx: dict) -> dict:
    r = artifact.get("business_report", {})
    meta = ctx["meeting_meta"]
    sections = [
        {
            "id": "summary",
            "title": "执行摘要",
            "blocks": [
                {"type": "paragraph", "data": {"text": r.get("executive_summary", "")}},
            ],
        },
        {
            "id": "market_analysis",
            "title": "市场分析",
            "blocks": [
                {"type": "paragraph", "data": {"text": r.get("market_analysis", "")}},
            ],
        },
        {
            "id": "financial_projection",
            "title": "财务预测",
            "blocks": [
                {"type": "paragraph", "data": {"text": r.get("financial_projection", "")}},
            ],
        },
        {
            "id": "risk_assessment",
            "title": "风险评估",
            "blocks": [
                {"type": "risks", "data": {"items": _parse_risks_from_text(r.get("risk_assessment", ""))}},
            ],
        },
        {
            "id": "strategic_recommendation",
            "title": "战略建议",
            "blocks": [
                {"type": "paragraph", "data": {"text": r.get("strategic_recommendation", "")}},
            ],
        },
        {
            "id": "next_steps",
            "title": "下一步行动",
            "blocks": [
                {"type": "list", "data": {"items": r.get("next_steps", []), "ordered": True}},
            ],
        },
    ]
    _append_appendix_section(sections, ctx)
    return {"title": r.get("title", ""), "subtitle": meta.get("topic", ""), "sections": sections}


# ─── comprehensive ───
def _build_comprehensive_layout(artifact: dict, ctx: dict) -> dict:
    c = artifact.get("comprehensive", {})
    meta = ctx["meeting_meta"]
    req = c.get("requirements", {})
    sd = c.get("system_design", {})
    api = c.get("api_design", {})
    dm = c.get("data_model", {})
    sections = [
        {
            "id": "requirements",
            "title": "需求",
            "blocks": [
                {"type": "field", "data": {"label": "目标", "value": req.get("goal", "")}},
                {"type": "list", "data": {"items": req.get("functional", []), "ordered": False}},
                {"type": "list", "data": {"items": req.get("non_functional", []), "ordered": False}},
                {"type": "list", "data": {"items": req.get("constraints", []), "ordered": False}},
            ],
        },
        {
            "id": "system_design",
            "title": "系统设计",
            "blocks": [
                {"type": "paragraph", "data": {"text": sd.get("architecture", "")}},
                {"type": "list", "data": {"items": sd.get("components", []), "ordered": False}},
                {"type": "paragraph", "data": {"text": sd.get("data_flow", "")}},
            ],
        },
        {
            "id": "data_model",
            "title": "数据模型",
            "blocks": [
                {"type": "data_model", "data": {"entities": _parse_entities(dm.get("entities", []))}},
                {"type": "paragraph", "data": {"text": dm.get("relationships", "")}},
                {"type": "field", "data": {"label": "存储方案", "value": dm.get("storage", "")}},
            ],
        },
        {
            "id": "api_design",
            "title": "API 规范",
            "blocks": [
                {"type": "api_table", "data": {"endpoints": api.get("endpoints", [])}},
                {"type": "field", "data": {"label": "认证方案", "value": api.get("auth", "")}},
                {"type": "field", "data": {"label": "错误处理", "value": api.get("error_handling", "")}},
            ],
        },
        {
            "id": "attachments",
            "title": "附件",
            "blocks": [
                {"type": "attachments", "data": {"items": artifact.get("attachments", [])}},
            ],
        },
    ]
    _append_appendix_section(sections, ctx)
    return {"title": c.get("title", ""), "subtitle": meta.get("topic", ""), "sections": sections}


# ─── design_doc ───
def _build_design_doc_layout(artifact: dict, ctx: dict) -> dict:
    d = artifact.get("design_doc", {})
    meta = ctx["meeting_meta"]
    sections = [
        {
            "id": "overview",
            "title": "系统概述",
            "blocks": [{"type": "paragraph", "data": {"text": d.get("overview", "")}}],
        },
        {
            "id": "architecture",
            "title": "架构设计",
            "blocks": [{"type": "paragraph", "data": {"text": d.get("architecture", "")}}],
        },
        {
            "id": "tech_stack",
            "title": "技术选型",
            "blocks": [{"type": "list", "data": {"items": d.get("tech_stack", []), "ordered": False}}],
        },
        {
            "id": "data_model",
            "title": "数据模型",
            "blocks": [{"type": "paragraph", "data": {"text": d.get("data_model", "")}}],
        },
        {
            "id": "api_design",
            "title": "接口设计",
            "blocks": [{"type": "paragraph", "data": {"text": d.get("api_design", "")}}],
        },
        {
            "id": "deployment",
            "title": "部署方案",
            "blocks": [{"type": "paragraph", "data": {"text": d.get("deployment", "")}}],
        },
        {
            "id": "risks",
            "title": "风险",
            "blocks": [{"type": "risks", "data": {"items": _parse_risks_from_list(d.get("risks", []))}}],
        },
        {
            "id": "open_questions",
            "title": "遗留问题",
            "blocks": [{"type": "list", "data": {"items": d.get("open_questions", []), "ordered": False}}],
        },
    ]
    _append_appendix_section(sections, ctx)
    return {"title": d.get("title", ""), "subtitle": meta.get("topic", ""), "sections": sections}


# ─── code_analysis ───
def _build_code_analysis_layout(artifact: dict, ctx: dict) -> dict:
    prd = artifact.get("prd", {})
    ca = artifact.get("code_analysis", {})
    exec_result = artifact.get("execution", {})
    meta = ctx["meeting_meta"]
    sections = [
        {
            "id": "summary",
            "title": "执行摘要",
            "blocks": [
                {"type": "field", "data": {"label": "title", "value": prd.get("title", "")}},
                {"type": "paragraph", "data": {"text": prd.get("goal", "")}},
            ],
        },
        {
            "id": "analysis_description",
            "title": "分析说明",
            "blocks": [
                {"type": "field", "data": {"label": "title", "value": ca.get("title", "")}},
                {"type": "paragraph", "data": {"text": ca.get("description", "")}},
            ],
        },
        {
            "id": "code",
            "title": "分析代码",
            "blocks": [
                {"type": "code", "data": {"code": ca.get("code", ""), "lang": "PYTHON"}},
            ],
        },
        {
            "id": "expected_output",
            "title": "预期输出",
            "blocks": [
                {"type": "paragraph", "data": {"text": ca.get("expected_output", "")}},
            ],
        },
    ]
    if exec_result:
        sections.append(
            {
                "id": "execution",
                "title": "执行结果",
                "blocks": _build_execution_blocks(exec_result),
            }
        )
    _append_appendix_section(sections, ctx)
    return {"title": prd.get("title", ca.get("title", "")), "subtitle": meta.get("topic", ""), "sections": sections}


# ─── data_science ───
def _build_data_science_layout(artifact: dict, ctx: dict) -> dict:
    prd = artifact.get("prd", {})
    ca = artifact.get("code_analysis", {})
    exec_result = artifact.get("execution", {})
    meta = ctx["meeting_meta"]
    sections = [
        {
            "id": "summary",
            "title": "分析目标",
            "blocks": [
                {"type": "field", "data": {"label": "title", "value": prd.get("title", "")}},
                {"type": "paragraph", "data": {"text": prd.get("goal", "")}},
                {"type": "paragraph", "data": {"text": prd.get("scope", "")}},
            ],
        },
        {
            "id": "methodology",
            "title": "方法论",
            "blocks": [
                {"type": "paragraph", "data": {"text": ca.get("description", "")}},
            ],
        },
        {
            "id": "code",
            "title": "分析代码",
            "blocks": [
                {"type": "code", "data": {"code": ca.get("code", ""), "lang": "PYTHON"}},
            ],
        },
    ]
    if exec_result:
        sections.append(
            {
                "id": "execution",
                "title": "执行结果",
                "blocks": _build_execution_blocks(exec_result),
            }
        )
    _append_appendix_section(sections, ctx)
    return {"title": prd.get("title", ca.get("title", "")), "subtitle": meta.get("topic", ""), "sections": sections}


# ─── tested_system ───
def _build_tested_system_layout(artifact: dict, ctx: dict) -> dict:
    prd = artifact.get("prd", {})
    ts = artifact.get("tested_system", {})
    exec_result = artifact.get("execution", {})
    meta = ctx["meeting_meta"]
    sections = [
        {
            "id": "summary",
            "title": "系统说明",
            "blocks": [
                {"type": "field", "data": {"label": "title", "value": ts.get("title", prd.get("title", ""))}},
                {"type": "paragraph", "data": {"text": ts.get("description", "")}},
            ],
        },
        {
            "id": "prd",
            "title": "PRD",
            "blocks": [
                {"type": "field", "data": {"label": "goal", "value": prd.get("goal", "")}},
                {"type": "field", "data": {"label": "scope", "value": prd.get("scope", "")}},
                {"type": "api_table", "data": {"endpoints": prd.get("api_endpoints", [])}},
            ],
        },
        {
            "id": "main_code",
            "title": "主代码",
            "blocks": [
                {"type": "code", "data": {"code": ts.get("main_code", ""), "lang": "PYTHON"}},
            ],
        },
        {
            "id": "test_code",
            "title": "测试代码",
            "blocks": [
                {"type": "code", "data": {"code": ts.get("test_code", ""), "lang": "PYTHON"}},
            ],
        },
        {
            "id": "run_command",
            "title": "运行命令",
            "blocks": [
                {"type": "code", "data": {"code": ts.get("run_command", ""), "lang": "BASH"}},
            ],
        },
    ]
    if exec_result:
        sections.append(
            {
                "id": "test_results",
                "title": "测试结果",
                "blocks": _build_test_result_blocks(exec_result),
            }
        )
    _append_appendix_section(sections, ctx)
    return {"title": ts.get("title", prd.get("title", "")), "subtitle": meta.get("topic", ""), "sections": sections}


# ─── deployable_service ───
def _build_deployable_service_layout(artifact: dict, ctx: dict) -> dict:
    prd = artifact.get("prd", {})
    ds = artifact.get("deployable_service", {})
    review = artifact.get("review", {})
    deployment = artifact.get("deployment", {})
    exec_result = artifact.get("execution", {})
    meta = ctx["meeting_meta"]
    sections = [
        {
            "id": "service_viewer",
            "title": "代码预览",
            "blocks": [
                {
                    "type": "service_viewer",
                    "data": {
                        "title": ds.get("title", prd.get("title", "")),
                        "port": ds.get("port", 8000),
                        "run_command": ds.get("run_command", ""),
                        "app_code": ds.get("static_files") or ds.get("app_code", ""),
                        "file_count": ds.get("phased_generation", {}).get("file_count", 0),
                        "complexity": ds.get("complexity_level", ""),
                    },
                }
            ],
        },
        {
            "id": "deploy_status",
            "title": "部署状态",
            "blocks": _build_deploy_status_blocks(deployment, exec_result),
        },
        {
            "id": "prd",
            "title": "PRD",
            "blocks": [
                {"type": "field", "data": {"label": "title", "value": prd.get("title", "")}},
                {"type": "field", "data": {"label": "goal", "value": prd.get("goal", "")}},
                {"type": "field", "data": {"label": "scope", "value": prd.get("scope", "")}},
                {"type": "api_table", "data": {"endpoints": prd.get("api_endpoints", [])}},
            ],
        },
        {
            "id": "code_structure",
            "title": "代码结构",
            "blocks": [
                {"type": "file_tree", "data": {"items": _parse_file_tree(ds.get("file_tree", []))}},
            ],
        },
    ]
    if review:
        sections.append(
            {
                "id": "code_review",
                "title": "代码审查",
                "blocks": [
                    {"type": "field", "data": {"label": "结果", "value": review.get("result", "")}},
                    {"type": "list", "data": {"items": review.get("issues", []), "ordered": False}},
                ],
            }
        )
    if exec_result and "tests" in str(exec_result):
        sections.append(
            {
                "id": "test_results",
                "title": "测试结果",
                "blocks": _build_test_result_blocks(exec_result),
            }
        )
    if ds.get("dockerfile"):
        sections.append(
            {
                "id": "dockerfile",
                "title": "Dockerfile",
                "blocks": [{"type": "code", "data": {"code": ds.get("dockerfile", ""), "lang": "DOCKER"}}],
            }
        )
    if ds.get("docker_compose"):
        sections.append(
            {
                "id": "docker_compose",
                "title": "docker-compose.yml",
                "blocks": [{"type": "code", "data": {"code": ds.get("docker_compose", ""), "lang": "YAML"}}],
            }
        )
    _append_appendix_section(sections, ctx)
    return {"title": prd.get("title", ""), "subtitle": meta.get("topic", ""), "sections": sections}


# ─── 辅助函数 ───
def _append_appendix_section(sections: list, ctx: dict) -> None:
    """添加附录章节（执行追踪）"""
    trace = ctx.get("llm_trace", {})
    if not trace:
        return
    sections.append(
        {
            "id": "appendix",
            "title": "附录",
            "blocks": [
                {"type": "field", "data": {"label": "LLM 调用次数", "value": str(trace.get("total_calls", "—"))}},
                {"type": "field", "data": {"label": "成功率", "value": trace.get("success_rate", "—")}},
                {"type": "field", "data": {"label": "总 Token", "value": str(trace.get("total_tokens", "—"))}},
            ],
        }
    )


def _enrich_conflicts(conflicts: list, decisions: list) -> list:
    """为冲突列表补充裁决理由"""
    decision_map = {d.get("conflict_id"): d for d in decisions}
    result = []
    for i, c in enumerate(conflicts):
        cid = c.get("id", f"conflict-{i}")
        dec = decision_map.get(cid, {})
        result.append(
            {
                "summary": c.get("summary", ""),
                "sideA": c.get("side_a", c.get("sideA", "")),
                "sideB": c.get("side_b", c.get("sideB", "")),
                "verdict": c.get("verdict", "compromise"),
                "rationale": dec.get("rationale", c.get("rationale", "")),
                "trace": c.get("trace"),
            }
        )
    return result


def _parse_risks_from_text(text: str) -> list:
    """从风险评估文本中解析风险项"""
    if not text:
        return []
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    risks = []
    for line in lines:
        level = "mid"
        lower = line.lower()
        if any(w in lower for w in ["高", "high", "严重", "critical"]):
            level = "high"
        elif any(w in lower for w in ["低", "low", "轻微", "minor"]):
            level = "low"
        risks.append({"level": level, "desc": line})
    return risks if risks else [{"level": "mid", "desc": text}]


def _parse_risks_from_list(items: list) -> list:
    """从风险列表中解析风险项"""
    return [{"level": "mid", "desc": str(item)} for item in items]


def _parse_entities(entities: list) -> list[dict[str, Any]]:
    """解析数据模型实体"""
    result: list[dict[str, Any]] = []
    for e in entities:
        if isinstance(e, str):
            parts = e.split(":", 1)
            name = parts[0].strip()
            fields = [f.strip() for f in parts[1].split(",")] if len(parts) > 1 else []
            result.append({"entity": name, "fields": fields})
        elif isinstance(e, dict):
            result.append(
                {
                    "entity": str(e.get("entity", e.get("name", ""))),
                    "fields": e.get("fields", []),
                }
            )
    return result


def _parse_file_tree(items: list) -> list:
    """解析文件树"""
    if not items:
        return []
    result = []
    for item in items:
        if isinstance(item, dict):
            result.append(
                {
                    "name": item.get("name", ""),
                    "type": item.get("type", "file"),
                    "indent": item.get("indent", item.get("level", 0)),
                }
            )
        elif isinstance(item, str):
            indent = len(item) - len(item.lstrip())
            name = item.strip()
            result.append({"name": name, "type": "dir" if name.endswith("/") else "file", "indent": indent // 2})
    return result


def _build_execution_blocks(exec_result: dict) -> list:
    """构建执行结果块"""
    blocks = []
    if exec_result.get("stdout"):
        blocks.append({"type": "code", "data": {"code": exec_result["stdout"], "lang": "TEXT"}})
    if exec_result.get("stderr"):
        blocks.append({"type": "code", "data": {"code": exec_result["stderr"], "lang": "TEXT"}})
    if exec_result.get("exit_code") is not None:
        blocks.append({"type": "field", "data": {"label": "退出码", "value": str(exec_result["exit_code"])}})
    if not blocks:
        blocks.append({"type": "raw", "data": {"text": str(exec_result)}})
    return blocks


def _build_test_result_blocks(exec_result: dict) -> list:
    """构建测试结果块"""
    blocks = []
    tests = exec_result.get("tests", [])
    if tests:
        blocks.append({"type": "test_groups", "data": {"tests": tests}})
    else:
        stdout = exec_result.get("stdout", "")
        if stdout:
            blocks.append({"type": "code", "data": {"code": stdout, "lang": "TEXT"}})
    summary = exec_result.get("summary", "")
    if summary:
        blocks.append({"type": "paragraph", "data": {"text": summary}})
    if not blocks:
        blocks.append({"type": "raw", "data": {"text": str(exec_result)}})
    return blocks


def _build_deploy_status_blocks(deployment: dict, exec_result: dict) -> list:
    """构建部署状态块"""
    blocks = []
    if deployment:
        blocks.append({"type": "field", "data": {"label": "服务地址", "value": deployment.get("access_url", "—")}})
        blocks.append(
            {
                "type": "field",
                "data": {"label": "部署状态", "value": "健康运行中" if deployment.get("ok") else "部署失败"},
            }
        )
        blocks.append({"type": "field", "data": {"label": "部署时间", "value": deployment.get("deployed_at", "—")}})
    else:
        blocks.append({"type": "paragraph", "data": {"text": "部署信息不可用"}})
    return blocks


# ─── 类型 → 布局构建器注册表 ───
_LAYOUT_BUILDERS: dict[str, Any] = {
    "prd_openapi": _build_prd_openapi_layout,
    "research_report": _build_research_report_layout,
    "business_report": _build_business_report_layout,
    "comprehensive": _build_comprehensive_layout,
    "design_doc": _build_design_doc_layout,
    "code_analysis": _build_code_analysis_layout,
    "data_science": _build_data_science_layout,
    "tested_system": _build_tested_system_layout,
    "deployable_service": _build_deployable_service_layout,
}
