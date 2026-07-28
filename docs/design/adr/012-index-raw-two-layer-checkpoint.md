# ADR-012: 会话检查点 Index+Raw 2 层架构

## 状态

Accepted — 2026-07-27

## 背景

### 演进路径

会话检查点机制经历了三个阶段的演进：

1. **单文件全量快照**（当前 AGENTS.md §9 实际状态）：每次存档生成 `checkpoint-YYYYMMDD-HHMM.md`，包含完整状态快照。恢复时全量读取。
2. **ADR-011 Base+Delta+Index 3 层**（Proposed，**从未落地**）：定义了 base/delta/index 三层结构，但仅完成了模板创建，SKILL.md / AGENTS.md §9 / current-status.md 均未更新。
3. **本 ADR Index+Raw 2 层**（Accepted）：吸取 3 层未落地的教训，以更简单的 2 层结构替代。

> **关键事实**：ADR-011 的 3 层结构是纸面架构，从未真正实施。本 ADR 不是"从 3 层简化为 2 层"，而是"3 层方案因复杂度过高从未落地，改用更简单的 2 层方案"。

### 当前问题（单文件全量快照模式）

1. **全量写入浪费**：即使本次会话只推进了一个小待办，存档时仍要重写整个快照，90% 内容与上次重复。
2. **全量读取浪费 token**：恢复时必须读取整个检查点文件（5-15KB）+ 全部锚点文件（每个 10-50KB）。运行 3 个月的项目，单次恢复可能消耗 50-100KB token。
3. **无历史可追溯性**：旧检查点被新检查点"覆盖"（恢复时只读最新的），无法快速回答"这个决策是什么时候做的"。

### ADR-011 3 层结构未落地的原因

ADR-011 定义了 Base+Delta+Index 3 层结构，存在五个结构性问题导致从未落地：

1. **Base 滚动逻辑复杂**：需判断触发条件（月度/大阶段/delta 链过长/手动），合并算法（旧 base + 所有 delta → 新 base）易出错，ADR-011 自己也承认"目前手动触发"。
2. **Delta 增量记录认知负担重**：每次存档都要区分"新增/完成/变更/无变化"待办，需与上一次 delta 对比。AI 实际执行时容易凭感觉判断，违反 Anti-Vibe-Coding 原则（AGENTS.md §5.2）。
3. **恢复路径不直观**：常规恢复需 4 步 4 文件（current-status → index → base + delta），且需理解 base/delta 边界。
4. **Base 与 Delta 边界模糊**："哪些该进 base 哪些该进 delta"经常混淆，实践中难以一致执行。
5. **从未落地**：ADR-011 的 6 步执行顺序只完成了第 1 步（创建模板），其余 5 步均未执行。3 层结构复杂度超出了实际可维护性。

### 约束

- vault 存储在 `D:\conclave-knowledge-vault\`，不进 Git，不推 GitHub（AGENTS.md §9）
- MCP Server 提供 `search-vault`、`read-section`、`read-note` 等按需查询工具
- 按月分目录已实现（`sessions\YYYY-MM\`）
- 不能引入外部数据库——vault 是纯文件系统，MCP Server 只提供文件读写 API
- 用户偏好：索引层简洁、结构化、可检索带引用；原文层大而全（user_profile.md）

## 决策

### 核心思路：Index + Raw 2 层结构

将"单一全量快照文件"拆解为两层：

| 层 | 文件后缀 | 大小 | 内容 | AI 读取策略 |
|---|---|---|---|---|
| **索引层** | `.md` | ~2-5KB | 简摘 + 关键决策 + 待办全集 + 代码变更 + 锚点（必读/按需分类）+ 引用关系 | 默认读 |
| **原文层** | `.raw.md` | ~50-500KB | 完整对话记录，创建后不可修改 | 按需读（MCP search-vault 检索） |
| **月度索引** | `index.md` | ~1KB | 当月所有索引层文件的时序目录 | 恢复时读一次 |

### 目录结构

```
D:\conclave-knowledge-vault\
├── sessions\
│   └── YYYY-MM\
│       ├── index.md                          # 月度索引（当月会话时序目录）
│       ├── YYYYMMDD-HHMM-topic.md            # 索引层（AI 默认读）
│       └── YYYYMMDD-HHMM-topic.raw.md        # 原文层（按需读）
├── decisions\                                # 跨会话决策记录（被多个检查点引用）
├── project-context\
│   └── current-status.md                     # 会话恢复入口点
└── templates\
    ├── index-layer-template.md               # 索引层模板
    ├── raw-layer-template.md                 # 原文层模板
    └── decision-template.md                  # 决策记录模板
```

### 文件命名

`YYYYMMDD-HHMM-topic.md` + `YYYYMMDD-HHMM-topic.raw.md`

- `topic` 为简短英文/拼音标识（如 `vault-2layer-arch`、`security-wave6`），人类可读
- 索引层和原文层共享相同的时间和 topic 前缀，仅后缀不同

### 文件格式

#### 索引层（`.md`）

```markdown
---
title: "{{会话主题}}"
date: "{{YYYY-MM-DDTHH:MM:SS+08:00}}"
session_id: "{{session_id}}"
raw_file: "{{YYYYMMDD-HHMM-topic.raw.md}}"
tags:
  - checkpoint
  - index-layer
---

# {{会话主题}} — {{YYYY-MM-DD HH:MM}}

## 简摘

{{一句话描述本次会话做了什么}}

## 关键决策

- **{{决策标题}}**：选择 {{A}} 而非 {{B}}，原因是 {{理由}}

## 待办全集（当前状态）

### 高优先级
1. [ ] {{待办}} —— {{简述}}

### 中优先级
2. [ ] {{待办}}

### 近期完成（本会话）
- [x] {{完成事项}}（`{{文件路径}}`）

### 搁置项
- {{搁置待办}} —— 搁置原因：{{原因}}

## 代码变更

- 修改：`{{文件路径}}`（{{变更摘要}}）
- 新增：`{{文件路径}}`（{{用途}}）

## 锚点

### 必读（恢复上下文必须读）
- `{{文件路径}}` — {{为什么需要读}}

### 按需（深挖时读）
- `{{文件路径}}` — {{什么情况下读}}

## 引用关系

- **前驱**：`{{上一个检查点索引层路径}}`（{{一句话关联说明}}）
- **关联决策**：`decisions/{{decision-slug}}.md`
- **关联 ADR**：`docs/design/adr/{{adr-number}}.md`

> 原文层：`{{YYYYMMDD-HHMM-topic.raw.md}}`（完整对话记录，按需检索）
```

#### 原文层（`.raw.md`）

```markdown
---
title: "{{会话主题}} — 原文记录"
date: "{{YYYY-MM-DDTHH:MM:SS+08:00}}"
session_id: "{{session_id}}"
index_file: "{{YYYYMMDD-HHMM-topic.md}}"
tags:
  - checkpoint
  - raw-layer
---

# {{会话主题}} — 完整对话记录

> 本文件为原文层，创建后不可修改。AI 默认不读此文件，
> 仅在需要追溯具体对话细节时通过 MCP search-vault 检索。
> 索引层：`{{YYYYMMDD-HHMM-topic.md}}`

## 对话记录

{{完整对话记录，保留原始格式}}

---
> 创建时间：{{YYYY-MM-DD HH:MM}}
> 不可修改：是
```

**原文层内容范围**：
- **包含**：user/assistant 消息文本
- **摘要**：工具调用（工具名 + 参数摘要 + 返回摘要，非完整返回）
- **排除**：工具返回中的大段代码/文件内容（通过文件路径回溯）

#### 月度索引（`index.md`）

```markdown
---
month: "{{YYYY-MM}}"
last_updated: "{{YYYY-MM-DDTHH:MM:SS+08:00}}"
tags:
  - session-index
---

# {{YYYY-MM}} 会话索引

## 会话列表（时序）

| 时间 | 索引层文件 | 主题 | 变更类型 |
|---|---|---|---|
| {{YYYY-MM-DD HH:MM}} | `{{YYYYMMDD-HHMM-topic.md}}` | {{一句话主题}} | {{feat/fix/refactor/docs}} |

> 恢复上下文：读最新索引层 .md 即可。
> 深挖历史：按需读取对应原文层 .raw.md，或用 MCP search-vault 全文搜索。
```

### 恢复策略

#### 常规恢复（90% 场景）

用户说"继续"时，AI 执行：

```
1. 读 project-context\current-status.md     → ~1KB，获取最新索引层路径
2. 读最新索引层 .md                          → ~2-5KB，获取完整当前状态
3. 按需读"必读"锚点
```

**总读取量：~3-6KB**（对比单文件全量模式 50-100KB+，节省 90%+ token）

对比 ADR-011 的 4 步 4 文件（current-status → index → base + delta），2 层只需 2 步 2 文件即可获取完整当前状态——因为索引层是自包含的"全集"而非"增量"。

#### 深度恢复（需要追溯历史决策时）

用户问"这个决策是什么时候做的"时：

```
1. 用 MCP search-vault 搜索关键词
2. 返回包含该关键词的原文层文件列表
3. 按需读取匹配的原文层 .raw.md
```

#### 全量重建（罕见，如 vault 损坏恢复）

```
1. 读取月度索引 index.md
2. 按时序读取当月所有索引层 .md
3. 人工合并重建完整状态
```

### 索引层待办全集防膨胀策略

索引层包含"待办全集"而非 ADR-011 的"增量"，需要防止随项目推进无限膨胀：

| 待办状态 | 处理方式 |
|---|---|
| **进行中/未开始** | 保留在"当前待办全集"中，每条一行（优先级 + 一句话描述） |
| **本会话完成** | 移到"近期完成（本会话）"摘要区，一行一条，不附详情 |
| **历史完成** | 超过 10 条已完成项时，将最早的移入原文层归档 |
| **已取消/搁置** | 移到"搁置项"区，记录搁置原因 |

这样索引层维持在 2-5KB，不会随项目推进无限膨胀。

### 引用关系设计

采用**单向"前驱"链追溯**（策略 B），不回填"后继"字段：

- **前驱**：上一个检查点的索引层路径（创建时从 current-status.md 获取上一个指针）
- **关联决策**：`decisions/` 下的决策文件
- **关联 ADR**：`docs/design/adr/` 下的 ADR 文件
- **后继**：不记录（下一个检查点创建时只设自己的"前驱"，不回填上一个的"后继"）

选择单向链的原因：
- 回填"后继"需修改旧文件，增加操作复杂度
- 单向"前驱"链已足够追溯历史，双向链的收益不抵成本
- 与 Git 的单向 commit history 一致，心智模型简单

### 与 Trae memory 的协作

| 层级 | 存储内容 | 更新时机 |
|---|---|---|
| `project_memory.md` 顶部指针 | 索引层路径 + 最新时间 + 一句话任务 | 每次存档 |
| `current-status.md` | 最新索引层路径 + 时间 + 任务 + 近期重点 | 每次存档 |
| `index.md`（月度） | 当月所有索引层文件的时序目录 | 每次存档 |
| 索引层 `.md` | 完整当前状态（简摘/决策/待办/变更/锚点/引用） | 每次存档 |
| 原文层 `.raw.md` | 完整对话记录 | 每次存档（不可修改） |

`project_memory.md` 仍然**只存指针**（路径 + 时间 + 一句话任务），不含会话实质内容。

### 兼容性

- **旧检查点文件**：已有的 `checkpoint-*.md` 文件保留不删，视为"退化版索引层"——恢复时如果遇到旧格式，按全量快照读取（向后兼容）
- **迁移**：下次存档时自动使用新格式（索引层 + 原文层），不强制迁移历史文件
- **MCP 工具不变**：`search-vault`、`read-note`、`read-section` 等工具对索引层/原文层文件一视同仁，都是普通 markdown

## 备选方案

### 方案 A：Index+Raw 2 层（已选择）

- 优点：简单（无滚动合并）、自包含（索引层即全集）、恢复路径短（2 步 2 文件）、历史可追溯（原文层不可修改）
- 缺点：索引层包含全集可能膨胀（通过防膨胀策略缓解）

### 方案 B：Base+Delta+Index 3 层（ADR-011，未选择）

- 优点：读取量最小（base 提供全局状态快速恢复）、delta 记录变化轨迹
- 缺点：Base 滚动逻辑复杂、Delta 增量判断认知负担重、恢复路径 4 步 4 文件、**从未落地**
- 未选择原因：3 层结构复杂度超出实际可维护性，连第一步落地都没完成

### 方案 C：单文件全量快照（现状，未选择）

- 优点：最简单，无分层逻辑
- 缺点：全量写入浪费、全量读取浪费 token、无历史可追溯性
- 未选择原因：token 浪费严重，无法追溯历史决策

### 方案 D：纯增量日志（无全集）

- 优点：最简单，无冗余
- 缺点：恢复时间随历史线性增长；早期 delta 过时信息会累积；无法快速获取"当前全局状态"
- 未选择原因：长期使用后恢复成本不可接受

### 选择理由

方案 A 兼顾了简单性（无滚动合并逻辑）和自包含性（索引层即全集，恢复只需 2 步 2 文件）。相比方案 B，它消除了 Base/Delta 边界判断的认知负担；相比方案 C，它通过分层将 token 消耗降低 90%+；相比方案 D，它通过全集模式保证了恢复的 O(1) 复杂度。

用户明确表示"一天整个会话聊下来的数据量再大能有多大呢？有个 5MB 撑死了"——数据量不是核心问题，**数据存储结构和检索效率**才是。2 层结构以最小的复杂度解决了检索效率问题。

## 影响

### 文件变更

| 文件 | 变更 | 说明 |
|---|---|---|
| `docs/design/adr/011-*.md` | 状态改 Superseded | 标记为被 ADR-012 取代 |
| `docs/design/adr/012-*.md` | 新建 | 本文件 |
| `D:\...\templates\index-layer-template.md` | 新建 | 索引层模板 |
| `D:\...\templates\raw-layer-template.md` | 新建 | 原文层模板 |
| `D:\...\templates\base-template.md` | 归档 | 移入 `archive/` |
| `D:\...\templates\delta-template.md` | 归档 | 移入 `archive/` |
| `D:\...\templates\index-template.md` | 归档 | 移入 `archive/` |
| `D:\...\templates\checkpoint-template.md` | 归档 | 移入 `archive/` |
| `.trae/skills/session-checkpoint/SKILL.md` | 重写 | 存档/恢复流程改为 2 层 |
| `AGENTS.md` §9 | 更新 | 存储结构/存档规则/恢复规则改为 2 层 |
| `D:\...\project-context\current-status.md` | 更新 | 指向索引层 .md |

### 存档流程变化

```
旧流程（单文件）：
  存档 → 写 checkpoint-*.md（全量） → 更新 current-status.md → 更新 project_memory 指针

新流程（2 层）：
  存档 → 写索引层 .md（全集）
       → 写原文层 .raw.md（完整对话）
       → 更新月度索引 index.md
       → 更新 current-status.md → 更新 project_memory 指针
```

### 恢复流程变化

```
旧流程（单文件）：
  恢复 → 读 current-status.md → 读 checkpoint-*.md（全量） → 读全部锚点

新流程（2 层）：
  恢复 → 读 current-status.md → 读索引层 .md（全集） → 按需读"必读"锚点
       → 深挖时用 MCP search-vault 检索原文层 .raw.md
```

### 不在此 ADR 范围

- 索引层自动归档算法（已完成项超过阈值时自动移入原文层）——目前手动判断
- vault 跨项目共享的命名空间设计——vault 独立化后另行规划
- MCP Server 增加 `get-index-layer` 等专用工具——目前用通用 `search-vault` / `read-note` 足够
- 原文层压缩归档——当前存储充足，vault 总体积超 1GB 时再考虑
- project_memory.md 历史重复规则清理——独立任务
