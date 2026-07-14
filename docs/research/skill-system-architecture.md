# Conclave Agent Skill 系统架构文档

> 最后更新：2026-07-10

## 1. 设计动机

在多 Agent 辩论系统中，不同阶段、不同角色、不同产出类型对 LLM 的约束完全不同。将所有规范硬编码在一个超长 prompt 中会导致：

- **Token 浪费**：与当前任务无关的规范（如前端设计规则在写 PRD 时）也被注入
- **维护困难**：修改一个偏好需要搜索整个 prompt 模板
- **无法动态扩展**：用户自定义偏好、项目特定规范无处放置
- **知识无法沉淀**：BugFix 循环中积累的经验没有分层管理

Skill 系统的核心思想：**按需加载、上下文感知、可组合叠加**。

## 2. 核心概念

### Skill 是什么

Skill 是一个可被 Agent 在运行时动态加载的知识/规范/偏好模块。每个 Skill 是一个 YAML 文件，包含：

- **元数据**：ID、名称、描述、版本、类型、优先级、标签
- **触发条件**（`applies_to`）：在什么阶段/什么产出类型/什么角色/什么复杂度下激活
- **Prompt 内容**：注入到 LLM prompt 的规范文本

### Skill 与 Bug Patterns 的区别

| 维度 | Skills | Bug Patterns |
|------|--------|--------------|
| 性质 | 正面指南（"应该怎么做"） | 负面清单（"不要犯什么错"） |
| 触发 | 按上下文（阶段/角色/产出类型）匹配 | 始终注入（produce阶段） |
| 内容 | 设计规范、代码风格、沟通方式 | 具体Bug模式、错误示例、修复方案 |
| 粒度 | 模块化（一个Skill一个主题） | 分类聚合（Python/前端/部署） |
| 扩展 | 用户可创建自定义Skill | BugFix循环自动追加 |

两者互补：Skills 告诉 Agent "好的标准是什么"，Bug Patterns 告诉 Agent "哪些坑不要踩"。

## 3. 文件结构

```
backend/app/
├── agents/
│   ├── skills.py              # Skill加载器核心（Skill dataclass + 匹配逻辑）
│   ├── bug_patterns.py        # Bug经验库加载器
│   └── compute.py             # Prompt构建，注入Skills和BugPatterns
├── skills/                    # Skill定义文件（YAML）
│   ├── ui_design_system.yaml  # UI设计规范（色彩/排版/组件/反模式）
│   ├── code_conventions.yaml  # 代码生成规范（结构/安全/API/部署）
│   ├── communication_style.yaml # 沟通风格（语言/格式/禁忌）
│   └── deliverable_quality.yaml # 产出验收标准（质量门槛）
├── prompts/
│   └── bug_patterns.yaml      # Bug经验库（按分类组织的错误模式）
└── orchestrator/
    └── nodes/                  # 编排节点包（clarify/intra_team/cross_team/evidence_check/arbitrate/produce/borrow），review阶段注入Skills
```

## 4. Skill 加载机制

### 4.1 触发条件匹配

每个 Skill 通过 `applies_to` 字段声明激活条件：

```yaml
applies_to:
  stages: ["produce"]                    # 生效阶段，空=全部
  deliverable_types: ["deployable_service"] # 产出类型，空=全部
  roles: ["engineer", "ux_designer"]     # 角色，空=全部
  complexity: []                         # 复杂度，空=全部
```

匹配逻辑（`Skill.matches()`）：
- 如果 Skill 声明了 `stages` 且当前阶段不在列表中 → 不激活
- 如果 Skill 声明了 `deliverable_types` 且当前产出类型不在列表中 → 不激活
- 如果 Skill 声明了 `roles` 且当前角色不在列表中 → 不激活
- 如果 Skill 声明了 `complexity` 且当前复杂度不在列表中 → 不激活
- 所有条件满足或未声明 → 激活

### 4.2 优先级排序

激活的 Skills 按 `priority` 字段降序排列（高优先级先注入prompt）。当前优先级设置：

| Skill | Priority | 说明 |
|-------|----------|------|
| ui_design_system | 90 | 设计规范优先级最高 |
| code_conventions | 85 | 代码规范次之 |
| communication_style | 80 | 沟通风格 |
| deliverable_quality | 75 | 验收标准 |

### 4.3 注入点

Skills 在以下位置注入 LLM prompt：

1. **`compute.py` - 所有阶段**：
   - `build_clarify_prompt()` → stage="clarify"
   - `build_intra_team_prompt()` → stage="intra_team"
   - `build_cross_team_prompt()` → stage="cross_team"
   - `build_evidence_prompt()` → stage="evidence_check"
   - `build_arbitrate_prompt()` → stage="arbitrate"
   - `build_produce_prompt()` → stage="produce"（带 deliverable_type）

2. **`nodes.py` - Review阶段**：
   - 代码审查时注入 `deliverable_quality` 和 `code_conventions`

### 4.4 缓存机制

`load_all_skills()` 使用 `@lru_cache(maxsize=4)` 缓存，避免每次构建prompt都读磁盘。Skill文件更新后可调用 `reload_skills()` 清除缓存。

## 5. 当前 Skills 清单

### 5.1 ui_design_system (v2)

**触发条件**：produce阶段 + deployable_service/design_doc + engineer/ux_designer

封装用户的完整审美偏好和前端设计规则：

- **核心哲学**：反装饰功能优先、克制色彩纯色为王、信息密度优先、场景分层各司其职
- **色彩体系**：纯白背景 + 沉稳靛蓝(#335c8e)品牌色 + 冷灰文字阶 + 6%透明度状态色背景
- **排版规则**：Inter字体、13-14px正文、1.5-1.6行高、字重400-700
- **形状间距**：4-8px圆角、极轻阴影(0.04-0.06透明度)、4px间距基准
- **组件规范**：Notion表格、靛蓝按钮、inline-flex Badge、1px边框卡片
- **CSS反模式**：8条必须避免的前端陷阱（Flex溢出、文字截断、z-index管理、图表设计、Modal溢出等）
- **交互设计**：0.15s过渡、32px最小点击区、skeleton加载态

### 5.2 code_conventions (v1)

**触发条件**：produce/review/bugfix阶段 + 代码类产出 + engineer

涵盖：
- 项目结构（单文件<500行、模块拆分）
- 错误处理（try/except、HTTPException）
- 安全要求（参数化SQL、bcrypt哈希、JWT过期、CORS配置）
- API设计（RESTful、统一响应、分页、/health端点）
- 数据库（连接关闭、WAL模式、外键约束）
- Docker部署（0.0.0.0绑定、端口一致、必要目录创建）
- 真实性要求（禁止mock数据、TODO标注）

### 5.3 communication_style (v1)

**触发条件**：所有对话阶段（clarify/intra_team/cross_team/evidence_check/arbitrate），所有角色和产出类型

规范Agent发言风格：
- 自然流畅中文，技术名词可保留英文
- 角色名/阶段名使用中文
- 禁止【角色·阶段】机器头
- 编号段落+标签格式（[事实]/[假设]/[风险]/[建议]）
- 论点具体可执行，说明理由
- 禁止原始JSON、Markdown表格、emoji、分隔线

### 5.4 deliverable_quality (v1)

**触发条件**：review/arbitrate/produce阶段 + moderator/engineer

定义产出验收标准：
- 通用质量门槛（完整、一致、可执行、不编造）
- 代码类产出验收（11项checklist）
- 文档类产出验收（6项checklist）
- 问题严重等级定义（critical/high/medium/low）

## 6. API 接口

### GET /meetings/skills/list

列出所有已加载的Skills（供调试和前端展示）：

```json
{
  "skills": [
    {
      "id": "ui_design_system",
      "name": "UI设计系统",
      "description": "...",
      "type": "style",
      "version": 2,
      "priority": 90,
      "applies_to": { ... },
      "tags": ["design", "frontend", ...]
    }
  ]
}
```

## 7. Bug 经验库 (bug_patterns.yaml)

按分类组织的负面清单，在produce阶段始终注入：

| 分类 | ID前缀 | 条目数 | 覆盖内容 |
|------|--------|--------|----------|
| Python/FastAPI | PY | 10 | import、requirements、JWT、SQL注入、密钥、CORS、文件上传、bcrypt、datetime |
| Docker/部署 | DK | 6 | CMD路径、build上下文、卷挂载、gcc依赖、端口、目录创建 |
| 前端/React | FE | 13 | API地址、key prop、Flex溢出、Modal溢出、图表反模式、动画布局属性、Badge截断、z-index、列表排序、ECharts内存泄漏、UTF-8 BOM、CSS装饰过重、PostCSS @import |
| 架构/设计 | AR | 6 | Mock数据、功能偏差、单文件过大、健康检查、README、默认账号 |

每个Bug模式包含：ID、名称、问题描述、修复方案、严重等级、正反示例代码。

## 8. 如何扩展

### 添加新的 Skill

1. 在 `backend/app/skills/` 下创建新的YAML文件：

```yaml
id: my_custom_skill
name: "我的自定义规范"
description: "描述这个Skill的作用"
version: 1
type: guideline  # guideline/constraint/style/checklist
priority: 70
tags: ["custom"]

applies_to:
  stages: ["produce"]
  deliverable_types: ["deployable_service"]
  roles: ["engineer"]
  complexity: []

prompt: |
  # 我的自定义规范
  - 规则1
  - 规则2
```

2. 调用 `reload_skills()` 或重启服务，新Skill自动加载。

### 追加 Bug 模式

BugFix循环修复问题后，调用 `append_bug_pattern()` 自动追加：

```python
from app.agents.bug_patterns import append_bug_pattern
append_bug_pattern("frontend_react", {
    "id": "FE014",
    "name": "新Bug模式",
    "pattern": "问题描述",
    "fix": "修复方案",
    "severity": "high",
})
```

## 9. 当前欠缺与改进方向

### 9.1 已完成

- [x] Skill基础框架（加载/匹配/注入/缓存）
- [x] 4个核心Skill（设计/代码/沟通/质量）
- [x] Bug经验库（Python/Docker/前端/架构 共35+模式）
- [x] 全阶段Skill注入（compute.py所有build_prompt）
- [x] Review阶段Skill注入
- [x] Skills列表API
- [x] 运行时缓存刷新机制

### 9.2 待完善

1. **Skill管理UI**：前端缺少Skill管理界面，目前只能通过编辑YAML文件添加
2. **用户级Skill**：当前Skills是全局的，不支持按用户/项目/会议自定义
3. **Skill版本控制**：修改Skill后无版本历史，无法回滚
4. **Skill效果反馈**：无法衡量某个Skill是否真正减少了对应类型的错误
5. **Skill组合冲突**：两个Skill的规则可能冲突（如code_conventions说用4空格，另一个说用2空格），缺少冲突检测
6. **前端Skill粒度**：ui_design_system是一个大Skill，可拆分为 color_system、typography、layout_patterns、chart_design 等更小的模块
7. **Skill启用/禁用**：没有按会议粒度开关某个Skill的机制
8. **A/B测试**：无法对比启用/禁用某个Skill对产出质量的影响
9. **Token预算感知**：当前所有激活Skill全量注入，没有根据剩余Token预算裁剪低优先级Skill
10. **Skill依赖关系**：某些Skill可能依赖其他Skill先激活，缺少依赖声明

### 9.3 长期方向

- **Skill市场**：可分享/导入的Skill包
- **自动Skill生成**：从BugFix历史和代码审查中自动提炼新Skill
- **Skill评分**：根据用户反馈（采纳/拒绝修复）动态调整Skill优先级
- **上下文压缩**：当Token紧张时，自动将长Skill压缩为精简版
