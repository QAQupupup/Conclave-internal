# Conclave 多 Agent 技能生态系统调研报告

> 调研日期：2026-08-04
> 调研范围：职业人格类 Agent 角色定义、开源 Skill/Plugin 生态系统、Conclave 现有技能体系、集成建议与优先级路线图

---

## 执行摘要

本报告对 AI 多 Agent 会议/协作框架中的技能（Skill）生态进行了系统性调研，覆盖 16 个开源/商业平台的技能模式与 14 类职业人格角色定义。核心发现如下：

1. **Conclave 现有技能体系已具备良好的框架基础**：7 个 YAML 格式的会议内 Skill + 7 个四维画像角色，采用按需加载、优先级排序、上下文感知匹配的架构，与主流平台（CrewAI、Claude Code Skills、Cursor Rules）的设计哲学一致。

2. **人格类 Skill 是当前最大缺口**：现有 7 个角色（主持人、产品架构师、工程师、安全专家、数据工程师、UX设计师、市场专家）仅覆盖了技术产品开发场景，缺少秘书/行政助理、商业分析师、研究员、项目经理、技术文档工程师、QA工程师、DevOps工程师、法务合规、财务分析师等高频协作角色。

3. **开源生态中可借鉴的模式**：
   - **CrewAI** 的 role-goal-backstory 三元组定义模式
   - **Roo Code/Cline** 的自定义 Mode 系统（roleDefinition + whenToUse + customInstructions + tool groups）
   - **Claude Code** 的 Markdown 文件即 Skill 的轻量模式
   - **GitHub Copilot** 的 `.github/skills/*.md` + YAML frontmatter 规范
   - **MCP 协议** 的工具/资源/Prompt 三层标准化接口
   - **LangGraph** 的 Supervisor/Hierarchical 多 Agent 编排模式

4. **推荐优先级**：P0（立即实现）——秘书、项目经理、QA工程师、技术文档工程师；P1（近期实现）——商业分析师、研究员、DevOps工程师、法务合规；P2（按需扩展）——UX研究员、数据科学家、财务分析师、营销专家增强、设计师。

---

## 一、Conclave 现有技能清单

### 1.1 会议内 Skill（YAML 格式，运行时自动加载）

| Skill ID | 名称 | 类型 | 优先级 | 生效阶段 | 生效角色 | 生效产出类型 |
|----------|------|------|--------|----------|----------|-------------|
| `ui_design_system` | UI设计系统 | style | 90 | produce | engineer, ux_designer | deployable_service, design_doc |
| `prd_traceability` | PRD溯源与质量约束 | constraint | 90 | clarify, produce | product_architect, clarifier | prd_openapi |
| `code_conventions` | 代码生成规范 | checklist | 85 | produce, review, bugfix | engineer | code_analysis, tested_system, deployable_service |
| `code_review` | 代码安全审查指南 | constraint | 80 | produce | security_expert | deployable_service, tested_system, code_analysis |
| `task_decomposition` | 任务分解规范（Specify-Plan-Tasks） | constraint | 80 | produce | product_architect, engineer | prd_openapi, design_doc, deployable_service, tested_system, code_analysis |
| `communication_style` | 沟通风格规范 | style | 80 | 所有对话阶段 | 所有角色 | 所有产出类型 |
| `deliverable_quality` | 产出质量验收 | checklist | 75 | review, arbitrate, produce | moderator, engineer | 所有产出类型 |

### 1.2 内置角色库（四维画像）

Conclave 当前内置 7 个角色，每个角色包含四维画像：

| 角色 ID | 中文名 | 核心视角 | 证据偏好 | 风险偏好 | 默认立场 |
|---------|--------|----------|----------|----------|----------|
| `moderator` | 主持人 | 推进流程、澄清议题、识别冲突 | policies | balanced | neutral |
| `product_architect` | 产品架构师 | 目标、用户价值、系统边界 | goals | conservative | value-first |
| `engineer` | 工程师 | 可行性、实现风险、测试边界 | constraints | conservative | feasibility-first |
| `security_expert` | 安全专家 | 认证、授权、数据安全 | risk | conservative | risk-first |
| `data_engineer` | 数据工程师 | 数据模型、存储、迁移 | constraints | balanced | data-first |
| `ux_designer` | UX设计师 | 交互流程、可用性 | goals | balanced | user-first |
| `marketing_expert` | 市场专家 | 市场定位、用户增长 | goals | aggressive | market-first |

### 1.3 现有体系的缺口分析

| 缺口类别 | 具体缺失 | 影响 |
|----------|----------|------|
| 人格类 Skill | 缺少非技术角色的完整画像（秘书、项目经理、BA、研究员、QA、DevOps、法务、财务、文档工程师） | 会议只能讨论技术产品话题，无法覆盖行政、管理、合规、商业全流程 |
| 角色方法论深度 | 现有角色的方法论描述较简略，缺少检查清单、输出模板、反模式 | 角色发言同质化，专业深度不足 |
| 工具 Skill | 外部工具集成没有对应的 Skill 指导如何使用工具 | 工具调用无规范，可能产生不一致行为 |
| 领域 Skill | 无行业知识包（金融、医疗、教育、电商） | 垂直行业场景下产出质量不足 |
| Skill 冲突检测 | 多个 Skill 可能给出矛盾指令 | 可能导致 LLM 行为不确定 |
| Token 预算感知 | 所有激活 Skill 全量注入 | 复杂场景下可能超出 context window |

---

## 二、职业人格类 Skill 目录

### 2.1 P0 优先级角色（高频使用，建议立即实现）

#### 2.1.1 秘书/行政助理（secretary）

| 属性 | 值 |
|------|-----|
| 角色 ID | `secretary` |
| 中文名 | 秘书 |
| 核心视角 | 日程管理、会议纪要、行动项追踪、跟进提醒、决议归档 |
| 证据偏好 | policies |
| 风险偏好 | conservative |
| 默认立场 | process-first |
| 激活阶段 | clarify, produce |
| 激活产出类型 | meeting_minutes, action_items, status_report |

**核心能力**：
- 自动提取会议中的决议、行动项（Action Item）、负责人（Owner）、截止日期（Deadline）
- 生成结构化会议纪要：议题清单、讨论要点、决议记录、待办事项、下次会议安排
- 追踪行动项状态：待开始/进行中/已完成/已阻塞
- 识别会议中的模糊表述并标记为待澄清项
- 生成会议议程模板和时间分配建议

**方法论/框架**：
- Robert's Rules of Order（议事规则）辅助
- SMART 行动项标准（Specific/Measurable/Assignable/Relevant/Time-bound）
- RACI 责任分配矩阵（Responsible/Accountable/Consulted/Informed）
- 会议纪要三段式：What/So What/Now What

**输出格式偏好**：
- 行动项表格格式：编号 | 事项 | 负责人 | 截止日期 | 状态 | 依赖
- 纪要采用倒金字塔结构（最重要决议在前）
- 待决问题明确标注 `[待决]` 和责任人

**建议优先级**：P0——Conclave 作为会议驱动平台，秘书角色是最基础的非技术角色，每场会议都需要纪要和行动项追踪。

#### 2.1.2 项目经理（project_manager）

| 属性 | 值 |
|------|-----|
| 角色 ID | `project_manager` |
| 中文名 | 项目经理 |
| 核心视角 | 任务分解、进度跟踪、风险管理、资源协调、站会主持 |
| 证据偏好 | constraints |
| 风险偏好 | balanced |
| 默认立场 | delivery-first |
| 激活阶段 | clarify, intra_team, produce |
| 激活产出类型 | project_plan, gantt_chart, risk_register, status_report, task_board |

**核心能力**：
- 将产品需求分解为可执行的工作包（Work Breakdown Structure, WBS）
- 识别关键路径（Critical Path）和里程碑（Milestone）
- 风险登记与管理：识别概率/影响/缓解策略/应急计划
- 资源分配与负载均衡
- 站会（Daily Standup）facilitation：昨天做了什么/今天做什么/有什么阻塞
- 进度报告生成：燃尽图（Burndown）、看板状态、偏差分析

**方法论/框架**：
- PMBOK 知识体系（范围/时间/成本/质量/风险/沟通/采购/相关方）
- Agile/Scrum：Sprint Planning、Daily Standup、Sprint Review、Retrospective
- Kanban 方法：可视化流程、WIP 限制、流动效率
- RICE 优先级框架（Reach/Impact/Confidence/Effort）
- MoSCoW 优先级（Must have/Should have/Could have/Won't have）
- 风险矩阵：概率 x 影响 = 风险等级

**建议优先级**：P0——从 PRD 到可部署服务的转化过程中，项目管理角色是衔接需求与交付的关键。

#### 2.1.3 QA/测试工程师（qa_engineer）

| 属性 | 值 |
|------|-----|
| 角色 ID | `qa_engineer` |
| 中文名 | 测试工程师 |
| 核心视角 | 测试用例设计、边界条件识别、回归测试策略、质量度量 |
| 证据偏好 | constraints |
| 风险偏好 | conservative |
| 默认立场 | quality-first |
| 激活阶段 | intra_team, cross_team, produce, review |
| 激活产出类型 | test_plan, test_cases, test_report, deployable_service, tested_system |

**核心能力**：
- 根据需求文档设计测试用例：等价类划分、边界值分析、错误推测法
- 识别边界条件和异常路径：空值、超长输入、并发、网络中断、权限不足
- 制定测试策略：单元测试/集成测试/E2E测试/性能测试/安全测试的覆盖范围
- 回归测试集维护：识别哪些变更需要回归哪些测试
- Bug 分级与报告：复现步骤/预期结果/实际结果/严重等级/环境信息

**方法论/框架**：
- 测试金字塔：单元测试(70%) > 集成测试(20%) > E2E测试(10%)
- ISTQB 测试设计技术：等价类划分、边界值分析、决策表、状态转换
- BDD（Behavior-Driven Development）：Gherkin语法 Given-When-Then
- 缺陷生命周期：New → Assigned → Fixed → Verified → Closed
- 质量度量：缺陷密度、测试通过率、覆盖率、逃逸缺陷率

**建议优先级**：P0——Conclave 现有 engineer 角色兼负 QA 视角，但专业深度不足。独立 QA 角色能显著提升产出代码质量。

#### 2.1.4 技术文档工程师（tech_writer）

| 属性 | 值 |
|------|-----|
| 角色 ID | `tech_writer` |
| 中文名 | 技术文档工程师 |
| 核心视角 | API 文档、用户指南、架构文档、README 生成、文档一致性 |
| 证据偏好 | goals |
| 风险偏好 | balanced |
| 默认立场 | clarity-first |
| 激活阶段 | produce, review |
| 激活产出类型 | api_docs, user_guide, architecture_doc, readme, design_doc |

**核心能力**：
- 从代码和注释中自动生成/补全 API 文档（OpenAPI/Swagger 格式）
- 编写用户指南：快速开始、安装步骤、配置说明、常见问题
- 架构文档撰写：系统上下文图、组件图、数据流图、部署拓扑
- README 质量审计：检查是否包含必要章节（功能/安装/配置/启动/API/贡献/许可证）
- 文档一致性检查：文档描述与实际代码行为是否一致
- 变更日志（CHANGELOG）维护：按 Keep a Changelog 格式组织

**方法论/框架**：
- 文档即代码（Docs as Code）：Markdown 格式、版本控制、CI 检查
- Diataxis 框架：教程/Tutorial、How-to指南、解释/Explanation、参考/Reference 四类文档
- OpenAPI 3.0 规范：路径/参数/请求体/响应/错误码/认证
- 架构文档：C4 模型（Context/Container/Component/Code）
- README 标准结构：项目简介 → 功能特性 → 环境要求 → 安装步骤 → 快速开始 → 配置说明 → API文档 → 故障排查 → 贡献指南 → 许可证

**建议优先级**：P0——每次产出 deployable_service 都需要高质量 README 和 API 文档。

### 2.2 P1 优先级角色（重要增强，近期实现）

#### 2.2.1 商业分析师（business_analyst）

| 属性 | 值 |
|------|-----|
| 角色 ID | `business_analyst` |
| 核心视角 | 需求获取、市场分析、竞品情报、ROI 计算、商业模式验证 |
| 证据偏好 | goals |
| 风险偏好 | balanced |
| 默认立场 | value-first |
| 激活阶段 | clarify, intra_team, cross_team |
| 激活产出类型 | market_research, competitive_analysis, business_case, roi_analysis, prd_openapi |

**方法论/框架**：BABOK、商业模式画布、价值主张画布、Kano模型、TAM/SAM/SOM模型、竞品功能矩阵、NPV/IRR/Payback Period。

**建议优先级**：P1——商业分析在产品立项和市场讨论中高频使用。

#### 2.2.2 研究员/调研员（researcher）

| 属性 | 值 |
|------|-----|
| 角色 ID | `researcher` |
| 核心视角 | 文献综述、数据收集、来源验证、引用管理、事实核查 |
| 证据偏好 | goals |
| 风险偏好 | conservative |
| 默认立场 | evidence-first |
| 激活阶段 | clarify, intra_team, evidence_check |
| 激活产出类型 | research_report, literature_review, source_verification |

**方法论/框架**：PRISMA系统性综述、CRAAP测试（Currency/Relevance/Authority/Accuracy/Purpose）、三角验证法、证据等级金字塔。

**建议优先级**：P1——Conclave 已有 evidence_check 阶段，但没有专业研究员角色执行深度调研和事实核查。

#### 2.2.3 DevOps/运维工程师（devops_engineer）

| 属性 | 值 |
|------|-----|
| 角色 ID | `devops_engineer` |
| 核心视角 | CI/CD 配置、监控告警、容器化部署、容灾备份、事故响应 |
| 证据偏好 | constraints |
| 风险偏好 | conservative |
| 默认立场 | reliability-first |
| 激活阶段 | intra_team, produce, review |
| 激活产出类型 | deployable_service, cicd_pipeline, monitoring_config, incident_report |

**方法论/框架**：GitOps、12-Factor App、SRE方法论（SLO/SLI/SLA/错误预算）、IaC（Terraform/Ansible）、可观测性三大支柱（Metrics/Logs/Traces）。

**建议优先级**：P1——生成的 deployable_service 需要专业 DevOps 审查才能生产就绪。

#### 2.2.4 法务/合规专员（legal_compliance）

| 属性 | 值 |
|------|-----|
| 角色 ID | `legal_compliance` |
| 核心视角 | 许可证合规、隐私审查、服务条款分析、知识产权、数据保护 |
| 证据偏好 | policies |
| 风险偏好 | conservative |
| 默认立场 | compliance-first |
| 激活阶段 | cross_team, review, arbitrate |
| 激活产出类型 | license_review, privacy_impact_assessment, terms_analysis, compliance_report |

**方法论/框架**：开源许可证兼容性矩阵、GDPR核心原则、Privacy by Design、PIPL（个人信息保护法）、DPIA。

**建议优先级**：P1——在产品发布、开源许可证选择、处理用户数据时必须审查。

### 2.3 P2 优先级角色（按需扩展）

| 角色 ID | 中文名 | 核心方法论 | 建议 |
|---------|--------|-----------|------|
| `product_manager` | 产品经理 | RICE/MoSCoW/Kano、用户故事映射、OKR、North Star Metric | product_architect已覆盖部分职能，纯PM视角仍有差异 |
| `ux_researcher` | UX研究员 | 用户访谈五步法、亲和图、Persona、可用性测试(SUS/NPS)、A/B测试 | 与UX设计师配合，偏研究而非设计 |
| `data_scientist` | 数据科学家 | 假设检验、贝叶斯分析、特征工程、模型评估、因果推断 | 与data_engineer互补，偏分析建模 |
| `financial_analyst` | 财务分析师 | COCOMO成本估算、LTV/CAC、单位经济模型、三表预测 | business_analyst已覆盖部分 |
| `designer` | 设计师 | Atomic Design、色彩理论、设计Token、8pt网格、品牌指南 | ux_designer偏交互，视觉设计师在品牌场景中需要 |

---

## 三、开源技能/插件生态系统分析

### 3.1 平台对比矩阵

| 平台 | 技能格式 | 角色/Persona支持 | 触发机制 | 与Conclave相似度 |
|------|----------|-----------------|----------|----------------|
| **CrewAI** | YAML (agents.yaml) | role+goal+backstory三元组 | Task编排，context参数串联 | 高 |
| **Claude Code Skills** | Markdown (.claude/skills/) | 支持自定义persona | 自动触发或/命令调用 | 高 |
| **Cursor Rules** | .mdc (.cursor/rules/) | 规则塑造行为 | glob模式匹配/@提及/Always | 高 |
| **MCP协议** | JSON Schema (Tool/Prompt/Resource) | Prompt模板可定义persona | 主机动态发现 | 中 |
| **AutoGen** | Python代码/配置 | system_message定义角色 | GroupChatManager选择发言者 | 高 |
| **LangGraph** | Python代码 | Agent节点即角色 | Supervisor/Hierarchical/Network拓扑 | 中 |
| **Dify** | Plugin包(.difypkg) | Agent节点+策略插件 | Workflow节点连线 | 中 |
| **Coze(扣子)** | 可视化配置+Plugin | Bot persona+工作流 | 工作流节点触发 | 低 |
| **Semantic Kernel** | C#/Python Plugin | Plugin封装角色能力 | Planner自动选择Plugin | 中 |
| **Roo Code/Cline** | .roomodes JSON | roleDefinition+whenToUse+tool groups | 模式切换/自动检测 | 高 |
| **Aider** | CONVENTIONS.md | 无独立persona | 会话开始时加载 | 中 |
| **GitHub Copilot** | .github/skills/*.md | Custom Agents（2025新增） | 文件模式匹配/手动调用 | 高 |
| **Continue.dev** | .continue/rules/*.md | 无内置persona | slash命令/@文件/@目录 | 中 |
| **Windsurf** | .windsurfrules | Cascade flows | Always/Manual/Model Decision | 高 |
| **OpenAI GPTs** | 自然语言Instructions | 自定义persona+知识库+Actions | 用户对话触发 | 低 |
| **Trae CN** | .trae/skills/ + MCP | 自定义Agent | 自动触发/手动调用 | 极高 |

### 3.2 关键模式提取

#### 3.2.1 CrewAI：role-goal-backstory 三元组

```yaml
researcher:
  role: "{topic} Senior Data Researcher"
  goal: "Uncover cutting-edge developments in {topic}"
  backstory: "You're a seasoned researcher..."
```

**可借鉴点**：backstory 让角色更有"人味"，goal 比 perspective 更具行动导向性。

#### 3.2.2 Roo Code：自定义 Mode 系统（最具参考价值）

```json
{
  "slug": "technical-writer",
  "name": "Technical Writer",
  "roleDefinition": "You are a technical writer...",
  "whenToUse": "Use this mode for writing and editing documentation.",
  "customInstructions": "Focus on clarity...",
  "groups": ["read", ["edit", { "fileRegex": "\\.(md|mdx)$" }]]
}
```

**可借鉴点**：`whenToUse` 明确触发条件；`groups` 工具权限控制（不同角色可使用不同工具集）；`fileRegex` 文件级权限。

#### 3.2.3 Claude Code Skills：Markdown即Skill

- 极简格式：纯 Markdown + YAML frontmatter
- 支持子文件引用（同目录下其他文件作为参考资料）
- allowedTools：细粒度工具白名单
- 项目级和全局两级存储

#### 3.2.4 MCP 协议：工具/资源/Prompt 三层标准化

- **Tools**：可执行函数
- **Resources**：可读数据
- **Prompts**：可复用提示词模板
- 截至2025年底已有近2000个 MCP 服务器
- Conclave 的工具集成应包装为 MCP 服务器以复用生态

#### 3.2.5 Windsurf：三模式触发规则

- **Always On**：始终生效（如编码规范）
- **Manual**：用户@提及才激活
- **Model Decision**：AI 判断何时激活

**对 Conclave 的启示**：当前只有"匹配即激活"，可以增加 Always 和 Manual 模式。

### 3.3 开源技能可复用 vs 需要自定义

| 技能类别 | 可直接复用/适配 | 需要Conclave自定义 |
|----------|----------------|-------------------|
| 代码规范 | Aider CONVENTIONS、Cursor rules编码规范 | DDL单一真相源、Docker纪律、多租户隔离 |
| 沟通风格 | Claude Code communication guidelines | [事实]/[假设]标签系统、中文方括号标签 |
| UI设计系统 | Radix UI、shadcn、Tailwind tokens | Conclave品牌色#335c8e、Impeccable反模式 |
| PRD/需求管理 | CrewAI researcher+writer模板 | PRD溯源(source_quotes/append-only)、SMART+BDD |
| 安全审查 | OWASP Top10检查清单 | 沙箱环境特有规则、OCR结果解读 |
| 角色persona | CrewAI backstory、Roo Code roleDefinition | 六阶段行为、四维画像、证据/风险/立场 |
| 工具集成 | MCP服务器（2000+） | 沙箱执行、Playwright、Bing/DDG搜索 |

---

## 四、Conclave人格Skill集成方案

### 4.1 新增Skill类型：persona

| 维度 | 现有Framework Skill | persona Skill |
|------|-------------------|---------------|
| 关注点 | "应该怎么做"（规范、约束） | "我是谁"（视角、方法论、思维框架） |
| 激活范围 | stage+deliverable_type+role组合 | 绑定到特定role_id，该角色发言时始终激活 |
| 优先级 | 75-90 | 95（高于所有framework skill） |

### 4.2 YAML格式扩展

persona 类型 Skill 新增 `persona:` 字段块：

```yaml
id: secretary
name: "秘书"
type: persona
priority: 95
persona:
  role_id: "secretary"
  display_name: "秘书"
  perspective: "日程管理、会议纪要、行动项追踪"
  evidence_preference: "policies"
  risk_appetite: "conservative"
  default_stance: "process-first"
  methodologies: ["SMART行动项", "RACI矩阵", "议事规则辅助"]
  checklists: ["决议有行动项/负责人/截止日期", "模糊表述标记待澄清"]
  collaboration_boundary: "不做技术判断或商业决策"
  tool_permissions: ["search", "read"]  # 预留
applies_to:
  roles: ["secretary"]
  stages: ["clarify", "intra_team", "produce"]
prompt: |
  # 秘书角色指南
  ...（完整prompt内容）
```

### 4.3 与现有系统的集成点

1. **RoleTemplate 扩展**：从硬编码迁移到 YAML 加载，向后兼容内置7个角色
2. **Role 枚举扩展**：短期扩展Enum，长期演进到动态角色+数据库持久化
3. **角色模糊匹配扩展**：`_ROLE_KEYWORDS` 添加新角色的中英文关键词
4. **Skill 匹配逻辑**：persona 类型对绑定角色始终激活
5. **前端展示适配**：角色选择器动态展示所有可用角色

### 4.4 Skill 分类体系

```
Conclave Skills
├── Framework Skills（框架规范类）—— 现有7个
├── Persona Skills（人格角色类）—— 新增
│   ├── Built-in（7个升级为YAML persona）
│   └── Extended（P0: 4个 / P1: 4个 / P2: 5个）
├── Tool Skills（工具使用类）—— 未来
└── Domain Skills（领域知识类）—— 未来
```

---

## 五、优先级路线图

### P0：立即实现（约 3-4 人日）

| 任务 | 工作量 |
|------|--------|
| 1. 现有7个内置角色迁移为 persona YAML | 1人日 |
| 2. 新增 secretary / project_manager / qa_engineer / tech_writer | 2人日 |
| 3. 扩展 Role 枚举和角色匹配 | 0.5人日 |
| 4. 更新 SKILL_REGISTRY + 测试 | 0.5人日 |

**P0 完成后**：角色总数从7个增加到11个，覆盖"需求→设计→开发→测试→文档→管理"全流程。

### P1：近期实现（约 5 人日）

| 任务 | 工作量 |
|------|--------|
| 5. 新增 business_analyst / researcher / devops_engineer / legal_compliance | 2人日 |
| 6. 实现工具权限框架（tool_permissions） | 2人日 |
| 7. 会议模板支持新角色组合 | 1人日 |

**P1 完成后**：角色总数达15个，覆盖商业分析、调研、运维、合规，支持角色级工具权限。

### P2：按需扩展（约 15+ 人日）

P2 角色、Tool Skills、Skill冲突检测、Token预算裁剪、Domain Skills试点、MCP集成框架、前端Skill管理UI。

---

## 六、风险与注意事项

### 6.1 人格冲突风险
多角色观点冲突是正常现象（cross_team阶段正是为此设计）。缓解：主持人推进收敛、arbitrate裁决、最大轮次限制。

### 6.2 Token 预算压力
每个 persona 约 800-1200 tokens，每场会议 5-7 个角色但每个角色只看到自己的 persona，增量约 1000 tokens/角色，占 128K 窗口 < 1%。

### 6.3 角色膨胀风险
P0 严格控制在4个新角色；提供"推荐角色"和"会议模板"降低选择复杂度。

### 6.4 角色与 Skill 边界模糊
原则：persona 定义"怎么思考、关注什么"，framework Skill 定义"产出必须满足什么标准"。允许合理重叠。

### 6.5 维护成本
通用方法论抽取为共享片段；建立版本号机制；长期从实际会议中自动学习和优化。

### 6.6 文化适配
方法论提供中文本地化解释；允许用户自定义 persona 覆盖内置版本。

---

## 七、总结与建议

1. **Conclave Skill 架构设计先进**：YAML声明式配置、四维匹配、优先级注入，与主流平台一致。

2. **人格类 Skill 是 ROI 最高的扩展方向**：每个新角色只需一个 YAML 文件（约100-150行），即可覆盖全新会议场景。

3. **P0 四个角色优先实现**：秘书、项目经理、QA工程师、技术文档工程师覆盖最高频场景。

4. **开源生态提供丰富可复用资源**：CrewAI三元组、Roo Code工具权限、MCP工具生态、Claude Code轻量格式都值得借鉴。

5. **长期方向是开放生态**：用户自定义 persona、MCP集成、Skill市场，从"7个固定角色"演进为"可扩展多Agent协作平台"。

---

## 附录A：参考资源

### 开源框架文档
- CrewAI Agents: https://docs.crewai.com/en/concepts/agents
- Claude Code Skills: https://docs.anthropic.com/en/docs/claude-code/skills
- Cursor Rules: https://cursor.com/docs/rules.md
- Roo Code Custom Modes: https://roocodeinc.github.io/Roo-Code/features/custom-modes/
- Aider Conventions: https://aider.chat/docs/usage/conventions.html
- GitHub Copilot Custom Instructions: https://docs.github.com/en/copilot
- MCP Protocol: https://modelcontextprotocol.io/
- AutoGen: https://microsoft.github.io/autogen/
- LangGraph Multi-Agent: https://langchain-ai.github.io/langgraph/
- Semantic Kernel Plugins: https://learn.microsoft.com/en-us/semantic-kernel/
- Dify Plugins: https://dify.ai/

### Conclave内部文档
- Skill系统架构: `docs/research/skill-system-architecture.md`
- 角色模板: `backend/app/agents/role_templates.py`
- Skill加载器: `backend/app/agents/skills.py`
- Skill定义: `backend/app/skills/*.yaml`
- ADR-014 动态工作流: `docs/design/adr/014-dynamic-workflow-assembly.md`
- 设计原则: `docs/design/design-principles.md`
- UI设计系统: `backend/app/skills/ui_design_system.yaml`
