# 多 LLM 协同审计架构说明

## 1. 设计目标

消除单个 LLM 在代码审计和质证中的偏见和盲区，通过跨模型族交叉验证提高审计可信度。

**理论基础**（Verification Design Principles [$TRAE_REF](https://github.com/verificationdesign/verificationdesign/blob/main/verification_design.md)）：

- LLM 无法可靠地自我纠正（Huang et al., ICLR 2024 [$TRAE_REF](https://arxiv.org/abs/2310.01798)）
- 跨模型族验证优于自验证（同一模型族的验证器与生成器共享盲区）
- 可执行验证（grep/测试/lint）不受模型偏见影响
- 谄媚率 58-78%——确认性框架不可靠

## 2. Trae 平台能力支撑

### 2.1 Skill 机制

Skill 通过 `SKILL.md` 定义，动态按需加载 [$TRAE_REF](https://docs.trae.cn/ide_skills)。Skill 负责：
- 定义审计流程和质证标准（"怎么做"）
- 不指定模型（"谁来做"由 Subagent 决定）
- 在 auto mode 下由 AI 自动调用

### 2.2 Subagent 机制

Subagent 通过 Markdown 文件定义，拥有独立上下文窗口 [$TRAE_REF](https://docs.trae.cn/ide_subagents)。关键能力：
- `model` 字段可指定 15 种内置模型（DeepSeek-V4-Pro、MiniMax-M3、GLM-5.2、Qwen3.7-Plus 等）
- `tools` 字段可限定工具权限（Read/Glob/Grep = 只读审计）
- 独立上下文窗口，不污染主对话历史
- 由内置 Agent 自动委派调用

### 2.3 Auto Mode

Auto 模式下系统综合调用合适的内置模型 [$TRAE_REF](https://docs.trae.cn/ide_auto-mode)。但 Auto 模式**仅调用内置模型，不调用自定义模型**。这意味着：
- 多模型审计依赖 Subagent 的 `model` 字段指定不同模型
- 不能使用自定义接入的模型进行交叉审计

## 3. 架构设计

### 3.1 三层架构

```
┌─────────────────────────────────────────────────────┐
│  Skill 层（流程定义，不指定模型）                      │
│  ┌─────────────────┐ ┌──────────────────┐ ┌───────┐ │
│  │ conclave-audit  │ │audit-cross-verify│ │state- │ │
│  │ (审计流程标准)   │ │ (质证流程标准)    │ │check  │ │
│  └────────┬────────┘ └────────┬─────────┘ └───┬───┘ │
└───────────┼───────────────────┼───────────────┼─────┘
            │                   │               │
            ▼                   ▼               ▼
┌─────────────────────────────────────────────────────┐
│  Subagent 层（模型指定，独立执行）                     │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐         │
│  │audit-     │ │audit-     │ │audit-     │         │
│  │deepseek   │ │minimax    │ │glm        │         │
│  │DeepSeek-  │ │MiniMax-M3 │ │GLM-5.2    │         │
│  │V4-Pro     │ │           │ │           │         │
│  └───────────┘ └───────────┘ └───────────┘         │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐         │
│  │verify-    │ │verify-    │ │state-     │         │
│  │deepseek   │ │qwen       │ │checker    │         │
│  │DeepSeek-  │ │Qwen3.7-   │ │DeepSeek-  │         │
│  │V4-Pro     │ │Plus       │ │V4-Flash   │         │
│  └───────────┘ └───────────┘ └───────────┘         │
└─────────────────────────────────────────────────────┘
            │                   │
            ▼                   ▼
┌─────────────────────────────────────────────────────┐
│  编排层（主智能体裁定）                                │
│  - 对比多模型结果差异                                  │
│  - 争议项裁定（grep 证据优先）                         │
│  - 生成最终报告                                        │
└─────────────────────────────────────────────────────┘
```

### 3.2 交叉审计流程

```
用户请求审计
    │
    ▼
conclave-audit skill 触发
    │
    ├──→ 调用 audit-deepseek subagent（DeepSeek-V4-Pro）
    │     └→ 独立执行后端审计 → 返回结果 A
    │
    ├──→ 调用 audit-minimax subagent（MiniMax-M3）
    │     └→ 独立执行前端审计 → 返回结果 B
    │
    └──→ 调用 audit-glm subagent（GLM-5.2）
          └→ 独立执行安全审计 → 返回结果 C
    
    主智能体汇总 A+B+C
    │
    ├── 一致项 → 高置信度结论（直接采纳）
    ├── 差异项 → 标记为"争议项"
    │     └── 对争议项执行 grep 补充核验
    └── 生成最终审计报告
```

### 3.3 交叉质证流程

```
用户收到外部审计报告
    │
    ▼
audit-cross-verify skill 触发
    │
    ├── 解析报告，提取 42 条事实性声明
    │
    ├──→ 调用 verify-deepseek subagent（DeepSeek-V4-Pro）
    │     └→ 独立 grep 核验 42 条 → 返回质证结果 X
    │
    └──→ 调用 verify-qwen subagent（Qwen3.7-Plus）
          └→ 独立 grep 核验 42 条 → 返回质证结果 Y
    
    主智能体对比 X 和 Y
    │
    ├── 两者一致 → 高置信度判定
    ├── 两者不一致 → 标记为"争议项"
    │     └── 执行补充 grep 核验裁定
    └── 生成质证报告（含审查漂移分析）
```

## 4. 文件清单

### 4.1 Skill 文件（.trae/skills/）

| 文件 | 功能 |
|------|------|
| `conclave-audit/SKILL.md` | 系统审计流程标准 |
| `audit-cross-verify/SKILL.md` | 审计质证流程标准 |
| `orchestrator-state-check/SKILL.md` | 编排器状态机验证规则 |

### 4.2 Subagent 文件（.trae/agents/）

| 文件 | 模型 | 职责 |
|------|------|------|
| `audit-deepseek.md` | DeepSeek-V4-Pro | 后端代码审计 |
| `audit-minimax.md` | MiniMax-M3 | 前端代码/UI 审计 |
| `audit-glm.md` | GLM-5.2 | 安全审计 |
| `verify-deepseek.md` | DeepSeek-V4-Pro | 后端声明质证 |
| `verify-qwen.md` | Qwen3.7-Plus | 前端/配置声明质证 |
| `state-checker.md` | DeepSeek-V4-Flash | 状态机快速检查 |

## 5. 使用方式

### 5.1 单模型审计（默认）

直接在对话中说：
```
对后端执行深度审计
```
conclave-audit skill 自动触发，主智能体执行审计。

### 5.2 多模型交叉审计

```
用多模型交叉审计后端，重点关注多租户隔离
```
conclave-audit skill 触发后，自动调用 audit-deepseek、audit-minimax、audit-glm 三个 subagent。

### 5.3 审计质证

```
质证 docs/audits/Deep-Seek-V4-Pro-system-audit-2026-07-19.html
```
audit-cross-verify skill 触发，逐条 grep 核验。

### 5.4 多模型交叉质证

```
交叉质证这份审计报告，用多个模型验证
```
audit-cross-verify skill 触发后，调用 verify-deepseek 和 verify-qwen 两个 subagent。

### 5.5 编排器状态检查

```
检查编排器状态机
```
orchestrator-state-check skill 触发，扫描状态赋值链。

## 6. 设计约束与局限

### 6.1 平台约束

- **Subagent 串行执行**：Trae 的 Agent 串行委派 Subagent，无并行 API。三个审计 subagent 是串行执行的，不是并行的。
- **仅内置模型**：Subagent 的 `model` 字段仅支持 15 种内置模型，不支持自定义接入的模型。
- **Subagent 仅被 Agent 调用**：Subagent 不能被 Skill 直接调用，只能由内置 Agent 在匹配 description 后委派。

### 6.2 设计权衡

- **Skill 不指定模型**：Skill 是"能力说明书"，模型选择由 Subagent 决定。这保证了 Skill 的通用性——同一套审计流程可以搭配不同模型使用。
- **grep 证据优先于模型投票**：当三个模型结果不一致时，不以 2:1 投票裁定，而是以 grep 证据为准。这避免了"多数模型都错"的情况。
- **独立执行**：Subagent 之间不查看彼此结果，确保验证的独立性。这是 Verification Design Principles 的核心要求。

### 6.3 已知局限

- **无法并行执行**：三个 subagent 串行执行，总耗时 = 模型 A + 模型 B + 模型 C。如果每个 2 分钟，总计 6 分钟。
- **无法共享上下文**：Subagent 有独立上下文窗口，无法共享中间发现。每个 subagent 独立扫描全部代码。
- **模型可用性依赖平台**：如果某个内置模型暂时不可用，对应 subagent 无法执行。建议至少配置 2 个模型族作为冗余。

## 7. 理论依据

本架构设计严格遵循 Verification Design Principles [$TRAE_REF](https://github.com/verificationdesign/verificationdesign/blob/main/verification_design.md)：

| 原则 | 本架构的实现 |
|------|-------------|
| External Signals Over Self-Review | grep/测试/lint 作为主验证手段，LLM 判断为辅 |
| Independence Between Generation and Verification | Subagent 独立执行，不查看其他模型结果 |
| Step-Level Checkpoints | 审计按维度分步执行，每步有独立验证 |
| Adversarial Framing | Skill 指令中使用"哪里可能出错？"框架 |
| Explicit Criteria | 每条检测规则有具体的 grep 命令和判定标准 |
| Executable Verification Is King | grep 命令是可执行的二元 pass/fail 信号 |
| Cross-Family Beats Self-Verification | 三个不同模型族（DeepSeek/MiniMax/GLM）交叉验证 |
| Simulate Debate | 争议项由主智能体裁定，模拟对抗性辩论 |
