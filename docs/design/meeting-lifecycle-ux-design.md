# Conclave 会议生命周期管理 — 前端交互设计方案

> 版本：v1.0 | 日期：2026-08-04 | 状态：设计稿
> 覆盖功能：删除/回收站、归档、克隆/重跑/系列、阶段重跑、信息架构重构

---

## A. 信息架构调整

### A.1 导航结构变更

现有 NavRail 为纯图标 w-14 侧栏。在大量会议场景下，单一 `/board` 入口无法承载"活跃/归档/回收站"三层状态，需要引入**视图分层**而非新增顶级导航项。

**方案：NavRail 保持精简，看板内部用 Tab 切换状态视图**

```
NavRail（保持 w-14 不变）
├── 看板 /board              ← 默认入口，内部 Tab 切换
│   ├── Tab: 进行中          ← running/paused 会议（卡片网格）
│   ├── Tab: 全部            ← 非归档非删除的历史会议（列表，默认选中）
│   ├── Tab: 归档 /archive   ← 已归档会议（独立视图）
│   └── Tab: 回收站 /trash   ← 软删除会议（管理员额外显示"永久删除"）
├── 探索 /explore            ← 不变
├── 工作区 /workspace        ← 不变
├── 图谱 /graph              ← 增强（见 A.3）
├── 报告 /reports            ← 不变
├── Agent /agents            ← 不变
├── 模型 /models             ← 不变
├── 团队 /teams              ← 不变
├── [admin] 运维/管理        ← 不变
└── 设置 /settings           ← 不变
```

**路由设计**：
- `/board` — 全部会议列表（含进行中分区）
- `/board?view=archive` — 归档视图（Tab 切换，不新增路由）
- `/board?view=trash` — 回收站视图
- `/series/:seriesId` — 同议题系列详情页（新增）
- `/meetings/:id/diff/:otherId` — 会议差异对照（新增，模态或子路由）

**为什么不新增顶级导航项**：
- 归档/回收站是看板的子状态，不是独立功能域
- NavRail 已经 8+ 项，继续增加会降低可扫描性
- Tab 切换成本低于导航跳转，且保留上下文（搜索/筛选条件不丢失）

### A.2 看板（Board）视图分层

将现有单一列表拆分为**三层状态机**：

```
                    ┌─────────────┐
                    │  进行中      │  running/paused
                    │  (卡片网格)  │
                    └──────┬──────┘
                           │ 完成/终止/出错
                           ▼
┌─────────┐  归档操作   ┌─────────────┐  删除操作   ┌─────────────┐
│  全部    │───────────▶│   归档       │───────────▶│  回收站     │
│ (默认)  │◀───────────│  (只读浏览)  │◀───────────│ (软删除)    │
└─────────┘  取消归档   └─────────────┘  恢复       └──────┬──────┘
                                                          │ 管理员硬删
                                                          ▼
                                                    ┌─────────────┐
                                                    │  永久删除    │
                                                    │ (不可恢复)   │
                                                    └─────────────┘
```

**每个视图的顶部工具栏统一**：

```
┌─────────────────────────────────────────────────────────┐
│ [搜索框........................] [状态筛选▾] [标签▾]      │
│ [排序: 最近创建▾]  [时间范围▾]         [批量操作▾]       │
└─────────────────────────────────────────────────────────┘
```

- 搜索：标题/议题/摘要全文搜索（debounce 300ms）
- 状态筛选：全部/已完成/出错/已终止（仅"全部"Tab 可见）
- 标签筛选：从 `meeting.metadata.tags` 聚合
- 排序：最近创建 / 最近活跃 / 消息数最多 / 标题 A-Z
- 时间范围：今天 / 本周 / 本月 / 自定义
- 批量操作：仅当有选中项时出现（归档/删除/打标签/恢复）

### A.3 图谱演进

现有 `/graph` 是知识图谱视图。随着归档/系列/重跑功能引入，图谱需要：

1. **系列关系边**：同 series 的会议之间用浅色虚线连接（区别于知识引用的实线）
2. **重跑关联边**：`rerun_from` / `stage_rerun_from` 用带箭头的边表示，箭头指向"重跑后的新会议"
3. **显示开关**（图谱右上角工具栏新增）：
   - `[ ] 显示归档会议` — 默认关闭，开启后归档节点以 40% 透明度渲染
   - `[ ] 显示已删除会议` — 仅管理员可见，开启后回收站节点以虚线边框+30%透明度渲染
   - `[ ] 按系列分组` — 开启后同 series 节点聚拢为簇（用浅色背景圈包裹）
4. **节点视觉编码**：
   - 正常会议：实心填充（现有样式）
   - 归档会议：填充+40%透明度
   - 回收站会议（管理员）：虚线边框+30%透明度，hover 显示"已删除"标签
   - 系列根节点：左上角小三角标记（系列起点）

### A.4 列表组织策略（数百到数千会议）

当会议数量增长到数百/数千级别时，需要**分组+折叠+分页**三层策略：

**第一层：时间分组（默认）**

历史列表按时间倒序分组，组头 sticky：

```
── 今天 ───────────────────────────────
  [MeetingRow]
  [MeetingRow]
── 昨天 ───────────────────────────────
  [MeetingRow]
── 本周 ───────────────────────────────
  ...
── 本月 ───────────────────────────────
  ...
── 更早 ───────────────────────────────
  ...
```

**第二层：系列折叠**

同一系列（series）的会议在列表中折叠为一个 `SeriesRow`：

```
▸ 微服务通信方案讨论 (3 次讨论)  最近: 2小时前  [展开▾]
▾ 数据库选型对比 (2 次讨论)  最近: 昨天
    ├ ① 数据库选型对比 - 首轮  3天前  已完成  47条消息
    ├ ② 数据库选型对比 - 加入PostgreSQL向量能力  2天前  已完成  63条
    └ ③ 数据库选型对比 - 重跑·证据核验阶段  昨天  已完成  28条  ← 阶段重跑
```

展开/收起状态通过 URL query `?expanded=series_xxx` 或 localStorage 记忆。

**第三层：分页/无限滚动**

修复现有 page/page_size 与后端 limit/offset 不匹配的 bug，使用**游标分页（cursor-based）**替代 offset 分页：
- 初始加载 20 条
- 滚动到底部自动加载下一批（Intersection Observer）
- 不显示传统页码，显示"已加载 N 条，共 M 条"

---

## B. 每个功能的交互流程

### B.1 删除/回收站

#### B.1.1 软删除（普通用户）

**入口**：MeetingRow 右侧 hover 出现的操作菜单（将现有单个垃圾桶图标替换为 `⋯` 菜单，避免误触）

```
MeetingRow 右侧操作区：
  平时：hover 时显示 [⋯]
  点击 ⋯ 展开 DropdownMenu：
    ├─ 打开详情
    ├─ 克隆会议
    ├─ 归档
    ├─ 重跑（仅已完成会议）
    └─ 删除 ──────── 危险操作，红色文字
```

**流程**：

1. 用户点击 MeetingRow 上的 `⋯` → `删除`
2. 若会议状态为 `running`/`paused`：
   - 弹出轻量提示（Toast 或 Popover，不用模态）："请先终止运行中的讨论才能删除"
   - 提供"终止讨论"按钮，点击后发送 `stop` 控制信号，终止后自动刷新状态
3. 若会议状态非运行中：
   - 弹出 ConfirmDialog：
     - 标题："删除讨论"
     - 描述：`「{truncate(title, 40)}」将移入回收站，30 天后自动清理。您可以在回收站中恢复。`
     - 按钮：[取消] [移入回收站]（destructive 红色）
4. 确认后：
   - 调用 `POST /meetings/{id}/trash`（软删除，设置 `deleted_at`）
   - 列表中该行以 0.15s 淡出+高度收缩动画移除（仅动画 opacity/max-height，不动画 height）
   - Toast 提示："已移入回收站"，带"撤销"按钮（5s 内可撤销，调用恢复接口）

#### B.1.2 回收站视图

**访问**：Board 页面 Tab 切换到"回收站"

**布局差异**：
- 列表项视觉弱化：整体 opacity 0.7，标题加删除线样式（`text-decoration: line-through`）
- 无"新建会议"区域
- 顶部提示条（浅色警告背景 `rgba(184,125,43,0.06)`）：
  - "回收站中的讨论将在 30 天后自动永久删除。剩余 N 天。"
- 每个 MeetingRow 的操作变为：`恢复` | `永久删除...`（管理员可见）

**空状态**：
```
┌─────────────────────────────────────┐
│          [垃圾桶图标，灰色 48px]      │
│                                     │
│      回收站是空的                    │
│      已删除的讨论会在这里暂存 30 天    │
└─────────────────────────────────────┘
```

#### B.1.3 恢复

1. 在回收站视图点击 `恢复`
2. 无确认弹窗（恢复是安全操作）
3. 调用 `POST /meetings/{id}/restore`
4. 该行从回收站列表移除，Toast："已恢复到全部列表"

#### B.1.4 管理员硬删（永久删除）

1. 管理员在回收站视图点击 `永久删除...`
2. 弹出**增强版确认对话框**（非普通 ConfirmDialog）：
   - 标题："永久删除讨论"
   - 红色警告条："此操作不可撤销。所有消息、思维链、工具调用记录将被彻底删除。"
   - 输入确认：要求用户输入会议标题以确认
     ```
     请输入会议标题以确认删除：
     ┌─────────────────────────────┐
     │  _________________________  │
     └─────────────────────────────┘
     ```
   - "永久删除"按钮默认 disabled，只有输入完全匹配标题时才 enabled（红色按钮）
   - [取消] [永久删除]
3. 确认后调用 `DELETE /meetings/{id}/hard`
4. 列表项移除，Toast："已永久删除"

**running 状态禁删逻辑**：在所有删除入口（单个删除、批量删除、管理员硬删）统一前置检查：
- 前端：MeetingRow 的删除菜单项对 running/paused 会议直接 disabled，tooltip 解释"请先终止讨论"
- 后端：接口层也做状态校验，返回 400 时前端弹出"请先终止运行中的讨论"错误提示

---

### B.2 归档

#### B.2.1 归档操作

**入口**：
- 单个：MeetingRow `⋯` 菜单 → `归档`
- 批量：选中多个会议 → 顶部批量操作栏 → `归档`
- 自动归档提示（见 B.2.3）

**流程**：

1. 用户点击 `归档`
2. 不弹确认框（归档是可逆操作，认知成本低）
3. 调用 `POST /meetings/{id}/archive`（设置 `archived=true, archived_at`）
4. 列表项以 0.15s 淡出移除
5. Toast："已归档"，带"撤销"（5s）

**running 状态禁归档**：与删除同理，归档菜单项对 running/paused disabled，tooltip "请等待讨论完成或终止后再归档"。

#### B.2.2 归档视图

**访问**：Board 页面 Tab 切换到"归档"

**视觉差异**：
- 列表项正常显示，但无 `⋯` 菜单中的"归档"选项（已归档），替换为"取消归档"
- 顶部信息条："归档的讨论不会出现在主列表和图谱中（可在图谱设置中开启显示）"
- 只读强调：点击归档会议进入 Explore 页面时，顶部加一个浅色提示条"这是一个已归档的讨论，内容为只读"，TakeoverPanel（接管面板）隐藏
- 归档会议仍可查看时间线/消息流/思维树，但所有控制按钮（暂停/跳过/接管）禁用

**取消归档**：
1. 归档视图点击 `取消归档`
2. 无确认，直接调用 `POST /meetings/{id}/unarchive`
3. Toast："已取消归档"

#### B.2.3 自动归档提示

**触发条件**（前端判断，基于后端返回的 `ended_at`）：
- 会议已完成（done/error/aborted）超过 30 天未被查看过（基于 `last_viewed_at` 或前端 localStorage 最后访问记录）

**提示形式**：非模态，在 Board 页面"全部"Tab 顶部出现一个可关闭的提示横幅：

```
┌─────────────────────────────────────────────────────────────────┐
│ 📦 您有 12 个已完成超过 30 天的讨论，建议归档以保持列表整洁。     │
│ [查看可归档会议] [全部归档] [×]                                  │
└─────────────────────────────────────────────────────────────────┘
```

- 点击"查看可归档会议"：筛选条件自动设为"30天前已完成"，展示待归档列表
- 点击"全部归档"：批量归档所有符合条件的会议，带进度 toast
- 点击 `×`：关闭横幅，7 天内不再提示（localStorage 记录）

---

### B.3 克隆/重跑/同议题系列

#### B.3.1 系列（Series）概念

**同一系列定义**：通过"克隆"或"重跑"产生的会议，自动归为同一系列，共享 `series_id`。
- 原始会议为 `series_root`（系列根）
- 后续克隆/重跑的会议通过 `parent_meeting_id` 形成有向图
- 系列标题默认取根会议标题，用户可重命名

#### B.3.2 克隆会议

**入口**：MeetingRow `⋯` 菜单 → `克隆会议`

**流程**：

1. 用户点击 `克隆会议`
2. 弹出克隆配置对话框（Dialog，max-w-md）：

```
┌─ 克隆讨论 ─────────────────────────────┐
│                                        │
│  原议题：{truncate(title, 50)}          │
│                                        │
│  新议题标题：                           │
│  ┌────────────────────────────────────┐│
││  {title} (副本)                     ││
│  └────────────────────────────────────┘│
│                                        │
│  复制内容：                             │
│  ☑ 议题描述                            │
│  ☑ Agent 团队配置                      │
│  ☐ 继承结论作为上下文                   │
│  ☐ 复制已上传的工作区文件               │
│                                        │
│              [取消]  [开始克隆讨论]     │
└────────────────────────────────────────┘
```

3. 用户调整标题和选项后点击"开始克隆讨论"
4. 调用 `POST /meetings/{id}/clone`，后端创建新会议，复制配置（按需复制上下文/文件）
5. 成功后直接跳转到新会议的 Explore 页面（`/explore/{newId}`）
6. 新会议自动归入同一 `series_id`

#### B.3.3 快速重跑（完整重跑）

**入口**：MeetingRow `⋯` 菜单 → `重跑`（仅 done/error/aborted 状态可见）

**流程**：

1. 点击 `重跑`
2. 弹出轻量确认（Popover 或小型 Dialog，非全屏）：
   - "将以相同议题和 Agent 团队重新启动一次讨论。历史讨论不会被修改。"
   - [取消] [开始重跑]
3. 确认后调用 `POST /meetings/{id}/rerun`（等价于克隆+自动启动，不弹配置）
4. 跳转到新会议 Explore 页面
5. 新会议与原会议同 series，且有 `rerun_type: 'full'` 标记

#### B.3.4 系列折叠展示（列表中）

在 Board "全部" Tab 中，同 series 的会议折叠为一个 `SeriesRow`：

```
┌─────────────────────────────────────────────────────────────┐
│ ▾  微服务通信方案讨论                                       │
│    3 次讨论 · 最近 2 小时前 · 系列创建于 7 天前              │
│                                          [系列操作▾]       │
├─────────────────────────────────────────────────────────────┤
│  ③ 微服务通信方案讨论 - gRPC 补充验证  2小时前  已完成  32条 │ ← 最新在最上
│  ② 微服务通信方案讨论 - 加入安全视角    3天前   已完成  58条 │
│  ① 微服务通信方案讨论                  7天前   已完成  89条 │ ← 根在最下
└─────────────────────────────────────────────────────────────┘
```

- 序号圆圈（①②③）表示系列内顺序
- 最新的在最上方（符合倒序原则）
- `系列操作▾` 菜单：重命名系列、差异对照、批量归档、在图谱中查看
- 点击单个子会议行：跳转到对应 Explore 页面
- 折叠态（▸）显示：系列标题 + 次数徽章 + 最近活动时间

**系列内图标标记**：
- 普通克隆：无标记
- 完整重跑：小刷新图标 ↻ 跟在标题后
- 阶段重跑：小阶段图标 ⟳ + "从{stage}阶段重跑"标签

#### B.3.5 系列详情页

**路由**：`/series/:seriesId`（从系列操作菜单或图谱点击系列簇进入）

**布局**：

```
┌─────────────────────────────────────────────────────────┐
│ ← 返回看板                                              │
│                                                         │
│ 微服务通信方案讨论                      [重命名] [+新讨论]│
│ 3 次讨论 · 系列创建于 2026-07-28 · 总消息 179 条        │
├─────────────────────────────────────────────────────────┤
│ ┌─ 讨论演进时间线 ─────────────────────────────────────┐│
│ │                                                      ││
│ │  ③ 2小时前 已完成  ● gRPC 补充验证                   ││
│ │     │  32条消息 · 从"证据核验"阶段重跑               ││
│ │     │                                                ││
│ │  ② 3天前   已完成  ● 加入安全视角     ↻ 完整重跑     ││
│ │     │  58条消息                                      ││
│ │     │                                                ││
│ │  ① 7天前   已完成  ● 首轮讨论                        ││
│ │     89条消息                                         ││
│ └──────────────────────────────────────────────────────┘│
│                                                         │
│ [选择两次讨论进行差异对照]                               │
│ 已选：① 和 ③  [查看差异]                                │
└─────────────────────────────────────────────────────────┘
```

#### B.3.6 差异对照视图

**触发**：系列详情页选择两个会议 → "查看差异"；或 MeetingRow 菜单 → "与...对照"

**展示形式**：全屏 Dialog（max-w-6xl）或子路由 `/meetings/:id/diff/:otherId`

**布局**（左右分栏）：

```
┌─ 讨论差异对照 ──────────────────────────────────── [×] ─┐
│                                                         │
│ ① 首轮讨论                      vs    ③ gRPC 补充验证    │
│ 7天前 · 89条 · 已完成             2小时前 · 32条 · 已完成│
├──────────────────────┬──────────────────────────────────┤
│                      │                                  │
│  [最终结论区域]       │  [最终结论区域]                   │
│  "建议采用 REST 为主  │  "补充安全审查后，建议内部服务    │
│   gRPC 用于高性能     │   间统一采用 gRPC + mTLS，        │
│   场景"              │   对外 REST"                      │
│                      │                                  │
├──────────────────────┴──────────────────────────────────┤
│  关键差异（AI 总结）：                                   │
│  • 结论从"REST 为主"演进为"内部 gRPC + 对外 REST"       │
│  • 新增了 mTLS 安全维度考量                             │
│  • 证据核验阶段推翻了首轮"gRPC 调试成本高"的假设        │
│                                                         │
│  [查看消息级别差异→]                                    │
└─────────────────────────────────────────────────────────┘
```

差异层级：
1. **结论差异**（默认显示）：AI 提取两次会议 final_summary 的关键不同点
2. **阶段差异**：折叠展开各阶段的结论差异
3. **消息级别差异**：跳转到底层双栏消息流对比（高级功能，v2 可做）

---

### B.4 阶段重跑

#### B.4.1 概念

从已完成会议的**某个阶段**重新开始讨论，而非从头再来。前置阶段的结论作为上下文注入，从指定阶段开始重新走流程。

典型场景：证据核验阶段发现引用有误，不想重新讨论澄清/组内/交叉讨论，直接从证据核验阶段重跑。

#### B.4.2 入口

**入口位置（两个）**：

1. **Explore 页面 StageTimeline 组件上**：每个已完成阶段节点 hover 时出现"从此阶段重跑"按钮
   ```
   StageTimeline 节点：
   ○──○──○──●──○──○──○
         澄清 组内 交叉 [证据核验] ← hover时显示 ↻ 从此阶段重跑
   ```

2. **MeetingRow `⋯` 菜单** → `阶段重跑...`（弹出阶段选择器）

#### B.4.3 阶段选择器

从 MeetingRow 菜单进入时，弹出阶段选择 Dialog：

```
┌─ 阶段重跑 ─────────────────────────────┐
│                                        │
│  原讨论：{truncate(title, 40)}          │
│                                        │
│  选择从哪个阶段重新开始：               │
│                                        │
│  ○ 澄清阶段（Clarification）           │
│  ○ 组内讨论（Intra-team）              │
│  ○ 交叉讨论（Cross-team）              │
│  ● 证据核验（Evidence Check）  ← 默认   │
│  ○ 仲裁（Arbitrate）                   │
│  ○ 产出（Produce）                     │
│                                        │
│  ℹ️ 澄清→交叉讨论→证据核验 之前的结论    │
│     将作为上下文保留。从证据核验开始     │
│     将重新进行证据检索和核验。          │
│                                        │
│           [取消]  [预览影响 →]         │
└────────────────────────────────────────┘
```

#### B.4.4 影响预览确认页

点击"预览影响"后，进入影响预览页（关键步骤，防止误操作）：

```
┌─ 阶段重跑 · 影响预览 ──────────────────────────────────┐
│                                                        │
│  将从「证据核验」阶段重新讨论：{title}                  │
│                                                        │
├────────────────────────────────────────────────────────┤
│  ✅ 保留的阶段（结论作为上下文继承）                    │
│     ├─ 澄清阶段：明确了 3 个核心问题                    │
│     ├─ 组内讨论：各角色形成初步立场                     │
│     └─ 交叉讨论：就技术选型方向达成 80% 共识            │
│                                                        │
│  🔄 将重新执行的阶段                                    │
│     ├─ 证据核验：将重新检索和验证引用来源               │
│     ├─ 仲裁：基于新证据重新仲裁                         │
│     └─ 产出：生成更新后的最终报告                       │
│                                                        │
│  ⚠️ 注意：                                              │
│     • 原讨论不会被修改，将创建一个新的重跑讨论          │
│     • 新讨论将链接到此讨论作为来源                      │
│     • 工作区上传的文件将被复制                          │
│                                                        │
│  新议题标题（可修改）：                                 │
│  ┌────────────────────────────────────────────────────┐│
││  {title} - 重跑·证据核验阶段                        ││
│  └────────────────────────────────────────────────────┘│
│                                                        │
│              [取消]  [开始阶段重跑]                    │
└────────────────────────────────────────────────────────┘
```

- "保留的阶段"从后端获取（GET /meetings/{id}/stage-rerun-preview?stage=evidence_check）
- 每个阶段显示阶段名 + 一句话摘要（从阶段结论提取）
- 此步骤的目的是让用户明确知道"哪些保留、哪些重来"

#### B.4.5 重跑执行

1. 点击"开始阶段重跑"
2. 调用 `POST /meetings/{id}/stage-rerun`，payload: `{ from_stage: 'evidence_check', new_title: '...' }`
3. 后端创建新会议：
   - 复制前置阶段消息作为 `context_messages`
   - 从指定 stage 开始执行
   - 设置 `parent_meeting_id`、`rerun_type: 'stage'`、`rerun_from_stage`
   - 归入同一 series
4. 前端跳转到新会议 Explore 页面
5. 新会议的 StageTimeline 有特殊视觉：
   - 前置阶段（已继承）：显示为灰色对勾 ✓，tooltip "继承自原讨论"
   - 起始阶段：高亮显示，标注"重跑起点"
   - 后续阶段：正常显示进度

#### B.4.6 关联展示

- 在原会议 Explore 页面顶部，若存在重跑子会议，显示关联条：
  ```
  ┌────────────────────────────────────────────────────┐
  │ ↻ 此讨论有 1 个重跑版本：                           │
  │   ③ {title} - 重跑·证据核验阶段  2小时前 已完成 →   │
  └────────────────────────────────────────────────────┘
  ```
- 在新会议 Explore 页面顶部，显示来源条：
  ```
  ┌────────────────────────────────────────────────────┐
  │ ⟳ 此讨论从 ① {原title} 的「证据核验」阶段重跑而来   │
  │   查看原讨论 →                                      │
  └────────────────────────────────────────────────────┘
  ```

---

### B.5 整体信息架构（面对数百到数千会议）

已在 A 节详述，这里补充交互层面的关键设计：

#### B.5.1 批量操作

**选中模式进入**：
- 鼠标悬停 MeetingRow 时，左侧出现 checkbox（默认隐藏，hover 显示）
- 点击 checkbox 进入多选模式，顶部出现批量操作工具栏（sticky）
- 也可通过快捷键 `Shift+点击` 范围选择

**批量操作工具栏**（sticky 在列表上方）：
```
┌─────────────────────────────────────────────────────────┐
│ [✓] 已选 5 个讨论                                        │
│                    [归档] [删除] [加标签▾] [取消选择]    │
└─────────────────────────────────────────────────────────┘
```

- 包含 running 状态时，"归档""删除"按钮 disabled，tooltip 提示"包含运行中的讨论，请先终止"
- 批量删除走软删除流程（同单个），批量归档无需确认

#### B.5.2 命令面板增强

现有 `Cmd/Ctrl+K` 命令面板增加以下命令：

- `归档: 归档当前会议`（在 Explore 页面可用）
- `删除: 删除当前会议`
- `克隆: 克隆当前会议`
- `重跑: 完整重跑当前会议`
- `阶段重跑: 从当前阶段重跑...`
- `切换视图: 归档/回收站/全部`
- `系列: 查看当前会议所属系列`

#### B.5.3 空状态引导

当用户首次使用（无任何会议）时，Board 页面不显示空表格，显示引导区：

```
┌─────────────────────────────────────────────┐
│                                             │
│           [Logo 大图标 64px]                │
│                                             │
│        开始你的第一次探索讨论                │
│   输入议题，让多 Agent 团队帮你分析          │
│                                             │
│   ┌─────────────────────────────────────┐   │
│   │ 启动一个新的探索讨论...             │   │
│   └─────────────────────────────────────┘   │
│                                             │
│   试试这些议题：                            │
│   [技术选型] [架构评审] [方案对比]          │
│                                             │
└─────────────────────────────────────────────┘
```

#### B.5.4 搜索增强

Board 搜索框支持：
- 实时搜索（300ms debounce）
- 搜索范围：标题、议题、summary、Agent 名称
- 空结果提示："未找到匹配的讨论" + [清除筛选] [查看归档] 快捷按钮
- 搜索结果中高亮匹配关键词（`<mark>` 标签，品牌色浅色背景）

---

## C. 关键组件设计

### C.1 MeetingRow（增强版）

现有 MeetingRow 仅有标题/状态/时间/删除按钮。需要增强为支持系列、归档状态、更多操作。

**Props**：

```ts
interface MeetingRowProps {
  meeting: Meeting;
  onClick: () => void;
  // 选择模式
  selectable?: boolean;
  selected?: boolean;
  onSelectChange?: (selected: boolean) => void;
  // 系列上下文
  isSeriesChild?: boolean;      // 是否是系列折叠内的子项
  seriesIndex?: number;         // 系列内序号（①②③）
  isRerun?: boolean;            // 是否为重跑会议
  rerunType?: 'full' | 'stage';
  rerunFromStage?: StageId;
  // 视图状态
  viewMode?: 'all' | 'archive' | 'trash';
  // 操作回调
  onArchive?: () => void;
  onUnarchive?: () => void;
  onDelete?: () => void;
  onRestore?: () => void;
  onHardDelete?: () => void;     // admin only
  onClone?: () => void;
  onRerun?: () => void;
  onStageRerun?: () => void;
  onViewSeries?: () => void;
  onCompare?: (otherId: string) => void;
}
```

**视觉结构**：

```
┌──────────────────────────────────────────────────────────────────┐
│ [☐] ①  标题文本（最多两行截断）                      [运行中]    │
│         2小时前 · 32条消息 · ⟳ 从证据核验重跑    [时间] [⋯]      │
└──────────────────────────────────────────────────────────────────┘
```

- 左侧 checkbox：默认 `opacity: 0`，hover row 时 `opacity: 1`，选中态常开
- 系列序号：小圆圈徽章（20px 直径，边框+数字），非系列子项不显示
- 标题：14px font-medium，`min-width: 0` + truncate
- 状态 Badge：右侧，flex-shrink-0
- 第二行：11px 文本 tertiary，包含时间、消息数、重跑标记
- 右侧操作区：hover 时显示 `⋯` 按钮，点击展开 DropdownMenu
- 回收站视图：整行 `opacity: 0.7`，标题 `line-through`
- 归档视图：正常显示，但无归档选项

**交互**：
- 点击行主体 → onClick（进入详情）
- 点击 checkbox → onSelectChange（不触发行点击）
- 点击 `⋯` → 打开操作菜单（stopPropagation）
- Hover：1px 边框 + sm 阴影（现有样式保持）

### C.2 SeriesRow（新增）

用于在列表中折叠展示同系列会议。

**Props**：

```ts
interface SeriesRowProps {
  series: {
    id: string;
    title: string;
    rootId: string;
    meetingCount: number;
    latestMeeting: Meeting;
    createdAt: string;
    totalMessages: number;
  };
  meetings: Meeting[];          // 展开时显示的子会议
  expanded: boolean;
  onToggleExpand: () => void;
  onRename: () => void;
  onViewSeries: () => void;
  onBatchArchive: () => void;
  onNewDiscussion: () => void;
  // 传递给子 MeetingRow 的回调
  onMeetingClick: (id: string) => void;
  onMeetingArchive?: (id: string) => void;
  // ... 其他 MeetingRow 回调
}
```

**视觉结构**：

折叠态：
```
┌──────────────────────────────────────────────────────────────────┐
│ ▸  系列标题文本                          [3次]  2小时前  [▾]     │
└──────────────────────────────────────────────────────────────────┘
```

展开态：
```
┌──────────────────────────────────────────────────────────────────┐
│ ▾  系列标题文本                                       [系列操作▾]│
│    3 次讨论 · 最近 2 小时前 · 创建于 7 天前                      │
├──────────────────────────────────────────────────────────────────┤
│  │  ③ 最新子会议标题...                             2h  [已完成] │
│  │  ② 子会议标题...                                  3d  [已完成] │
│  │  ① 根会议标题...                                  7d  [已完成] │
└──────────────────────────────────────────────────────────────────┘
```

- 展开箭头：16px chevron，旋转动画仅 transform（0.15s）
- 次数徽章：11px pill，`bg-bg-tertiary text-text-secondary`，"N次讨论"
- 子会议缩进：16px padding-left，左侧 2px 竖线（`border-l-2 border-border-soft`）
- 系列操作菜单：重命名、在图谱中查看、批量归档、差异对照（引导到系列详情页）

### C.3 ArchiveTrashConfirmDialog（删除/归档确认对话框）

现有 ConfirmDialog 只有简单的文本描述。管理员硬删需要输入确认，需要增强。

**Props**：

```ts
interface ArchiveTrashConfirmDialogProps {
  open: boolean;
  mode: 'soft-delete' | 'hard-delete' | 'archive' | 'restore';
  title: string;               // 会议标题
  meetingCount?: number;       // 批量操作时的数量
  // hard-delete 专属
  requireTitleConfirm?: boolean;
  expectedTitle?: string;
  // 状态检查
  hasRunningMeetings?: boolean;
  // 回调
  onConfirm: () => void;
  onCancel: () => void;
}
```

**视觉变体**：

- **soft-delete**：描述 + 回收站提示 + [取消] [移入回收站]红色
- **hard-delete**：红色警告条 + 描述 + 标题输入框 + [取消] [永久删除]红色(disabled直到标题匹配)
- **archive**：轻量描述，不需要弹窗，直接 Toast + 撤销
- **restore**：无弹窗，直接操作 + Toast

### C.4 StageRerunDialog（阶段重跑配置）

**Props**：

```ts
interface StageRerunDialogProps {
  open: boolean;
  meeting: Meeting;
  // 影响预览数据
  previewData?: {
    preservedStages: Array<{ stage: StageId; summary: string }>;
    rerunStages: Array<{ stage: StageId; description: string }>;
  };
  isPreviewLoading?: boolean;
  // 回调
  onPreview: (fromStage: StageId) => void;
  onConfirm: (fromStage: StageId, newTitle: string) => void;
  onCancel: () => void;
}
```

**内部状态**：

- `step: 'select' | 'preview'`（两步骤）
- `selectedStage: StageId`
- `newTitle: string`（默认 `{原标题} - 重跑·{stageLabel}阶段`）

### C.5 CloneDialog（克隆配置）

**Props**：

```ts
interface CloneDialogProps {
  open: boolean;
  meeting: Meeting;
  onConfirm: (config: CloneConfig) => void;
  onCancel: () => void;
}

interface CloneConfig {
  newTitle: string;
  copyDescription: boolean;
  copyAgents: boolean;
  inheritConclusions: boolean;
  copyFiles: boolean;
}
```

### C.6 DiffView（差异对照）

**Props**：

```ts
interface DiffViewProps {
  open: boolean;
  meetingA: Meeting;
  meetingB: Meeting;
  // AI 生成的差异摘要
  diffSummary?: {
    conclusionChanges: string[];
    newPerspectives: string[];
    overturnedPoints: string[];
  };
  isLoading?: boolean;
  onClose: () => void;
  onOpenMessageDiff?: () => void;
}
```

**视觉结构**：

- 顶部：两个会议的标题/时间/状态并排
- 中部：左右两栏各自的最终结论
- 底部：AI 总结的关键差异点列表（带图标标记新增/变更/推翻）
- 底部按钮：关闭 / 查看消息级差异

### C.7 BoardToolbar（看板工具栏）

提取现有搜索+筛选为独立组件，支持 Tab 切换。

**Props**：

```ts
interface BoardToolbarProps {
  currentView: 'all' | 'archive' | 'trash';
  onViewChange: (view: 'all' | 'archive' | 'trash') => void;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  statusFilter?: MeetingStatus[];
  onStatusFilterChange: (s: MeetingStatus[]) => void;
  sortBy: 'created_desc' | 'created_asc' | 'activity_desc' | 'messages_desc';
  onSortChange: (s: string) => void;
  totalCount: number;
  loadedCount: number;
  // 批量选择
  selectedCount: number;
  onBatchArchive: () => void;
  onBatchDelete: () => void;
  onBatchTag: (tag: string) => void;
  onClearSelection: () => void;
}
```

**视觉结构**：

```
┌─────────────────────────────────────────────────────────┐
│ [全部] [归档] [回收站]          会议数: 128             │
├─────────────────────────────────────────────────────────┤
│ [搜索.................] [状态▾] [标签▾] [排序▾] [时间▾] │
└─────────────────────────────────────────────────────────┘
```

- Tab 行：左侧 Tab 组，右侧总数统计
- 筛选行：搜索框（flex: 1）+ 筛选器下拉
- 选中 N 项时，筛选行替换为批量操作栏（黄色强调背景 `rgba(184,125,43,0.06)`）

### C.8 AutoArchiveBanner（自动归档提示横幅）

**Props**：

```ts
interface AutoArchiveBannerProps {
  count: number;              // 可归档数量
  oldestDate: string;
  onViewArchivable: () => void;
  onArchiveAll: () => void;
  onDismiss: () => void;
  isArchiving?: boolean;
}
```

**视觉结构**：

- 浅色信息背景 `bg-brand-soft`，左侧一个归档图标（box 图标），中间文字，右侧按钮组
- 8px 圆角，1px 边框 `border-brand-500/20`
- 不使用 error/warning 红色，使用品牌色浅色（归档是建议，不是警告）

### C.9 RerunNoticeBar（重跑关联提示条）

在 Explore 页面顶部显示。

**Props**：

```ts
interface RerunNoticeBarProps {
  type: 'has-rerun' | 'is-rerun';
  relatedMeeting: { id: string; title: string; stage?: StageId; time: string };
  onNavigate: (id: string) => void;
}
```

**视觉结构**：

- 高度 h-9，浅色背景，居中文字
- `has-rerun`：灰蓝背景（信息色），显示"此讨论有 N 个后续版本"
- `is-rerun`：浅色靛蓝背景，显示"此讨论从 XXX 的「XX阶段」重跑而来"
- 右侧一个小箭头链接，点击跳转关联会议

---

## D. 空状态/加载状态/错误状态设计

### D.1 空状态

| 视图 | 空状态内容 |
|------|-----------|
| 全部 Tab（新用户） | Logo 图标 + "开始你的第一次探索讨论" + 新建按钮 + 示例议题快捷按钮 |
| 全部 Tab（有归档/回收站） | "暂无活跃讨论" + [启动新讨论] + [查看归档] [查看回收站] 文字链接 |
| 归档 Tab | 归档图标 + "暂无归档讨论" + 说明文字"已完成且不常查看的讨论可以归档" |
| 回收站 Tab | 垃圾桶图标 + "回收站是空的" + "已删除的讨论会在这里暂存 30 天" |
| 搜索无结果 | 搜索图标 + "未找到匹配「xxx」的讨论" + [清除搜索] [在归档中搜索] 按钮 |
| 系列详情页无会议 | 不应出现（系列至少有根会议） |
| 差异对照无第二会议 | "请选择另一个讨论进行对照" + 最近会议列表快捷选择 |

**空状态统一视觉规范**：
- 居中布局，py-16
- 图标 48px，`text-text-tertiary`，不使用彩色大插画
- 主文字 14px font-medium `text-text-secondary`，副文字 12px `text-text-tertiary`
- 操作按钮：主按钮（如有）+ 文字链接
- 禁止使用装饰性几何图形/插画

### D.2 加载状态

**列表加载**：
- 首次加载：显示 5 个 Skeleton 行（高度同 MeetingRow）
- 加载更多（infinite scroll）：列表底部显示 spinner（20px）+"加载中..."文字
- 切换 Tab：显示 3 个 Skeleton 行（非首次加载不需要全屏 spinner）

**Skeleton 规格**：
- 每行高度 52px（同 MeetingRow），8px 圆角
- 标题区域：w-48 h-3 rounded（40% 透明度灰）
- 元信息区域：w-24 h-2 rounded mt-2
- 使用 `animate-pulse` 或 shimmer 效果

**对话框加载**：
- 影响预览加载：Dialog 内区块显示 skeleton spinner，不锁死整个对话框
- 克隆/重跑提交中：按钮显示 spinner，disabled，"处理中..."

**操作反馈**：
- 删除/归档/恢复等即时操作：Toast 反馈（2s 自动消失）
- 克隆/重跑创建会议：按钮 loading → 成功后直接跳转，Toast 在跳转后页面显示
- 批量操作：进度 Toast（"正在归档 5/12..."），完成后"已归档 12 个讨论"

### D.3 错误状态

| 场景 | 处理方式 |
|------|---------|
| 列表加载失败 | 列表区域显示：错误图标 + "加载失败" + 错误消息 + [重试] 按钮 |
| 删除/归档/恢复失败 | Toast 错误提示（红色），含错误消息，操作不撤回（列表状态不变） |
| 硬删失败（权限） | "您没有永久删除的权限"（403 时） |
| 克隆/重跑失败 | Dialog 内错误提示（红色文字在底部），不关闭 Dialog，允许重试 |
| 影响预览加载失败 | StageRerunDialog 内显示"加载影响预览失败" + [重试]，允许跳过预览直接重跑 |
| running 会议禁删/归档 | 菜单项 disabled + hover tooltip（不是点击后报错，前置防错） |
| 分页参数错误 | 修复前端分页 bug 后不应出现；若后端返回 400，重置到第一页 + Toast |

**错误状态统一规范**：
- 使用错误色 `#c53030`，背景 `rgba(197,48,48,0.06)`
- 错误信息必须具体：不要"操作失败"，要"讨论正在运行中，无法删除（code: meeting_running）"
- 提供恢复路径：[重试] 按钮或具体操作建议
- 禁止空白错误页，即使出错也要保留导航栏和基本框架

---

## E. 响应式考虑

### E.1 断点策略

沿用 Tailwind 默认断点，针对 Conclave 场景调整：

| 断点 | 宽度 | Board 布局 |
|------|------|-----------|
| Mobile | < 640px | 单列列表，无卡片网格，操作菜单简化 |
| Tablet | 640-1024px | 进行中 2 列卡片，历史列表正常 |
| Desktop | 1024-1280px | 进行中 3 列卡片（现有） |
| Wide | > 1280px | 进行中 3 列，列表最大宽 5xl 居中，两侧留白 |

### E.2 Mobile 适配（< 640px）

**NavRail**：
- 现有 w-14 侧栏保留但考虑改为底部导航（Tab Bar），w-14 在手机上过宽占用空间
- 建议方案：< 640px 时 NavRail 变为底部 Tab Bar（h-14），仅保留 5 个核心项：看板、探索(最近)、图谱、报告、设置
- 其他功能（Agent/模型/团队/管理）通过设置页面或"更多"菜单访问

**Board 页面**：
- 进行中卡片单列 1 列，非网格
- 新建区域 textarea min-h 减小到 64px
- 工具栏：搜索框占满宽度，筛选器收入"筛选"下拉按钮（不横向排列）
- MeetingRow：
  - 不显示消息数、Agent 数等辅助元信息（只显示时间+状态）
  - `⋯` 菜单常开（不 hover 才显示），因手机无 hover
  - 系列子项缩进减小到 12px
- Tab 栏横向可滚动（如果 Tab 太多）

**对话框**：
- 全屏 Dialog（底部滑入样式），非居中模态
- ConfirmDialog/CloneDialog/StageRerunDialog 在手机上占满屏幕宽度
- 标题输入框等控件全宽

**批量操作**：
- 手机不支持 Shift+点击范围选择
- checkbox 常开显示（不依赖 hover）
- 批量操作栏固定在底部（非顶部 sticky）

**差异对照**：
- 手机不做左右分栏，改为上下堆叠（先 A 结论，再 B 结论，再差异列表）
- 或仅显示"关键差异"列表，隐藏双栏结论对比

### E.3 系列折叠响应式

- < 640px：系列展开默认只显示最近 2 个子会议，底部有"查看全部 N 次讨论"展开按钮
- > 640px：展开显示所有子会议（单次系列一般不超过 10 个，性能可控）

### E.4 图谱响应式

- < 768px：图谱页面简化为列表视图（节点太多在手机上无法交互）
- 提供"在桌面端查看完整图谱"提示
- 系列分组开关在手机上收入"视图选项"下拉

### E.5 通用交互适配

- 所有可点击元素最小尺寸 32x32px（现有规范保持）
- 下拉菜单在手机上改为底部 Action Sheet（Radix UI 的 DropdownMenu 在移动端可考虑 AlertDialog 替代）
- Tooltip 在手机上不显示（touch 无 hover），关键信息直接展示在 UI 上
- 横向滚动区域（Tab 栏、筛选标签）加滚动指示器（右侧渐变遮罩提示可滚动）

---

## 附录：前端技术实现要点

### 需要新增的 API 端点（前端需要对接）

```
POST   /meetings/{id}/archive              # 归档
POST   /meetings/{id}/unarchive            # 取消归档
POST   /meetings/{id}/trash                # 软删除
POST   /meetings/{id}/restore              # 恢复
DELETE /meetings/{id}/hard                 # 硬删（admin）
POST   /meetings/{id}/clone                # 克隆
POST   /meetings/{id}/rerun                # 完整重跑
POST   /meetings/{id}/stage-rerun          # 阶段重跑
GET    /meetings/{id}/stage-rerun-preview  # 阶段重跑影响预览
GET    /series/{id}                        # 系列详情
GET    /meetings?status=archived           # 归档列表
GET    /meetings?status=trashed            # 回收站列表
GET    /meetings?series_id={id}            # 按系列筛选
```

### 需要修复的 Bug

- **分页参数不匹配**：`useMeetings` hook 中 `page/page_size` 改为 `limit/offset` 或统一后端为 cursor-based 分页，确保分页正确
- 前端 `normalizeMeeting` 中 metadata 字段需要扩展 `archived`/`deleted_at`/`series_id`/`parent_meeting_id`/`rerun_type`/`rerun_from_stage`

### Meeting 类型扩展

```ts
interface Meeting {
  // ...现有字段
  archived?: boolean;
  archived_at?: string;
  deleted_at?: string | null;
  series_id?: string | null;
  parent_meeting_id?: string | null;
  rerun_type?: 'full' | 'stage' | null;
  rerun_from_stage?: StageId | null;
  tags?: string[];
  last_viewed_at?: string;
}
```

### 新增路由

```tsx
<Route path="/series/:seriesId" element={<SeriesDetailPage />} />
```

Tab 状态通过 query string 管理（`/board?view=archive`），不新增路由组件。

### Zustand Store 扩展

现有 `meeting-slice` 需要增加：
- `viewMode: 'all' | 'archive' | 'trash'`
- `selectedMeetings: Set<string>`（批量选择）
- `searchQuery`、`filters` 等列表状态

### TanStack Query Keys 扩展

```ts
meetingKeys.list({ view: 'archive', status: 'done' })
meetingKeys.series(id)
meetingKeys.rerunPreview(id, stage)
```

---

> 设计遵循 ui_design_system.yaml 规范：品牌色 #335c8e、8px 圆角、极轻阴影、0.15s 过渡、禁止大面积渐变/3D/重阴影、Notion 风格扁平表格/列表、4px 间距基准。
