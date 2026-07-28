# ADR-011: 会话检查点增量与结构化改造

## 状态

Superseded by ADR-012 — 2026-07-27

> **本 ADR 从未落地实施。** 定义的 Base+Delta+Index 3 层结构仅完成了模板创建（第 1 步），
> SKILL.md / AGENTS.md §9 / current-status.md 均未更新到 3 层结构。
> 经评估，3 层结构复杂度超出实际可维护性（Base 滚动逻辑复杂、Delta 增量判断认知负担重、
> 恢复路径需 4 步 4 文件），改用 ADR-012 的 Index+Raw 2 层结构。
> 本文中关于"全量快照浪费 token""无历史可追溯性"的问题分析仍然有效，
> 2 层结构以不同方式（索引层自包含全集 + 原文层按需检索）解决这些问题。

## 背景

### 当前问题

会话检查点机制（ADR 隐式，见 AGENTS.md §9 + session-checkpoint SKILL.md）当前采用**全量快照模式**：每次存档生成一个完整的状态快照文件（`checkpoint-YYYYMMDD-HHMM.md`），包含当前任务/已完成/进行中/待办/关键决策/代码变更/上下文锚点/阻塞项全部内容。

恢复时必须全量读取该文件（5-15KB），再读取"上下文锚点"中列出的每个文件（每个 10-50KB）。随着项目推进，存在三个结构性问题：

**1. 全量写入浪费**

假设本次会话只推进了一个小待办（如"修复 healthcheck"），但存档时仍要重写整个快照——包括未变化的"关键决策""已完成的早期事项""架构背景"等。90% 的内容与上一次检查点重复。

**2. 全量读取浪费 token**

恢复上下文时，AI 必须读取整个检查点文件 + 全部锚点文件。即使本次只需要"上一步做了什么 + 下一步做什么"，也要读入大量历史信息。一个运行 3 个月的项目，单次恢复可能消耗 50-100KB token 用于上下文恢复，而实际需要的信息不到 5KB。

**3. 无历史可追溯性**

当前模式下，旧检查点被新检查点"覆盖"（虽然文件保留，但恢复时只读最新的）。无法快速回答"这个决策是什么时候做的""这个待办是哪次会话新增的"——需要逐个打开检查点文件人工比对。

### 参考来源

OpenDeepWiki（开源版 DeepWiki）在代码仓库知识库场景解决了同类问题 [$TRAE_REF](https://blog.csdn.net/sD7O95O/article/details/157949192)：

- **增量更新**：`IncrementalUpdateWorker` 监控 Git commit，记录上次处理的 commit ID，下次只处理 diff 部分 [$TRAE_REF](https://deepwiki.com/AIDotNet/OpenDeepWiki/1.1-system-architecture)
- **结构化分层存储**：`Repository → Branch → Language → DocCatalog（自引用树）→ DocFile`，外部 AI 通过 MCP 按需查询而非全量加载 [$TRAE_REF](https://deepwiki.com/AIDotNet/OpenDeepWiki/1.1-system-architecture)
- **智能过滤**：文件数超过阈值时，AI 智能选择相关文件而非全量分析 [$TRAE_REF](https://deepwiki.com/AIDotNet/OpenDeepWiki/2.2-repository-analysis-and-smart-filtering)

### 约束

- vault 存储在 `D:\conclave-knowledge-vault\`，不进 Git，不推 GitHub（AGENTS.md §9）
- MCP Server 提供 `search-vault`、`read-section`、`read-note` 等按需查询工具
- 按月分目录已实现（`sessions\YYYY-MM\`）
- 不能引入外部数据库——vault 是纯文件系统，MCP Server 只提供文件读写 API

## 决策

### 核心思路：Base + Delta + Index 三层结构

将当前的"单一全量快照文件"拆解为三层：

| 层 | 文件 | 更新频率 | 大小 | 作用 |
|---|---|---|---|---|
| **Base** | `base-YYYYMMDD.md` | 低频（每周/大阶段完成时） | ~3-5KB | 项目全局状态快照，含完整待办列表/关键决策全集/架构锚点 |
| **Delta** | `delta-YYYYMMDD-HHMM.md` | 高频（每次存档） | ~0.5-2KB | 相对上一次的变化：新增/完成/变更的待办、新增决策、代码变更 |
| **Index** | `index.md`（每月一个） | 每次存档更新 | ~1KB | 当月所有 delta 的时序索引 + 最新 base 指针 |

### 目录结构

```
D:\conclave-knowledge-vault\
├── sessions\
│   ├── 2026-07\
│   │   ├── index.md                    # 7月索引（base指针 + delta链）
│   │   ├── base-20260701.md            # 7月基础快照（月初或大阶段创建）
│   │   ├── base-20260715.md            # 7月第二个基础快照（大阶段更新）
│   │   ├── delta-20260701-1430.md      # 增量：7月1日14:30的变化
│   │   ├── delta-20260703-0915.md      # 增量：7月3日9:15的变化
│   │   ├── delta-20260715-1800.md      # 增量：7月15日18:00的变化
│   │   └── ...
│   ├── 2026-08\
│   │   ├── index.md
│   │   ├── base-20260801.md            # 8月基础快照（继承7月底状态）
│   │   └── ...
│   └── archive\
│       └── 2026-04\                    # 超过3个月的整月归档
├── project-context\
│   └── current-status.md               # 全局入口（指向当月 index.md）
└── templates\
```

### 文件格式

#### Index 文件（`sessions\YYYY-MM\index.md`）

```markdown
---
month: "2026-07"
last_updated: "2026-07-27T21:30:00+08:00"
current_base: "base-20260715.md"
tags:
  - session-index
---

# 2026-07 会话索引

## 当前 Base

- **文件**：`base-20260715.md`
- **时间**：2026-07-15 18:00
- **覆盖范围**：安全加固 8 波完成 → 测试验证阶段

## Delta 链（时序）

| 时间 | 文件 | 变更摘要 | 变更类型 |
|---|---|---|---|
| 2026-07-15 18:00 | `delta-20260715-1800.md` | healthcheck curl→wget 修复 | fix |
| 2026-07-20 14:00 | `delta-20260720-1400.md` | 多租户隔离 P2 修复 | fix |
| 2026-07-27 21:30 | `delta-20260727-2130.md` | Obsidian MCP 独立组件部署 | feat |

> 恢复上下文：读 current_base + 最新 1-2 个 delta 即可。
> 深挖历史：按需读取对应 delta，或用 MCP search-vault 全文搜索。
```

#### Base 文件（`base-YYYYMMDD.md`）

```markdown
---
base_time: "2026-07-15T18:00:00+08:00"
created_by: "manual | auto-rollover"
previous_base: "base-20260701.md"
tags:
  - session-base
---

# Base 快照：2026-07-15 18:00

> 本文件是项目全局状态快照。低频更新（大阶段完成/每月滚动）。
> 日常变化记录在 delta 文件中，不修改本文件。

## 项目阶段

安全加固 8 波已完成代码落地，进入测试验证阶段。

## 当前待办全集

1. 编排器状态机重构（高）——7 次 bug 同一根因，需开 ADR
2. 安全加固测试验证（高）——test_wave6/7/8 在 Docker 内跑通
3. 三数据源渗透审计（高）——内存/向量库/MCP 提示词渗透攻击面
4. 多租户路由层隔离（中）——P2 技术债
5. 超时量化 + 指数退避（中）——P2 技术债

## 关键决策全集（截至本 Base）

- **ADR-010**：砍掉伪引用，evidence strength 从 weak 改 none
- **ADR-009**：MeetingState sections 只迁移读取路径
- **Obsidian vault 独立化**：迁移到 D 盘，不进 Git，按月分目录

## 架构锚点

- `AGENTS.md` — AI 助手实战纪律
- `docs/design/design-principles.md` — 11 条设计原则
- `docs/design/adr/` — ADR 目录
- `backend/app/skills/ui_design_system.yaml` — UI 规范

## 阻塞项

- 无（等待测试验证）
```

#### Delta 文件（`delta-YYYYMMDD-HHMM.md`）

```markdown
---
delta_time: "2026-07-27T21:30:00+08:00"
session_id: "6a64d7cd"
base_ref: "base-20260715.md"
previous_delta: "delta-20260720-1400.md"
tags:
  - session-delta
---

# Delta：2026-07-27 21:30

## 本次任务

Obsidian MCP 独立组件部署 + vault 迁移到 D 盘

## 待办变更

### 新增
- [ ] 在 Trae 中连接 MCP Server（SSE 端点）（优先级：中）

### 完成
- [x] vault 迁移到 D:\conclave-knowledge-vault\（独立组件，不进 Git）
- [x] docker-compose.obsidian-mcp.yml 挂载 D 盘
- [x] AGENTS.md §9 描述存储逻辑和使用逻辑
- [x] session-checkpoint Skill 适配新架构
- [x] healthcheck curl→wget 修复

### 无变化
（本次未触及的待办不列出）

## 关键决策

- **vault 独立化**：选择 D 盘独立目录而非项目内 obsidian-vault/。原因：会话内容包含个人沟通，禁止推 GitHub；vault 是跨项目复用的个人 AI 记忆，不应绑定单一项目。
- **禁止双写**：选择只写 vault 而非 vault + docs/sessions 双写。原因：双写会导致 Git 仓库混入会话内容，违反隐私边界。
- **按月分目录**：选择 YYYY-MM 子目录而非平铺。原因：长期使用单目录会膨胀，AI 读取时只需扫描当月目录。

## 代码变更

- 修改：`docker-compose.obsidian-mcp.yml`（volume 挂载改 D 盘，healthcheck curl→wget）
- 修改：`AGENTS.md`（§0 路径修正，§9 重构为独立组件架构）
- 修改：`.gitignore`（排除 obsidian-vault/ 和 checkpoint 文件）
- 重写：`.trae/skills/session-checkpoint/SKILL.md`（路径/去双写/按月目录/隐私边界）

## 锚点（仅本次新增的）

- `docker-compose.obsidian-mcp.yml`
- `D:\conclave-knowledge-vault\project-context\current-status.md`

> 常规锚点见 base 文件"架构锚点"章节，此处只列本次新增的。
```

### 恢复策略

#### 常规恢复（90% 场景）

用户说"继续"时，AI 执行：

```
1. 读 project-context\current-status.md     → ~1KB，获取当月 index 指针
2. 读 sessions\YYYY-MM\index.md             → ~1KB，获取最新 base + delta 链
3. 读最新 base 文件                          → ~3-5KB，获取全局状态
4. 读最新 1-2 个 delta 文件                  → ~1-4KB，获取近期变化
```

**总读取量：~6-11KB**（对比当前全量模式 50-100KB+，节省 80-90% token）

#### 深度恢复（需要追溯历史决策时）

用户问"这个决策是什么时候做的"时：

```
1. 用 MCP search-vault 搜索关键词（如"vault 独立化"）
2. 返回包含该关键词的 delta 文件列表
3. 按需读取匹配的 delta 文件（~1-2KB/个）
```

#### 全量重建（罕见，如 vault 损坏恢复）

```
1. 读取最早的 base
2. 按时序读取所有 delta
3. 人工合并重建完整状态
```

### Base 滚动策略

Base 不是每次存档都更新，而是以下条件之一触发：

| 触发条件 | 说明 |
|---|---|
| **月度滚动** | 每月第一个 delta 之前，以上月底状态创建新月 base |
| **大阶段完成** | 完成 P0 修复/版本合并/架构重构等里程碑时 |
| **delta 链过长** | 当月 delta 超过 15 个时，合并为新的 base |
| **手动触发** | 用户说"存一个 base" / "更新基础快照" |

新 base 创建时，将上一个 base + 所有 delta 合并，生成当前完整状态快照。旧 base 保留不删。

### 与 Trae memory 的协作

| 层级 | 存储内容 | 更新时机 |
|---|---|---|
| `project_memory.md` 顶部指针 | `index.md` 路径 + 最新 delta 时间 + 一句话任务 | 每次存档 |
| `current-status.md` | 当月 `index.md` 路径 + 最新 base + 最新 delta | 每次存档 |
| `index.md` | base 指针 + delta 链 | 每次存档 |
| `base-*.md` | 全局状态快照 | 低频滚动 |
| `delta-*.md` | 增量变化 | 每次存档 |

`project_memory.md` 仍然**只存指针**（路径 + 时间 + 一句话任务），不含会话实质内容。

### 兼容性

- **旧检查点文件**：已有的 `checkpoint-*.md` 文件保留不删，视为"退化版 delta"——恢复时如果遇到旧格式，按全量快照读取（向后兼容）
- **迁移**：下次存档时自动使用新格式（base + delta），不强制迁移历史文件
- **MCP 工具不变**：`search-vault`、`read-note`、`read-section` 等工具对 base/delta 文件一视同仁，都是普通 markdown

## 备选方案

### 方案 A：Base + Delta + Index 三层（已选择）

- 优点：读取量最小（80-90% 节省），历史可追溯，结构清晰
- 缺点：三个文件类型，存档逻辑稍复杂

### 方案 B：单一快照 + 结构化分片

把检查点拆成多个分文件（`decisions.md`、`todos.md`、`changes.md`），恢复时按需读取。

- 优点：结构清晰，按需查询自然
- 缺点：每次仍要全量重写所有分片；无法追溯"什么时候变化的"；分片间一致性难维护

### 方案 C：纯增量日志（无 base）

只记 delta，不记 base。恢复时从最早的 delta 逐个重放。

- 优点：最简单，无冗余
- 缺点：恢复时间随历史线性增长；早期 delta 过时信息会累积；无法快速获取"当前全局状态"

### 选择理由

方案 A 兼顾了读取效率（base 提供全局状态快速恢复）和历史可追溯性（delta 链记录变化轨迹），且与 OpenDeepWiki 的增量更新思路一致。方案 B 的分片思路可作为未来增强（在 delta 内部按类型分片），但不是基础架构。方案 C 的线性重放在长期使用后不可接受。

## 影响

### 文件变更

| 文件 | 变更 | 说明 |
|---|---|---|
| `.trae/skills/session-checkpoint/SKILL.md` | 重写存档/恢复流程 | 适配 base+delta+index 三层结构 |
| `D:\conclave-knowledge-vault\templates\` | 新增 3 个模板 | `base-template.md`、`delta-template.md`、`index-template.md` |
| `AGENTS.md` §9 | 更新存储结构描述 | 从"单一检查点"改为"base+delta+index" |
| `D:\conclave-knowledge-vault\project-context\current-status.md` | 格式微调 | 指向 `index.md` 而非直接指向检查点 |

### 存档流程变化

```
旧流程：
  存档 → 写 checkpoint-*.md（全量） → 更新 current-status.md → 更新 project_memory 指针

新流程：
  存档 → 判断是否需要新 base
           ├─ 是 → 写 base-*.md + 更新 index.md
           └─ 否 → 写 delta-*.md + 更新 index.md
       → 更新 current-status.md → 更新 project_memory 指针
```

### 恢复流程变化

```
旧流程：
  恢复 → 读 current-status.md → 读 checkpoint-*.md（全量） → 读全部锚点

新流程：
  恢复 → 读 current-status.md → 读 index.md → 读最新 base + 最新 1-2 delta
       → 按需读锚点（只读 delta 中新增的，常规锚点已在 base 中）
```

### 不在此 ADR 范围

- delta 内部按类型分片（decisions/todos/changes 独立文件）——未来增强
- base 自动合并算法（delta 链 → base 的自动折叠）——目前手动触发
- vault 跨项目共享的命名空间设计——vault 独立化后另行规划
- MCP Server 增加 `get-delta-chain` 等专用工具——目前用通用 `search-vault` / `read-note` 足够

## 执行顺序

1. 创建 3 个新模板文件（base/delta/index template）
2. 重写 session-checkpoint SKILL.md 存档/恢复流程
3. 更新 AGENTS.md §9 存储结构描述
4. 更新 current-status.md 指向 index.md
5. 修正 project_memory.md 过时条目（双写策略描述）
6. 首次使用：手动创建第一个 base + delta + index，验证恢复流程
