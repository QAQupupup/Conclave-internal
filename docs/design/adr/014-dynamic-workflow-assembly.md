# ADR-014: 动态工作流编排与议题拆分

## 状态

Accepted — 2026-07-29（Phase 1/2/3 全部实现完成）

## 背景

### 问题历史

当前 Conclave 编排器采用"固定六阶段管线 + 约束内动态路由"架构（ADR-013）。在实际测试和用户反馈中暴露以下系统性缺陷：

1. **角色画像过于简短**：每个角色的 `prompt_template` 仅 30-60 字（`role_templates.py:26-104`），缺乏行业方法论、思考框架和产出质量标准。导致 LLM 发言简短无力，不符合专业角色预期。

2. **IntraTeam 模板覆盖不足**：`_INTRA_TEAM_TEMPLATES`（`compute.py:35-38`）仅注册了 2 个角色（engineer + product_architect），其余 5 个角色全部回退到 `ARCHITECT_INTRA` 模板，导致安全专家被要求从"产品与架构视角"给论点。

3. **固定管线无法适应多样化议题**：`STAGE_ORDER`（`state.py:406-413`）是硬编码六阶段列表。商业分析、可部署服务、调研报告等不同类型的议题走同一条管线，无法按议题类型定制阶段序列。

4. **不支持议题拆分**：`grep -r "topic_decompos|subtask_graph|decompose_topic|subtopic|议题拆分" backend/` 零命中。复杂议题（如"分析商业报告"）无法拆分为子议题图结构并行处理。

5. **`_ROLE_KEY_MAP` 缺少 marketing_expert**：`compute.py:41-48` 的映射表只有 6 个条目，缺 `marketing_expert`（隐性依赖 fallback 工作）。

### 代码核验

```
# 角色画像长度核验
grep -c "prompt_template" backend/app/agents/role_templates.py  # 7 个角色
# 每个画像 30-60 字，无方法论/框架/清单

# IntraTeam 模板覆盖核验
grep "_INTRA_TEAM_TEMPLATES" backend/app/agents/compute.py  # 仅 2 个角色

# 议题拆分能力核验
grep -r "topic_decompos|subtask_graph|decompose_topic" backend/  # 零结果

# 固定管线核验
grep "STAGE_ORDER" backend/conclave_core/state.py  # 硬编码六阶段
```

### 约束

- **设计原则 7（反架构沉迷）**：高级抽象只做最薄接口，先跑通主闭环再以插件方式引入
- **设计原则 8（演进式架构）**：极简内核先验证全部核心链路→逐步把终态特性作为插件装上去
- **ADR-013 契约**：阶段 runner 只设 `state.stage`，终态由 Runner 设置；元认知路由在六阶段白名单内决策
- **向后兼容**：现有六阶段管线必须作为默认工作流模板保留，不能破坏已有测试

## 决策

### 1. 三层架构：议题拆分 → 工作流模板 → 阶段执行

```
用户议题
    │
    ▼
[Layer 1] 议题拆分器（Topic Decomposer）
    │  将复杂议题拆分为子议题 DAG
    │  每个子议题标注类型（analysis/design/build/research）
    │  子议题间可声明依赖关系
    │
    ▼
[Layer 2] 工作流模板选择器（Workflow Template Selector）
    │  根据议题/子议题类型选择工作流模板
    │  模板定义阶段序列 + 角色组合 + 产出格式
    │  默认模板 = 现有六阶段管线（向后兼容）
    │
    ▼
[Layer 3] 阶段执行引擎（Stage Execution Engine）— 复用现有
    │  Planner → Scheduler → Reducer → StageRunner
    │  质量门禁 + 动态路由（ADR-013 不变）
    │
    ▼
[Aggregator] 子议题结果聚合器（Result Aggregator）
    │  将各子议题产出聚合为最终交付物
```

### 2. 议题拆分器（Layer 1）

**数据模型**：

```python
class SubTopic(BaseModel):
    """子议题节点"""
    id: str                          # 子议题 ID
    title: str                       # 子议题标题
    topic_type: str                  # analysis | design | build | research | report
    key_questions: list[str]         # 子议题的关键问题
    depends_on: list[str]            # 依赖的其他子议题 ID
    assigned_roles: list[str]        # 建议参与角色
    workflow_template: str           # 使用的工作流模板 ID（default = "standard"）

class TopicDecomposition(BaseModel):
    """议题拆分结果"""
    root_topic: str                  # 原始议题
    subtopics: list[SubTopic]        # 子议题列表（DAG 节点）
    edges: list[tuple[str, str]]     # 依赖边 (from_id, to_id)
    aggregation_strategy: str        # 聚合策略：sequential | parallel | hierarchical
```

**拆分时机**：clarify 阶段结束后，若 `complexity == "full"`，调用 LLM 执行议题拆分。`simple`/`standard` 跳过拆分，直接走默认管线。

**拆分约束**：
- 最多 5 个子议题（防止过度拆分）
- DAG 必须无环（拓扑排序校验）
- 每个子议题必须可独立执行
- 依赖链深度不超过 3 层

### 3. 工作流模板系统（Layer 2）

**工作流模板定义**：

```python
class WorkflowTemplate(BaseModel):
    """工作流模板：定义阶段序列 + 角色组合 + 产出格式"""
    template_id: str                 # 模板 ID
    description: str                 # 适用场景描述
    stages: list[str]                # 阶段序列（如 ["clarify", "intra_team", "produce"]）
    default_roles: list[str]         # 默认角色组合
    produce_type: str                # 产出类型（prd_openapi | deployable_service | ...）
    quality_dimensions: list[str]    # 质量评估维度
```

**内置模板**：

| template_id | 适用场景 | 阶段序列 | 默认角色 | 产出类型 |
|---|---|---|---|---|
| `standard` | 通用议题（默认，向后兼容） | clarify → intra_team → cross_team → evidence_check → arbitrate → produce | architect + engineer | 按议题匹配 |
| `instant` | 纯知识问答 | (无阶段，单次 LLM) | moderator | text |
| `design` | 架构设计类 | clarify → intra_team → produce | architect + engineer + security | design_doc |
| `build` | 可部署服务 | clarify → intra_team → cross_team → produce | architect + engineer + security + data | deployable_service |
| `research` | 调研报告类 | clarify → intra_team → produce | architect + marketing | research_report |
| `analysis` | 商业分析类 | clarify → intra_team → cross_team → arbitrate → produce | architect + marketing + data | business_report |

**模板选择规则**：
1. clarify 阶段的 LLM 输出 `complexity` 字段映射到模板：`simple` → `instant`，`standard` → `standard`，`full` → 按议题类型选择 `design`/`build`/`research`/`analysis`
2. 用户可在创建会议时显式指定 `workflow_template` 覆盖自动选择
3. 议题拆分器的每个子议题可指定不同模板

### 4. 增强角色画像体系

每个角色从"1-2 句话描述"升级为"四维画像"：

| 维度 | 内容 | 示例（安全专家） |
|---|---|---|
| **核心视角** | 角色关注的核心维度 | 认证、授权、数据安全、注入防护 |
| **方法论框架** | 行业标准方法论和思考框架 | OWASP Top 10、STRIDE 威胁建模、最小权限原则 |
| **产出检查清单** | 该角色视角的质量检查项 | AuthN/AuthZ 方案、注入防护、数据加密、审计日志 |
| **协作边界** | 与其他角色的协作分工 | 安全方案由安全专家主导，工程师负责实现，架构师负责接口 |

**可部署服务角色协作矩阵**：

| 产出阶段 | 架构师 | 工程师 | 安全专家 | 数据工程师 |
|---|---|---|---|---|
| PRD | 主导 | 约束 | 安全需求 | 数据需求 |
| ADR | 主导 | 评估 | 安全评估 | 数据评估 |
| OpenAPI | 主导 | 评估 | 安全约束 | — |
| 后端分层 | 接口层 | 主导 | 安全层 | 数据层 |
| Auth2.0 | 接口设计 | 实现 | 主导 | — |
| 数据模型 | 约束 | 评估 | — | 主导 |
| 测试策略 | 验收标准 | 主导 | 安全测试 | 数据测试 |
| 部署方案 | 架构约束 | 主导 | 安全加固 | 数据迁移 |

### 5. IntraTeam 模板全角色覆盖

为 7 个角色各自提供专用 IntraTeam 模板，消除"5 个角色回退到架构师模板"的问题：

| 角色 | 模板视角关键词 | 特有字段 |
|---|---|---|
| product_architect | 价值边界、接口约束、MVP 范围 | — |
| engineer | 可行性、实现风险、测试边界 | risk_level |
| security_expert | 威胁建模、攻击面、安全约束 | risk_level, threat_category |
| data_engineer | 数据模型、存储策略、一致性 | risk_level, data_impact |
| ux_designer | 用户旅程、可用性、错误处理 | — |
| marketing_expert | 市场定位、增长策略、商业可行性 | — |
| moderator | 流程合规、冲突暴露、 completeness | — |

### 6. 演进式实施路径

遵循设计原则 7/8，分三个阶段实施：

**Phase 1（已完成, commit 467dfdc）— 角色画像增强 + IntraTeam 全覆盖**
- 增强 `ROLE_LIBRARY` 中 7 个角色的 `prompt_template`（补充方法论/框架/清单）
- 为 7 个角色各自创建专用 IntraTeam 模板
- 修复 `_ROLE_KEY_MAP` 缺失 `marketing_expert`
- **不改变编排流程**，仅提升发言质量

**Phase 2（已完成, commit 45c6f6b）— 工作流模板系统**
- 实现 `WorkflowTemplate` 数据模型和 `WORKFLOW_TEMPLATES` 注册表
- clarify 阶段输出 `topic_type` 字段，`complexity_to_template()` 映射到模板
- Runner 根据模板选择阶段序列，替代固定 `STAGE_ORDER`
- 默认模板 = 现有六阶段（向后兼容）
- 28 个测试用例覆盖模板注册、阶段序列、向后兼容

**Phase 3（已完成, commit c4d10ff）— 议题拆分器**
- 实现 `TopicDecomposition` 数据模型（SubTopic + DAG + 聚合策略）
- clarify 后对 `full` 复杂度+非 standard 模板执行拆分
- DAG 校验：无环检测、深度限制（≤3）、子议题数限制（≤5）
- 子议题各自走工作流模板，runner 支持子议题迭代执行
- 聚合器实现 sequential/hierarchical 策略
- 30+ 测试用例覆盖 DAG 校验、拓扑排序、结果聚合、序列化

## 备选方案

### 方案 A（已选择）：三层架构 + 演进式实施

在现有架构上增加议题拆分和工作流模板层，保留六阶段管线作为默认模板。分三阶段实施，Phase 1 仅增强角色画像（零风险），Phase 2/3 逐步引入动态能力。

**选择理由**：
- 符合设计原则 7/8（薄接口先行，演进式架构）
- Phase 1 立即可见效果（发言质量提升），零架构风险
- 向后兼容（默认模板 = 现有六阶段）
- 每个阶段都有可验证产物

### 方案 B（未选择）：完全重写编排器

废弃现有 `STAGE_ORDER` + `Runner.run` 主循环，用完全动态的 DAG 引擎替代。

**未选择理由**：
- 违反设计原则 7（反架构沉迷）
- 改动范围过大（runner.py 700+ 行重写）
- 破坏所有现有测试
- 无法增量验证

### 方案 C（未选择）：仅增强角色画像，不引入动态工作流

只做 Phase 1（角色画像增强），不实施工作流模板和议题拆分。

**未选择理由**：
- 用户明确要求"大刀阔斧优化"
- 固定管线无法适应多样化议题类型
- 不支持议题拆分，复杂议题处理能力受限
- 但 Phase 1 作为第一步是正确的

## 影响 / 迁移

### Phase 1 文件变更

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `backend/app/agents/role_templates.py` | 修改 | 增强 7 个角色的 prompt_template（补充方法论/框架/清单） |
| `backend/conclave_core/prompts.py` | 修改 | 新增 5 个角色的专用 IntraTeam 模板 |
| `backend/app/agents/compute.py` | 修改 | `_INTRA_TEAM_TEMPLATES` 注册全 7 角色；`_ROLE_KEY_MAP` 补 marketing_expert |

### Phase 2 文件变更（已完成, commit 45c6f6b）

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `backend/app/orchestrator/workflow_templates.py` | 新增 | WorkflowTemplate 模型 + WORKFLOW_TEMPLATES 注册表 + next_stage_with_template() |
| `backend/app/orchestrator/runner.py` | 修改 | 根据模板选择阶段序列（get_stage_sequence） |
| `backend/app/domain/meeting.py` | 修改 | MeetingState 新增 workflow_template 字段 |
| `backend/conclave_core/prompts.py` | 修改 | clarify 模板新增 topic_type 输出 |
| `backend/app/orchestrator/stage_runners.py` | 修改 | complexity_to_template() 选择模板 |
| `backend/app/orchestrator/nodes/routing.py` | 修改 | next_stage_with_template() 替代 next_stage() |
| `backend/tests/test_workflow_templates.py` | 新增 | 28 个测试用例 |

### Phase 3 文件变更（已完成, commit c4d10ff）

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `backend/app/orchestrator/topic_decomposer.py` | 新增 | 议题拆分器（SubTopic + TopicDecomposition + DAG校验 + LLM拆分） |
| `backend/app/orchestrator/result_aggregator.py` | 新增 | 子议题结果聚合器（sequential/hierarchical 策略） |
| `backend/app/domain/meeting.py` | 修改 | MeetingState 新增 topic_decomposition/subtopic_results/current_subtopic_idx |
| `backend/app/orchestrator/stage_runners.py` | 修改 | run_clarify 集成 decompose_topic() |
| `backend/app/orchestrator/runner.py` | 修改 | produce 后子议题迭代 + 聚合上下文注入 |
| `backend/tests/test_topic_decomposer.py` | 新增 | 30+ 测试用例（DAG校验/拓扑排序/聚合/序列化） |

### 不受影响

- ADR-013 状态机契约（阶段 runner 权责不变）
- 质量门禁逻辑（cross_team ADR-010 门禁 + produce 质量评分）
- 熔断器/provider 回退链/JSON 提取管线
- 前端 WebSocket 事件协议

## 验证方式

### Phase 1 验证

```bash
# 1. 角色画像长度验证
grep "prompt_template" backend/app/agents/role_templates.py
# 每个画像应 > 200 字，包含方法论/框架/清单

# 2. IntraTeam 模板覆盖验证
grep "_INTRA_TEAM_TEMPLATES" backend/app/agents/compute.py
# 应有 7 个角色注册

# 3. _ROLE_KEY_MAP 完整性
grep "marketing_expert" backend/app/agents/compute.py
# 应出现在 _ROLE_KEY_MAP 中

# 4. Docker 容器内测试
docker exec conclave-dev-backend sh -c "cd /app && python -m pytest tests/test_role_library.py tests/test_json_extraction.py -v"

# 5. StubLLM 端到端验证
docker exec conclave-dev-backend sh -c "cd /app && python -m pytest tests/test_e2e_refactor.py -v"
```

## 参考

- AGENTS.md §4.16（文档真实性核查）、§4.17（问题评估与绕过检查）
- ADR-013：编排器状态机契约
- ADR-010：论点提纯架构与证据诚实性
- `docs/design/design-principles.md`：原则 7（反架构沉迷）、原则 8（演进式架构）
- `backend/app/agents/role_templates.py`：角色模板库
- `backend/app/agents/compute.py:35-66`：IntraTeam 模板注册表 + 角色映射
- `backend/conclave_core/prompts.py:27-51`：现有 IntraTeam 模板（仅 2 个）
- `backend/conclave_core/state.py:406-413`：STAGE_ORDER 固定六阶段
