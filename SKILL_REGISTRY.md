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

### 项目专属 Skill（`.trae/skills/`）

| Skill | 触发关键词 | 触发场景 | 错误信号 | 调用时机 |
|-------|-----------|----------|----------|----------|
| `baseline-runner` | 跑基线、跑测试、换模型测试、对比上次、基线测试 | 需要执行 Tier1/2/3 评估测试、切换 LLM 模型后重跑、对比历史结果 | — | 测试前 |
| `eval-report-builder` | 生成报告、分析结果、对比测试、给我看数据、分析报告 | 基线测试完成后、需要多轮对比可视化 | — | 测试后 |
| `provider-diagnostic` | LLM 挂了、API 不通、输出是空的、余额不足 | LLM 调用失败、会议产出为空 | total_tokens=0, HTTP 429/402, StubLLM, latency<5s | 故障时 |
| `session-checkpoint` | 存档、保存进度、checkpoint、继续、恢复、上次说到哪了 | 阶段性完成、切换窗口前、新会话恢复 | — | 按需 |
| `conclave-audit` | 系统审计、代码审查、架构债、安全扫描 | 大版本合并后、安全修复后、架构重构后 | — | 按需 |
| `audit-cross-verify` | 交叉质证、核验审查报告、验证评审意见 | 收到外部审计报告、AI 生成的评估报告 | — | 收到报告时 |
| `orchestrator-state-check` | 阶段被跳过、阶段重复、质量门禁不执行、终态错误 | 修改编排器代码（runner.py、stage_runners.py、nodes/） | state.stage/status 赋值冲突 | 改编排器时 |

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
