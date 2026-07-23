[返回上级文档](../../README.md)

# Agents 模块 — Agent 计算层

> 智能体子系统：LLM 调用、角色定义、Prompt 管理、全链路追踪。

## 1. 模块定位

Agents 模块是 Conclave 多智能体会议系统的**计算核心层**，负责：

- **LLM 调用封装**：统一对接 OpenAI 兼容接口，内置重试、降级、熔断器、Provider 回退链
- **角色定义**：7 个内置专业角色（主持人、产品架构师、工程师、安全专家、UX 设计师、数据工程师、市场专家），每个角色有独立的视角、决策偏置和风险偏好
- **Prompt 模板管理**：按会议阶段（clarify / intra_team / cross_team / evidence_check / arbitrate / produce）组织模板，支持 Skills 动态注入
- **全链路追踪**：记录每次 LLM 调用的完整信息（prompt、原始响应、解析结果、token 消耗、延迟、降级状态），用于审计、复现和成本统计
- **结构化输出校验**：三明治模式（请求层 Schema 注入 → 解析层 Pydantic 校验 → 重试/降级层）保证 LLM 输出始终符合预期结构

## 2. 架构概览

```
┌─────────────────────────────────────────────────┐
│                 orchestrator/                    │
│            (状态机驱动的阶段编排器)                 │
└──────────────────┬──────────────────────────────┘
                   │ 调用
                   ▼
┌─────────────────────────────────────────────────┐
│              AgentRuntime                        │
│  统一执行入口：构造 prompt → 调 compute → 校验结果  │
│  AgentConfig + AgentContext → AgentResult        │
└──────────────────┬──────────────────────────────┘
                   │ think()
                   ▼
┌─────────────────────────────────────────────────┐
│              Compute 层 (compute.py)              │
│  LocalAgentCompute (进程内) / GRPCAgentCompute    │
│  ├─ build_xxx_prompt()  按阶段构造 prompt          │
│  ├─ _inject_profile()   注入角色画像               │
│  ├─ _inject_skills()    注入激活的 Skill           │
│  └─ llm.complete()      调用底层 LLM               │
└──────────────────┬──────────────────────────────┘
                   │
        ┌──────────┴──────────┐
        ▼                     ▼
┌──────────────┐    ┌──────────────────────┐
│ RealLLM       │    │ StubLLM (降级/无key)  │
│ httpx + 重试  │    │ 返回符合 schema 的假数据│
│ + Provider回退│    └──────────────────────┘
│ + 熔断器      │
└──────┬───────┘
       │ 记录
       ▼
┌──────────────┐
│  CallTrace    │
│  全链路追踪    │
└──────────────┘
```

### 核心组件关系

| 组件 | 职责 | 文件 |
|------|------|------|
| `AgentRuntime` | 统一 Agent 执行入口，根据 `AgentConfig` 构造 prompt、调用 compute、递归拆分子任务 | `agent_runtime.py` |
| `AgentConfig` | Agent 运行时配置（角色、指令、输出 schema、工具、子 Agent、温度） | `agent_runtime.py` |
| `AgentContext` | 单次执行上下文（会议 ID、议题、阶段、工作记忆、父约束、锁定结论） | `agent_runtime.py` |
| `Compute` (Protocol) | 计算抽象层，解耦"思考"与具体调用方式（本地/远程 Worker） | `compute.py` |
| `LocalAgentCompute` | 进程内 Compute 实现，按阶段构造 prompt 并调用 LLM | `compute.py` |
| `LLMClient` (Protocol) | LLM 客户端协议：输入 prompt，返回解析后的 dict | `llm.py` |
| `RealLLM` | 真实 LLM 客户端（httpx 调 OpenAI 兼容接口） | `llm.py` |
| `StubLLM` | 桩 LLM，无 API Key 时返回符合各阶段 schema 的假数据 | `llm.py` |

## 3. Agent 角色体系（7 个内置角色）

角色定义集中在 `role_templates.py` 的 `ROLE_LIBRARY` 字典中，每个角色包含：核心视角、证据偏好、风险偏好、默认立场、prompt 模板。

| 角色 ID | 中文名 | 核心视角 | 证据偏好 | 风险偏好 | 默认立场 |
|---------|--------|---------|---------|---------|---------|
| `moderator` | 主持人 | 推进流程、澄清议题、识别冲突、维持规则 | policies（规则） | balanced | neutral（中立） |
| `product_architect` | 产品架构师 | 目标、用户价值、系统边界、接口约束 | goals（目标） | conservative | value-first（价值优先） |
| `engineer` | 工程师 | 可行性、实现风险、测试边界（兼负 QA 视角） | constraints（约束） | conservative | feasibility-first（可行性优先） |
| `security_expert` | 安全专家 | 认证、授权、数据安全、注入防护 | risk（风险） | conservative | risk-first（风险优先） |
| `ux_designer` | UX 设计师 | 交互流程、可用性、错误处理 | goals（目标） | balanced | user-first（用户优先） |
| `data_engineer` | 数据工程师 | 数据模型、存储、迁移、一致性 | constraints（约束） | balanced | data-first（数据优先） |
| `marketing_expert` | 市场专家 | 市场定位、用户增长、商业价值、竞争差异化 | goals（目标） | aggressive | market-first（市场优先） |

### 角色决策偏置简述

- **主持人**：保持中立，重流程合规与冲突暴露，不持立场
- **产品架构师**：先谈价值与约束，再谈实现；重证据引用；适度保守
- **工程师**：先质疑可行性，再谈方案；重执行细节和测试边界
- **安全专家**：先找安全漏洞，重风险评估，保守型决策
- **UX 设计师**：从用户视角出发，关注交互体验和错误处理
- **数据工程师**：重数据完整性和一致性，关注迁移方案
- **市场专家**：先看市场价值与增长空间，重商业可行性；适度激进

## 4. 关键文件索引

| 文件 | 用途 |
|------|------|
| `__init__.py` | 模块入口，标记为智能体子系统 |
| `agent_runtime.py` | 统一 Agent 运行时（`AgentRuntime` / `AgentConfig` / `AgentContext` / `AgentResult`） |
| `compute.py` | 计算抽象层，`LocalAgentCompute` 实现，按阶段构造 prompt + 注入角色画像与 Skills |
| `llm.py` | LLM 客户端封装（`RealLLM` / `StubLLM`），三明治校验、重试、Provider 回退、熔断器 |
| `roles.py` | Agent 工厂（`get_agent()` 单例缓存 + 便捷工厂函数），re-export `app.models.Role` |
| `role_templates.py` | 动态角色库（`ROLE_LIBRARY`），7 个内置角色的画像与决策偏置定义 |
| `prompts.py` | Prompt 模板 re-export 入口（源码编译保护，实际模板在 `conclave_core.prompts`） |
| `schemas.py` | LLM 结构化输出 Pydantic 模型（6 个阶段的输出 schema） |
| `trace.py` | 全链路追踪（`CallTrace` / `LLMCallRecord`），调用记录与统计摘要 |
| `skills.py` | Skill 系统（YAML 动态加载的知识/规范模块） |
| `bug_patterns.py` | Bug 模式负面清单（与 Skills 互补：Skills 是"应该怎么做"，bug_patterns 是"不要犯的错"） |
| `feedback.py` | Agent 反馈机制 |
| `task_baseline.py` | 任务基线与必选产出物定义 |
| `worker.py` | gRPC Worker 预留（当前 STUB 状态，用于未来横向扩展） |
| `compute.proto` | gRPC 服务定义（预留） |

## 5. 全链路追踪（CallTrace）

`trace.py` 提供 `CallTrace` 和 `LLMCallRecord` 两个核心模型，记录每次会议中所有 LLM 调用的完整信息。

### LLMCallRecord 字段

| 字段 | 说明 |
|------|------|
| `call_id` | 唯一调用 ID |
| `timestamp` | 调用时间（UTC ISO 格式） |
| `stage` | 阶段名（clarify / intra_team / cross_team / evidence_check / arbitrate / produce_xxx） |
| `model` | 实际使用的模型 |
| `temperature` | 采样温度 |
| `prompt` | 完整 prompt 文本 |
| `raw_response` | LLM 原始返回 |
| `parsed_result` | Pydantic 解析后的结构化结果 |
| `validation_status` | 校验状态：`valid` / `invalid` / `fallback_stub` |
| `consistency_status` | 一致性状态：`consistent` / `inconsistent_retry` / `low_confidence` |
| `attempt` | 第几次尝试（校验重试，最多 `MAX_ATTEMPTS` 次） |
| `latency_ms` | 调用延迟（毫秒） |
| `input_tokens` / `output_tokens` / `total_tokens` | Token 消耗统计 |
| `agent_role` | 发起调用的 Agent 角色 |
| `provider_id` | 实际使用的 Provider（siliconflow / deepseek 等） |
| `error_detail` | 错误详情（HTTP 错误响应体、异常信息） |
| `request_id` / `meeting_id` / `runner_session_id` | 全链路关联 ID |

### CallTrace 能力

- **`add_call(record)`**：追加一条调用记录
- **`summary()`**：返回追踪摘要，包括：
  - 总调用数、成功率、降级数、不一致数
  - 延迟分布
  - Token 消耗统计（总输入/输出/合计）
  - 按阶段分组统计（每个阶段的调用数、成功率、降级率、延迟、token）
  - 按角色分组统计

> 仅 `RealLLM` 记录真实调用（`StubLLM` 不记录），但 `CallTrace` 对象对 stub 模式也存在（空记录）。

## 6. LLM 客户端

### 单例获取

```python
from app.agents.llm import get_llm

llm = get_llm()  # 有 API Key 返回 RealLLM，否则返回 StubLLM
```

`get_llm()` 根据 `settings.use_real_llm`（由 `CONCLAVE_USE_REAL_LLM` 环境变量控制）决定返回真实客户端还是桩客户端。`Agent` 类内部通过 `llm_mod.get_llm()` 延迟获取，保证测试 monkeypatch 能生效。

### RealLLM 核心特性

**三明治模式（结构化输出加固）**：
1. **请求层**：System message 注入对应 Pydantic 模型的 JSON Schema；传 `response_format={"type":"json_object"}`（接口不支持时自动降级为纯文本提示）
2. **解析层**：用 `schemas.py` 对应模型的 `model_validate()` 校验 LLM 返回
3. **重试层**：解析失败把 `ValidationError` 信息追加到 prompt 再次调用，最多 `MAX_ATTEMPTS` 次（由 `settings.llm_max_attempts` 配置）；全部失败则降级到 `StubLLM` 同阶段数据，保证流程不中断

**Provider 回退链**：
- 通过 `app.llm_providers.get_fallback_chain()` 获取 Provider 列表
- 连接失败（`ConnectError` / `TimeoutException`）时自动尝试下一个 Provider
- 支持会议级模型覆盖（`get_meeting_llm_config()`）和租户级覆盖（`resolve_llm_config()`）
- 配置优先级：会议级 > 租户级 > 全局默认（环境变量）

**熔断器（Circuit Breaker）**：
- 连续失败达到阈值后熔断器打开，直接跳过 LLM 调用降级到 Stub
- 恢复后自动半开探测，成功则关闭熔断器

**分阶段温度控制**：
- 温度不全局锁死，而是按阶段（`schema_hint`）查 `STAGE_TEMPERATURES` 映射
- 关键决策阶段（clarify / cross_team / evidence_check / arbitrate）温度为 **0.0**（确定性输出）
- 讨论阶段（intra_team）温度为 **0.3**（适度多样性）
- 产出阶段（produce_xxx）温度为 **0.1**（兼顾创造性和稳定性）
- 支持通过 `CONCLAVE_LLM_STAGE_TEMPERATURES` 环境变量（JSON 格式）自定义阶段温度

**其他保护机制**：
- 连接池限制（`max_connections=20`, `max_keepalive_connections=10`）
- 响应体大小保护（10MB 上限）
- Prompt 超长自动截断（`trim_prompt_to_budget`）
- 最小输出长度校验（cross_team / produce / arbitrate 阶段要求 >= 200 字符，其他阶段 >= 50 字符）
- json_mode 按 (base_url, model) 维度缓存支持情况，遇到 400 错误自动回退到纯文本模式

### StubLLM

无 API Key 或降级时使用。根据 prompt 中的阶段关键字（或 `schema_hint`）返回对应结构的假数据，保证端到端流程在无 LLM 时也能跑通，便于开发和测试。

## 7. Prompt 模板管理

### 模板组织

Prompt 模板已迁移至 `conclave_core.prompts` 模块进行编译保护（开源版编译为 `.so`/`.pyd`），`prompts.py` 作为 re-export 入口保持现有 import 路径不变。

### 模板清单

| 模板常量 | 对应阶段 | 说明 |
|---------|---------|------|
| `MODERATOR_CLARIFY` | clarify | 主持人澄清议题 |
| `ARCHITECT_INTRA` | intra_team（架构师） | 产品架构师队内发言 |
| `ENGINEER_INTRA` | intra_team（工程师） | 工程师队内发言 |
| `CROSS_TEAM` | cross_team | 跨队辩论/冲突识别 |
| `EVIDENCE_CHECK` | evidence_check | 证据核查 |
| `ARBITRATE` | arbitrate | 主持人裁决 |
| `PRODUCE` | produce（通用） | 产出物生成 |
| `PRODUCE_PRD_OPENAPI` / `PRODUCE_DESIGN_DOC` / `PRODUCE_COMPREHENSIVE` 等 | produce（具体类型） | 各类型产出物专用模板 |
| `PRODUCE_TEMPLATES` | produce | 产出模板注册表 |
| `CODE_REVIEW_PROMPT` / `CODE_FIX_PROMPT` | produce（代码类） | 代码审查/修复专用 |

### 渲染机制

`render(template, **kwargs)` 函数负责模板渲染，使用 Python `str.format()` 进行变量替换。Compute 层在构造 prompt 时通过以下步骤动态组装：

1. 取阶段基础模板（如 `MODERATOR_CLARIFY`）
2. `_inject_profile()`：注入角色画像（从 `ROLE_LIBRARY` 取 `prompt_template`，通过 `{role_persona}` 占位符注入）
3. `_inject_skills()`：注入激活的 Skill 内容（根据阶段、角色、产出类型、复杂度匹配）
4. `render()`：填充工作记忆、父约束、锁定结论等运行时变量

### IntraTeam 模板注册表

`compute.py` 使用 Registry 模式（`_INTRA_TEAM_TEMPLATES` 字典）管理角色→模板映射，消除 if/elif 硬编码分派，新增角色只需注册即可（开闭原则）。

## 8. Skills 系统

### 设计理念

Skill 是可被 Agent 动态加载的**知识/规范/偏好模块**，以 YAML 文件形式存储在 `backend/app/skills/` 目录。

与硬编码 prompt 的区别：
- **按需加载**：不相关的 Skill 不会占用 token
- **用户可定制**：用户可创建自定义 Skill 定制行为
- **可组合叠加**：一个任务可能同时激活 design + code_review + communication 多个 Skill
- **互补关系**：Skills 是"应该怎么做"（正面指南），`bug_patterns.py` 是"不要犯的错"（负面清单）

### Skill 数据结构

```python
@dataclass
class Skill:
    id: str                    # 唯一 ID，如 "ui_design_system"
    name: str                  # 人类可读名称
    description: str           # 简介
    version: int = 1
    type: str = "guideline"    # guideline / constraint / style / checklist
    applies_to: dict           # 触发条件：stages / deliverable_types / roles / complexity
    priority: int = 50         # 加载优先级（0-100），高优先级先注入
    prompt: str = ""           # 注入到 LLM prompt 的内容
    tags: list[str]            # 标签
```

### 匹配机制

`Skill.matches(stage, deliverable_type, role, complexity)` 判断此 Skill 是否在给定上下文中激活：
- `applies_to.stages` 为空或包含当前阶段 → 匹配
- `applies_to.deliverable_types` 为空或包含当前产出类型 → 匹配
- `applies_to.roles` 为空或包含当前角色 → 匹配
- `applies_to.complexity` 为空或包含当前复杂度 → 匹配

所有条件都满足时 Skill 才被激活注入。Compute 层在 `_inject_skills()` 中遍历所有已加载 Skill，按 `priority` 降序排列后拼接注入。

### 内置 Skills

内置 Skill 文件位于 `backend/app/skills/` 目录，包括但不限于：
- `ui_design_system.yaml`：UI 设计系统规范
- `code_conventions.yaml`：代码生成正面规范
- `communication_style.yaml`：Agent 发言风格（中文、方括号标签等）
- `deliverable_quality.yaml`：产出验收标准

## 9. 扩展指南

### 新增角色

1. 在 `role_templates.py` 的 `ROLE_LIBRARY` 中添加新角色条目：

```python
"new_role": RoleTemplate(
    role_id="new_role",
    display_name="新角色中文名",
    perspective="核心视角描述",
    evidence_preference="goals",       # goals / constraints / risk / policies
    risk_appetite="balanced",          # conservative / balanced / aggressive
    default_stance="xxx-first",
    prompt_template="你是XX专家。关注...决策偏置：...",
),
```

2. 在 `app/domain/enums.py` 的 `Role` 枚举中添加新枚举值：

```python
NEW_ROLE = "new_role"
```

3. 如需在 IntraTeam 阶段使用专用模板，在 `compute.py` 的 `_INTRA_TEAM_TEMPLATES` 中注册；同时更新 `_ROLE_KEY_MAP`。

4. 在 `prompts.py`（即 `conclave_core.prompts`）中添加对应的 prompt 模板（如需区别于默认模板）。

5. 在 `roles.py` 中添加便捷工厂函数（可选）：

```python
def new_role() -> Agent:
    return get_agent(Role.NEW_ROLE)
```

### 自定义 Agent 行为

**方式一：通过 AgentConfig 配置**

```python
from app.agents.agent_runtime import AgentConfig, AgentContext, AgentRuntime

config = AgentConfig(
    role="engineer",
    name="高级工程师",
    instructions="你是一位资深后端工程师，特别关注性能优化",
    output_schema="intra_team",
    tools=["web_search"],
    temperature=0.2,  # 覆盖默认温度
)
runtime = AgentRuntime(config)
```

**方式二：创建自定义 Skill**

在 `backend/app/skills/` 下新建 YAML 文件：

```yaml
id: custom_react_guide
name: React 开发规范
description: 前端 React 代码的专项规范
version: 1
type: guideline
applies_to:
  stages: ["produce"]
  deliverable_types: ["deployable_service", "design_doc"]
  roles: ["engineer"]
  complexity: ["full", "standard"]
priority: 80
prompt: |
  React 开发规范补充：
  1. 使用函数组件 + Hooks，禁止类组件
  2. 状态管理优先使用 React Context，复杂场景用 Zustand
  3. 样式使用 CSS Modules 或 Tailwind CSS
tags: ["frontend", "react"]
```

Skills 系统会在启动时自动扫描并加载该目录下所有 YAML 文件，无需手动注册。

**方式三：通过环境变量调温**

设置 `CONCLAVE_LLM_STAGE_TEMPERATURES` 环境变量自定义各阶段温度：

```json
{"clarify": 0.0, "intra_team": 0.5, "produce": 0.2}
```

**方式四：会议级/租户级模型覆盖**

- 会议级：通过 `llm_providers.set_meeting_llm_config()` 为指定会议设置模型/API Key
- 租户级：通过 `tenants.settings_override` 为租户配置默认 LLM 参数

### gRPC Worker 横向扩展（预留）

`worker.py` 预留了 gRPC Worker 模式，用于将 Agent 计算卸载到独立进程/机器。当前状态为 STUB，实现路线图：

1. 定义 protobuf（已有 `compute.proto` 草稿）
2. 生成 Python gRPC stub
3. 实现 `AgentComputeServicer`
4. Manager 端实现 `GrpcAgentCompute` 客户端（`compute.py` 已预留 Protocol）
5. 负载均衡：多 Worker 注册 + Least Loaded 调度

启动命令（当前仅运行 LocalAgentCompute 验证接口）：

```bash
python -m app.agents.worker --port 50051
```

## 10. 设计模式总结

| 模式 | 应用位置 | 目的 |
|------|---------|------|
| Facade | `AgentRuntime` / `roles.py::Agent` | 统一执行入口，隐藏内部复杂性 |
| Protocol | `LLMClient` / `Compute` | 抽象接口，支持多种实现（本地/远程/Stub） |
| Registry | `_INTRA_TEAM_TEMPLATES` / `PRODUCE_TEMPLATES` / `ROLE_LIBRARY` | 消除硬编码 if/elif，支持开闭原则扩展 |
| Singleton (缓存) | `get_agent()` / `STAGE_TEMPERATURES_CACHE` | 避免重复创建，缓存解析结果 |
| Strategy | 角色决策偏置（不同角色不同 risk_appetite / evidence_preference） | 同一接口不同行为 |
| Circuit Breaker | `_circuit_breaker`（llm.py） | 故障快速恢复，防止级联失败 |
| Chain of Responsibility | Provider 回退链 | 一个 Provider 失败自动尝试下一个 |
| Sandwich Pattern | RealLLM.complete() | 请求层 Schema + 解析层校验 + 重试层兜底 |
