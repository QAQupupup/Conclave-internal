# Conclave Skill Registry — 技能索引

> **本文件是 AI 助手自动发现和调用 Skill 的入口。**
> AI 助手在每次对话开始时应扫描本文件，根据当前任务自动决定是否调用相关 Skill。
> **用户不需要主动提及 Skill 名称——AI 应基于任务上下文自动触发。**
>
> 位置：`SKILL_REGISTRY.md`（项目根目录，与 AGENTS.md 同级）
> Skill 目录：`.trae/skills/<skill-name>/SKILL.md`

---

## 自动触发规则

AI 助手在以下情况应**主动**检查并调用对应 Skill，无需用户提示：

1. **任务关键词匹配**：用户消息中出现下表"触发关键词"时
2. **上下文模式匹配**：当前工作内容匹配"触发场景"时
3. **错误信号匹配**：遇到下表"错误信号"时

**调用方式**：通过 `Skill` 工具，传入 skill name（不含路径）。

---

## Skill 列表

### 会议内 Skill（`backend/app/skills/*.yaml`，运行时自动加载）

会议内 Skill 是 YAML 格式的 prompt 约束模块，由编排器在会议运行时根据 stage/deliverable_type/role/complexity 自动匹配加载，通过 priority 排序后注入 LLM prompt。用户无需手动调用。

| Skill ID | 名称 | priority | applies_to | 用途 |
|----------|------|----------|------------|------|
| `ui_design_system` | UI设计系统 | 90 | produce / deployable_service,design_doc / engineer,ux_designer | 色彩/排版/布局/Impeccable反模式/前端红线 |
| `prd_traceability` | PRD溯源与质量约束 | 90 | clarify,produce / prd_openapi / product_architect,clarifier | PRD输入历史追加、SMART标准、P0/P1/P2分级、source_quotes溯源 |
| `code_conventions` | 代码生成规范 | 85 | produce,review,bugfix / code_analysis,tested_system,deployable_service / engineer | 代码质量正面规范(安全/DDL/API/Docker) |
| `code_review` | 代码安全审查指南 | 80 | produce / deployable_service,tested_system,code_analysis / security_expert | OCR结果解读、漏洞分级、修复建议 |
| `async_safety` | 异步代码安全指南 | 90 | produce,review / backend_service,fullstack_app,api_service,tested_system / engineer,security_expert | async阻塞/超时/任务泄漏/锁/DB会话/事件循环坑 |
| `audit_invariants` | 语义安全审计不变量 | 85 | produce / backend_service,fullstack_app,api_service,tested_system,code_analysis / security_expert | 30条语义级安全不变量(多租户/async/授权/注入/一致性) |
| `task_decomposition` | 任务分解规范 | 80 | produce / prd_openapi,design_doc,deployable_service,tested_system,code_analysis / product_architect,engineer | specify→plan→tasks三段式分解(standard/full复杂度) |
| `communication_style` | 沟通风格规范 | 80 | clarify,intra_team,cross_team,evidence_check,arbitrate / (all) / (all) | 中文发言格式、方括号标签、内容质量 |
| `deliverable_quality` | 产出质量验收 | 75 | review,arbitrate,produce / (all) / moderator,engineer | 产出验收checklist、严重等级定义 |

### 项目专属 Skill（`.trae/skills/`，运维/开发辅助）

| Skill | 触发关键词 | 触发场景 | 错误信号 | 调用时机 |
|-------|-----------|----------|----------|----------|
| `baseline-runner` | 跑基线、跑测试、换模型测试、对比上次、基线测试 | 需要执行 Tier1/2/3 评估测试、切换 LLM 模型后重跑、对比历史结果 | — | 测试前 |
| `eval-report-builder` | 生成报告、分析结果、对比测试、给我看数据、分析报告 | 基线测试完成后、需要多轮对比可视化 | — | 测试后 |
| `provider-diagnostic` | LLM 挂了、API 不通、输出是空的、余额不足 | LLM 调用失败、会议产出为空 | total_tokens=0, HTTP 429/402, StubLLM, latency<5s | 故障时 |
| `session-checkpoint` | 存档、保存进度、checkpoint、继续、恢复、上次说到哪了 | 阶段性完成、切换窗口前、新会话恢复 | — | 按需 |
| `conclave-audit` | 系统审计、代码审查、架构债、安全扫描 | 大版本合并后、安全修复后、架构重构后 | — | 按需 |
| `audit-cross-verify` | 交叉质证、核验审查报告、验证评审意见 | 收到外部审计报告、AI 生成的评估报告 | — | 收到报告时 |
| `audit-remediation` | 审计报告修复、验证并修复、分析并修、fix audit | 收到审计报告后需要独立验证 + 实际代码修复 | 审计报告中的 P0/P1 问题需要修复 | 收到报告+需修复时 |
| `orchestrator-state-check` | 阶段被跳过、阶段重复、质量门禁不执行、终态错误 | 修改编排器代码（runner.py、stage_runners.py、nodes/） | state.stage/status 赋值冲突 | 改编排器时 |
| `hardcode-check` | 检查硬编码、巡检硬编码、hardcode check、硬编码扫描 | 提交前自检、代码审计、收到硬编码相关评审意见 | grep 发现 password/secret/token 硬编码、温度魔法数字 | 提交前/审计时 |

### 内置通用 Skill（平台提供）

| Skill | 触发场景 | 调用时机 |
|-------|----------|----------|
| `html-report` | 生成 HTML 报告/白皮书/PRD/仪表盘 | `eval-report-builder` 内部使用，或独立生成文档时 |
| `html-deck` | 生成 HTML 幻灯片/演示文稿 | 用户要求创建演示文稿时 |
| `docx` | 生成/编辑 Word 文档 | 用户明确要求 .docx 格式时 |
| `pptx` | 生成/编辑 PPT 演示文稿 | 用户明确要求 .pptx 格式时 |
| `pdf` | 处理 PDF 文件 | 用户需要 PDF 操作时 |
| `xlsx` | 处理 Excel/CSV 表格 | 用户需要电子表格操作时 |
| `skill-creator` | 创建新 Skill | 用户要求创建新 skill 时 |
| `research-guide` | 研究/调研/竞品分析 | 用户要求调研某主题时 |
| `doc-writing-guide` | 写文档/PRD/规格说明 | 用户要求写结构化文档时 |

---

## Skill 间的协作链

常见工作流中多个 Skill 会串联使用：

```
基线测试全流程:
  baseline-runner → eval-report-builder → session-checkpoint

Provider 故障处理:
  provider-diagnostic → (修复后) baseline-runner

代码审计后修复:
  conclave-audit → (修复) → audit-cross-verify (核验)

编排器修改:
  orchestrator-state-check → (修复) → session-checkpoint
```

---

## Skill 维护规则

1. **新增 Skill 后**：必须在本文件添加一行到"项目专属 Skill"表
2. **Skill 废弃后**：从表中移除，并在 `.trae/skills/` 下创建 `DEPRECATED.md` 说明原因
3. **触发关键词变更**：同步更新本文件的"触发关键词"列
4. **本文件位置**：始终在项目根目录，与 `AGENTS.md` 同级，确保 AI 助手首次扫描时能发现
5. **AGENTS.md 引用**：AGENTS.md §0 第 2 步应包含"读 `SKILL_REGISTRY.md` 了解可用 Skill"
