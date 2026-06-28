# §2 全部 Prompt 模板（字符串 + format 填充）
from __future__ import annotations

# ---------- 2.1 主持人 Clarify 阶段 ----------
MODERATOR_CLARIFY = """[系统] 你是 Conclave 会议主持人。职责是推进流程、澄清议题、识别冲突、维持规则。
风格：简洁、结构化、不臆断。

[阶段: Clarify]
输入议题：{topic}
上传资料摘要：{doc_summaries}
任务：
1. 用一句话复述议题，确认无歧义
2. 列出 3-5 个待澄清的关键问题
3. 建议团队组成（角色 + 立场）

输出 JSON: {{"clarified_topic": "...", "key_questions": ["..."], "team_config": [{{"role": "...", "stance": "..."}}]}}"""

# ---------- 2.2 产品/架构师 IntraTeam 阶段 ----------
ARCHITECT_INTRA = """[系统] 你是产品架构师。关注目标、用户价值、系统边界、接口约束。
决策偏置：先谈价值与约束，再谈实现；重证据引用；适度保守。

[阶段: IntraTeam]
议题：{clarified_topic}
你的立场：{stance}
任务：从产品与架构视角给出论点，每条论点须标注证据来源：
- [doc:section] 上传文档中的证据（强证据）
- [common_knowledge] 通用工程实践或行业常识（弱证据，需用户验证）
- [assumption] 基于当前信息的推理假设（最弱，需确认）

输出 JSON: {{"claims": [{{"claim": "...", "evidence_ref": "...", "type": "fact|assumption|constraint"}}]}}"""

# ---------- 2.3 工程师 IntraTeam 阶段 ----------
ENGINEER_INTRA = """[系统] 你是工程师，兼负 QA 视角。关注可行性、实现风险、测试边界。
决策偏置：先质疑可行性，再谈方案；重执行细节。

[阶段: IntraTeam]
议题：{clarified_topic}
你的立场：{stance}
任务：从工程可行性角度给出论点，标注风险等级与证据来源：
- [doc:section] 上传文档中的证据（强证据）
- [common_knowledge] 通用工程实践或行业常识（弱证据，需用户验证）
- [assumption] 基于当前信息的推理假设（最弱，需确认）

输出 JSON: {{"claims": [{{"claim": "...", "evidence_ref": "...", "risk_level": "low|medium|high", "type": "fact|assumption|constraint"}}]}}"""

# ---------- 2.4 跨队辩论阶段 ----------
CROSS_TEAM = """[阶段: CrossTeam]
各方队内结论：{team_conclusions}
任务：找出结论间的冲突点。冲突类型分为 factual（事实矛盾）、preference（取舍分歧）、scope（边界争议）。

输出 JSON: {{"conflicts": [{{"id": "...", "type": "factual|preference|scope", "summary": "...", "side_a": "...", "side_b": "..."}}]}}"""

# ---------- 2.5 证据对照阶段 ----------
EVIDENCE_CHECK = """[阶段: EvidenceCheck]
冲突点：{conflict}
检索证据：{evidence_chunks}
任务：逐条证据判断支持哪一方，或中立，或与冲突无关。

重要：证据的 strength 字段标注了证据强度：
- strength=strong：来自上传文档或网络检索的具体证据，应重点采信
- strength=weak：通用工程实践占位证据（source 以 common_knowledge 开头），仅作参考，不可单独作为裁决依据
- strength=none：无实质内容的占位，应判为 irrelevant

对于 strength=weak 的证据，请基于 side_a / side_b 论点本身的质量做倾向性判断，而非对占位文本判中立。

输出 JSON: {{"conflict_id": "...", "evidence_assessments": [{{"evidence_id": "...", "quote": "...", "source": "...", "supports": "a|b|neutral|irrelevant", "strength": "strong|weak|none"}}]}}"""

# ---------- 2.6 仲裁阶段 ----------
ARBITRATE = """[阶段: Arbitrate]
冲突与证据：{evidence_set}
任务：基于证据裁决每个冲突，给出采纳结论与驳回理由。

注意：若证据中 strength 全为 weak 或 none（无外部文档/网络证据），请基于双方论点本身的质量裁决，并在 rationale 中标注"无外部证据支持，置信度低"。

输出 JSON: {{"decisions": [{{"conflict_id": "...", "verdict": "a|b|compromise", "rationale": "..."}}], "adopted_claims": ["..."]}}"""

# ---------- 2.6 产出阶段 ----------
PRODUCE = """[阶段: Produce]
裁决结果：{decision_record}
任务：产出结构化 PRD 与 OpenAPI 片段。严格遵守给定 schema。

输出 JSON:
{{
  "prd": {{
    "title": "...", "goal": "...", "scope": "...",
    "assumptions": ["..."], "constraints": ["..."],
    "api_endpoints": ["..."], "open_questions": ["..."]
  }},
  "openapi": "<OpenAPI 3.0 YAML 片段>"
}}"""

# ---------- 产出阶段：设计文档 ----------
PRODUCE_DESIGN_DOC = """[阶段: Produce]
裁决结果：{decision_record}
任务：产出架构设计文档。严格遵守给定 schema。

输出 JSON:
{{
  "design_doc": {{
    "title": "...",
    "overview": "系统概述",
    "architecture": "架构设计（组件关系、分层、数据流）",
    "tech_stack": ["技术选型1", "技术选型2"],
    "data_model": "数据模型设计",
    "api_design": "接口设计概述",
    "deployment": "部署方案",
    "risks": ["风险1", "风险2"],
    "open_questions": ["遗留问题1"]
  }}
}}"""

# ---------- 产出阶段：综合文档 ----------
PRODUCE_COMPREHENSIVE = """[阶段: Produce]
裁决结果：{decision_record}
任务：产出综合设计文档，包含需求、系统设计、接口设计、数据模型四个部分。

输出 JSON:
{{
  "comprehensive": {{
    "title": "...",
    "requirements": {{
      "goal": "项目目标",
      "functional": ["功能需求1", "功能需求2"],
      "non_functional": ["非功能需求1"],
      "constraints": ["约束1"]
    }},
    "system_design": {{
      "architecture": "架构概述",
      "components": ["组件1: 职责描述", "组件2: 职责描述"],
      "data_flow": "数据流描述"
    }},
    "api_design": {{
      "endpoints": ["GET /api/resource - 描述", "POST /api/resource - 描述"],
      "auth": "认证方案",
      "error_handling": "错误处理策略"
    }},
    "data_model": {{
      "entities": ["实体1: 字段描述", "实体2: 字段描述"],
      "relationships": "实体关系",
      "storage": "存储方案"
    }}
  }}
}}"""

# ---------- 产出阶段：调研报告 ----------
PRODUCE_RESEARCH_REPORT = """[阶段: Produce]
裁决结果：{decision_record}
任务：产出调研报告，总结讨论中的发现和建议。

输出 JSON:
{{
  "research_report": {{
    "title": "...",
    "summary": "摘要",
    "findings": [
      {{"topic": "发现1", "detail": "详细描述", "source": "来源"}}
    ],
    "analysis": "分析结论",
    "recommendations": ["建议1", "建议2"],
    "references": ["引用1", "引用2"]
  }}
}}"""

# ---------- 产出阶段：商业报告 ----------
PRODUCE_BUSINESS_REPORT = """[阶段: Produce]
裁决结果：{decision_record}
任务：产出商业报告，面向决策层。

输出 JSON:
{{
  "business_report": {{
    "title": "...",
    "executive_summary": "执行摘要",
    "market_analysis": "市场分析",
    "financial_projection": "财务预测",
    "risk_assessment": "风险评估",
    "strategic_recommendation": "战略建议",
    "next_steps": ["下一步1", "下一步2"]
  }}
}}"""

# ---------- 产出阶段：代码分析 ----------
PRODUCE_CODE_ANALYSIS = """[阶段: Produce]
裁决结果：{decision_record}
任务：基于讨论结论，生成 PRD 文档 + OpenAPI 摘要 + Python 数据分析代码。代码将在沙箱中执行，结果会回填到报告中。

输出 JSON:
{{
  "prd": {{
    "title": "...",
    "goal": "目标说明",
    "scope": "范围说明",
    "assumptions": ["假设1"],
    "constraints": ["约束1"],
    "api_endpoints": ["GET /api/..."],
    "open_questions": ["待解决问题"]
  }},
  "openapi": "openapi: 3.0.0\\ninfo: ...",
  "code_analysis": {{
    "title": "...",
    "description": "分析目的说明",
    "code": "完整的 Python 代码（可直接执行，可用 pandas/numpy/matplotlib）",
    "expected_output": "预期输出说明"
  }}
}}"""

# ---------- 产出阶段：测试系统 ----------
PRODUCE_TESTED_SYSTEM = """[阶段: Produce]
裁决结果：{decision_record}
任务：基于讨论结论，生成 PRD 文档 + OpenAPI 摘要 + 完整的 Python 代码和对应的 pytest 测试。代码将在沙箱中执行测试。

输出 JSON:
{{
  "prd": {{
    "title": "...",
    "goal": "目标说明",
    "scope": "范围说明",
    "assumptions": ["假设1"],
    "constraints": ["约束1"],
    "api_endpoints": ["GET /api/..."],
    "open_questions": ["待解决问题"]
  }},
  "openapi": "openapi: 3.0.0\\ninfo: ...",
  "tested_system": {{
    "title": "...",
    "description": "系统说明",
    "main_code": "主代码（可被 import 的模块）",
    "test_code": "pytest 测试代码",
    "run_command": "python -m pytest test_code.py -v"
  }}
}}"""

# ---------- 产出阶段：可部署服务 ----------
PRODUCE_DEPLOYABLE_SERVICE = """[阶段: Produce]
裁决结果：{decision_record}
任务：基于讨论结论，生成 PRD 文档 + OpenAPI 摘要 + 可直接部署的完整服务。包含应用代码、Dockerfile 和 docker-compose.yml。
要求：
1. 应用代码应是一个完整的可运行 Web 服务（如 FastAPI/Flask 应用）
2. Dockerfile 基于 python:3.12-slim，安装依赖，暴露端口
3. docker-compose.yml 定义服务，映射端口，挂载数据卷
4. 包含 requirements.txt 依赖清单

输出 JSON:
{{
  "prd": {{
    "title": "...",
    "goal": "目标说明",
    "scope": "范围说明",
    "assumptions": ["假设1"],
    "constraints": ["约束1"],
    "api_endpoints": ["GET /api/..."],
    "open_questions": ["待解决问题"]
  }},
  "openapi": "openapi: 3.0.0\\ninfo: ...",
  "deployable_service": {{
    "title": "...",
    "description": "服务说明",
    "app_code": "完整的 Python 应用代码（FastAPI/Flask，可直接运行）",
    "requirements_txt": "依赖清单（每行一个包名==版本）",
    "dockerfile": "Dockerfile 内容",
    "docker_compose": "docker-compose.yml 内容",
    "port": 8000,
    "run_command": "uvicorn app:main --host 0.0.0.0 --port 8000"
  }}
}}"""

# 产出模板映射
PRODUCE_TEMPLATES = {
    "prd_openapi": PRODUCE,
    "design_doc": PRODUCE_DESIGN_DOC,
    "comprehensive": PRODUCE_COMPREHENSIVE,
    "research_report": PRODUCE_RESEARCH_REPORT,
    "business_report": PRODUCE_BUSINESS_REPORT,
    "code_analysis": PRODUCE_CODE_ANALYSIS,
    "tested_system": PRODUCE_TESTED_SYSTEM,
    "deployable_service": PRODUCE_DEPLOYABLE_SERVICE,
}


def get_produce_template(deliverable_type: str) -> str:
    """根据产出类型获取对应的 produce prompt 模板"""
    return PRODUCE_TEMPLATES.get(deliverable_type, PRODUCE)


def render(template: str, **kwargs) -> str:
    """安全填充 Prompt 模板，缺省字段填空串避免 KeyError"""
    from string import Formatter

    fields = {f[1] for f in Formatter().parse(template) if f[1]}
    safe = {k: kwargs.get(k, "") for k in fields}
    return template.format(**safe)
