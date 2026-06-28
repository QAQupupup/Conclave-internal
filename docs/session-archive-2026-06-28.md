# Conclave 会话归档：2026-06-28

> 本文记录本次会话的关键沟通、决策与规划，用于后续回溯。
> 配合 [`optimization-backlog.md`](./optimization-backlog.md)（代码优化待办）和 [`iteration-2-design.md`](./iteration-2-design.md)（迭代二设计）使用。

---

## 1. 会话脉络

本次会话围绕"设计模式优化 → 产品质量缺口修复 → 三阶段升级规划"展开，逐步从代码质量推进到系统能力升级。

### 1.1 设计模式优化（已完成，4 commit）

对照 [`design-principles.md`](./design-principles.md) 审查代码，完成 4 个分组 commit：

| Commit | 分组 | 设计模式 | 净行数 |
|---|---|---|---|
| `7644d71` | 前端 hooks/utils 抽象 | DRY + 单一职责 + 适配器 | -30 |
| `ca969f0` | 前端常量统一 | Registry 单一数据源 | +50 |
| `01b3e53` | 后端 agents 角色分派 | Facade + Registry + 策略模式 | -58 |
| `f87da58` | 后端 orchestrator 信号分派 | 命令模式 + Registry | +18 |

剩余优化项归档到 [`optimization-backlog.md`](./optimization-backlog.md)（21 项，按 P0/P1/P2 分级）。

### 1.2 产品质量缺口修复（已完成，1 commit）

修复了影响实际使用的三大缺口（`8a2209b`）：

1. **claims 数据流断裂**：Schema 改必填 + LLM 空检查强制重试 + 前端采纳高亮匹配修正
2. **intra_team 消息压缩**：借调角色接真实 LLM + 消息存可读文本替代裸 JSON
3. **evidence 全中立**：Schema 加 strength 字段 + prompt 弱证据分支 + 无文档时生成双方向证据

### 1.3 三阶段升级规划（确立方向，用户确认）

基于用户提出的真实场景需求（数据调研 + 商业报告 + 可运行程序），诊断出系统能力差距，确立三阶段升级路线。

---

## 2. 系统能力诊断（2026-06-28）

用户提出真实场景需求，经调研确认以下能力边界：

### 2.1 任务并行调度

| 维度 | 现状 | 满足"自动并行无依赖任务" |
|---|---|---|
| intra_team | N-1 并行 + 1 react，硬编码 | 部分（LLM 并行，非通用） |
| evidence_check | 冲突级 gather 并行 | 部分 |
| produce | 纯串行单 LLM | 不满足 |
| DAG/任务图 | 无，固定六阶段线性 | 不满足 |
| 跨阶段 | prefetch 被 await 阻塞 | 不满足 |

**结论**：当前架构无法自动并行无依赖任务，需引入 DAG 任务图 + 调度器（阶段三）。

### 2.2 沙箱代码执行

| 能力 | 现状 |
|---|---|
| 沙箱环境 | Docker sibling 容器，python:3.12-slim 裸镜像 |
| 数据分析库 | ❌ 无 pandas/numpy/matplotlib/scikit-learn |
| pip install | ❌ --network none 全程断网 |
| 资源限制 | 256MB 内存，15-30s 超时 |
| 多文件 | 部分（tested_system 双文件） |
| 附件回传 | ❌ 仅 stdout/stderr 文本 |

### 2.3 产出能力

| 能力 | 现状 |
|---|---|
| 产出模板 | 7 种（PRD/设计文档/综合文档/调研报告/商业报告/代码分析/测试系统） |
| 渐进式产出 | ❌ 一次性 deliverable_type，不支持多轮决策 |
| Docker 镜像生成 | ❌ 完全没有 |
| 附件体系 | ❌ 无二进制文件存储/传输/下载链路 |

---

## 3. 三阶段升级规划

### 阶段一：RAG 升级（最高优先级）

**目标**：提升证据检索质量 + 沙箱数据分析能力

1. **沙箱镜像升级**：构建 `conclave-python-datascience` 镜像（预装 pandas/numpy/matplotlib/scikit-learn），给 code_analysis 模板用
2. **embedding 模型接入**：替换内存伪向量为真实 embedding（BGE/sentence-transformers）
3. **Chunk 结构化**：Chunk 加 metadata/claims/relations 字段，为图 RAG 铺路
4. **摘要惰性读取**：摘要保留原文 char_range，按需展开

### 阶段二：产出能力升级

**目标**：支持完整产出闭环（讨论→代码→可部署服务）

1. **附件体系**：沙箱执行产出文件（PNG/CSV/MD）→ 存储 → 前端下载
2. **渐进式 produce**：支持多轮产出（讨论→基础代码→完整实现→终态产品），用户在每轮间做决策
3. **Dockerfile 生成模板**：新增 `deployable_service` 产出类型，生成 Dockerfile + docker-compose

### 阶段三：任务编排升级

**目标**：自动并行 + 知识库集成

1. **DAG 任务图**：引入任务依赖图抽象，自动并行无依赖任务
2. **多 Agent 代码执行**：produce 阶段支持多 Agent 各自生成代码 + 并行执行
3. **MCP 服务器协议预研**：知识库挂载 + 交叉映射（会议结果存入知识库、系统读取知识库执行审核）

---

## 4. 用户偏好与约束

- **前端风格**：当前样式用户喜欢，不要随意改动；设计模式生成的 .design 文件用户不喜欢，已手动调整
- **工作方式**：用户希望助手自主推进、不必反复确认，确保改动在项目目录下即可
- **commit 要求**：必须完善、分组清晰、不要弄错改动
- **后期计划**：项目完成后会引入多个 agent/平台做多方面评估
- **沟通记录**：要求归档，用于后续回溯

---

## 5. 执行进度

| 阶段 | 状态 | Commit | 说明 |
|---|---|---|---|
| 归档 | ✅ 完成 | `eafabe8` | 本文档 |
| 阶段一 | ✅ 完成 | `a23f45e` | RAG 升级：沙箱 datascience 镜像 + Chunk 结构化 + 惰性读取 |
| 阶段二 | ✅ 完成 | `046d300` | 产出能力升级：附件体系 + deployable_service + 产出类型选择器 |
| 阶段三 | ✅ 完成 | `6945e1c` | 任务编排升级：DAG 任务图 + MCP 预研 |

---

## 6. 架构演进讨论（2026-06-28 续）

三阶段升级完成后，用户提出了更深层的架构演进方向，经多轮讨论达成共识，沉淀到 [`architecture-evolution.md`](./architecture-evolution.md)。

### 6.1 讨论脉络

1. **系统能力诊断**：确认当前沙箱断网、无 pip install、无附件回传、无 Docker 镜像生成的限制
2. **ReAct vs Plan-Execute vs Re-Execution 取舍**：选择 Plan-Execute + 受控 Re-Execution，不用纯 ReAct（会推翻六阶段架构）
3. **思考爆炸的正确定义**：不是循环次数多，而是话题偏离 + 重复讨论 + 突破边际导致上下文归档/缩略
4. **系统自我进化**：Meta-Agent 自主优化代码库，人工审批合并，推送钉钉/微信通知
5. **动态流程**：阶段不固定，根据议题动态组装，前端动态展示
6. **成本核算**：方案二（token 预算）为主 + 方案一（实时价格）为辅，两者互补
7. **多视角评估**：不同公司/团队关注点不同，需要多模型多 Agent 评估
8. **沙箱开放**：默认开放网络，保留分级开关

### 6.2 核心决策

| 议题 | 决策 | 理由 |
|---|---|---|
| Agent 循环范式 | Plan-Execute + Re-Execution | 不推翻六阶段，LLM 只做修正不做决策 |
| 思考爆炸防护 | 目标锚定 + 偏离检测 + 归档压缩 | 不是 max_iterations，是上下文管理 |
| 系统自我进化 | Meta-Agent 生成 + 人工审批合并 | 不全自动，人在回路 |
| 流程模式 | 动态生成，非固定六阶段 | 根据议题自由组装 |
| 成本核算 | token 预算为主，实时价格为辅 | 两者互补不冲突 |
| 沙箱网络 | 默认开放，分级开关 | 未来需 Web Search/API/浏览器自动化 |
| 评估方式 | 多模型多 Agent 多视角 | 不同团队关注点不同 |

### 6.3 实施优先级

**近期**：议题路由 + RefineLoop + token 预算仪表盘
**中期**：Meta-Agent 改进建议 + 偏离检测 + 动态 DAG + 多视角评估
**远期**：完全动态流程 + 多 Agent 协作 + 沙箱全开放 + MCP 集成
