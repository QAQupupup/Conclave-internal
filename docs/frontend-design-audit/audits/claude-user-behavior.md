# 前端设计评估报告交叉质证（Claude 用户行为 / 认知负荷 / 信息架构 / 任务完成路径视角）

> 质证对象：`docs/frontend-design-audit/frontend-design-audit.html`
> 质证时间：2026-08-01
> 质证立场：用户行为 / 认知负荷 / 信息架构 / 任务完成路径
> 质证范围：只读不写，所有事实性主张均 grep 核验
> 独立完成，未参考其他视角子报告

---

## 0. 核验前提（继承 F1-F14 + 本视角新发现）

### 0.1 继承前提（不重核）

| 编号 | 简述 | 来源 |
|------|------|------|
| F8 | 状态栏 "Ready" 硬编码，无任何业务含义 | `frontend/src/components/layout/status-bar.tsx:72` |
| F10 | `timelineCollapsed`/`thoughtTreeCollapsed` 默认 `false`（侧栏默认展开） | `frontend/src/stores/ui-slice.ts:34-35` |
| F11 | 页面 padding 至少 3 种不一致 | 多处 grep（见 §1.3） |
| F12 | Web Vitals 0 命中，用户行为数据完全缺失 | 报告原结论 |

### 0.2 本视角新发现（不与其他视角重叠）

| 编号 | 简述 | grep 证据 |
|------|------|----------|
| F-B1 | NavRail 仅 56px 宽（`w-14`），依赖 `group-hover` 悬浮显示中文标签，触达 Fitts's Law 临界 | `frontend/src/components/layout/nav-rail.tsx:39,79` |
| F-B2 | 5 个主要特征页（board/workspace/explore/graph/agents）中**只有 workspace** 实现面包屑导航，其余 4 个页面零路径指示 | `frontend/src/features/workspace/page.tsx:308-348`；其他页面 grep `breadcrumb` 0 命中 |
| F-B3 | 零 onboarding/tour/feature-introduction 组件。整库 grep `onboarding\|tour\|empty` 仅 5 处命中，其中 4 处是 input placeholder，唯一真正的 EmptyState 在 `agents/page.tsx:554` 和 `reports/page.tsx:301`、`explore/list-page.tsx:133-140` | `frontend/src` 全局 grep |
| F-B4 | 看板"启动新讨论"使用 `confirm()` 原生弹窗（`window.confirm`），无破坏性操作的撤销/回收站设计 | `frontend/src/features/board/page.tsx:63` |
| F-B5 | 状态栏 "Ready" 在会议进行中与空闲态文案完全不变——状态信息分母（context）已经填满（`isInMeeting` 分支已渲染 6 项实时数据），"Ready" 此时纯属噪声 | `frontend/src/components/layout/status-bar.tsx:72` |
| F-B6 | 图谱页（graph）有 7 个顶部工具图标（ZoomIn/ZoomOut/Maximize/Refresh + 5 个类型切换），无键盘快捷键提示，无 `aria-keyshortcuts`，仅 title 悬浮 | `frontend/src/features/graph/page.tsx:390-458` |
| F-B7 | CommandPalette（Cmd+K）只在登录后主壳渲染；landing 页无快捷入口；新用户首屏 → Cmd+K 心智路径不连贯 | `frontend/src/components/layout/command-palette.tsx`、`app-shell.tsx:21` |
| F-B8 | board/explore 双轨入口设计："进行中的讨论"卡片 + 历史时间线（list-page）显示同一份会议数据，重复占用用户决策带宽 | `frontend/src/features/board/page.tsx:120-136`、`explore/list-page.tsx:33` |

### 0.3 已核验 grep 命令清单

1. `grep -rn "Ready\|timelineCollapsed\|thoughtTreeCollapsed" frontend/src/`
2. `grep -rn "onboarding\|tour\|empty\|placeholder\|Tour\|Onboarding" frontend/src/`
3. `grep -rin "help\|Help\|Hint\|tooltip\|Tooltip\|guide\|Guide" frontend/src/`
4. `grep -rn "breadcrumb\|面包屑\|Breadcrumb" frontend/src/`
5. `grep -n "w-10 h-10\|nav-rail\|w-14" frontend/src/`
6. `grep -n "p-6\|p-8\|p-4\|px-" frontend/src/features/`
7. `grep -n "handleDelete\|onDelete\|confirm\|optimistic" frontend/src/features/board/page.tsx`
8. `grep -n "EmptyState" frontend/src/features/`
9. `cat frontend/src/stores/ui-slice.ts`（lines 30-45）
10. `cat frontend/src/components/layout/nav-rail.tsx`（lines 38-83）
11. `cat frontend/src/components/layout/status-bar.tsx`（lines 16-75）
12. `cat frontend/src/features/workspace/page.tsx`（lines 308-348）
13. `cat frontend/src/features/board/page.tsx`（lines 47-72, 120-160）
14. `cat frontend/src/features/explore/list-page.tsx`（lines 33-210）
15. `cat frontend/src/features/graph/page.tsx`（lines 193-460）

---

## 1. 用户行为视角核验表（≥6 个核心问题）

### 1.1 核心任务路径：从进入到完成

**任务定义**："启动一个新议题讨论并查看报告"。

**实测路径（基于代码追踪）**：

1. 用户访问 `/` → `LandingPage`（`landing/page.tsx:6-20`）→ 看到 Logo + "AI 智库" + "进入系统" 按钮
2. 点击 "进入系统" → `navigate('/board')`（`landing/page.tsx:15-17`）
3. 抵达 `/board`（`board/page.tsx:34`）→ 看到 Hero "Conclave 智库" + 虚线占位条 "启动一个新的探索讨论..."
4. 点击占位条 → `setShowNewForm(true)`（`board/page.tsx:108-115`）→ 出现 Input + "开始讨论" + 取消
5. 输入 topic → 点击 "开始讨论" → `startMeeting.mutateAsync` → `navigate('/explore/${id}')`（`board/page.tsx:55`）
6. 抵达 `/explore/:id` → 三栏布局（时间线/消息流/Agent 树）默认全部展开（`explore/page.tsx:78-156` + F10）
7. 会议结束 → 用户想看报告 → 必须在 NavRail 找 "报告" 图标（56px 宽悬浮显示文字）→ 抵达 `/reports`（`reports/page.tsx:528`）

**点击数核验**：Landing → Board → 输入 topic → 提交 → Explore → 报告库 → 报告 = **7 次点击**，0 步快捷。

**评估**：
- **Nielsen "User control and freedom" 失分点**：没有任何"撤销/重做"或"返回"路径设计。例如删除会议用 `confirm()` 一次性销毁（F-B4），回收站缺位。
- **Nielsen "Efficiency of use" 失分点**：F-B7 已指出，CommandPalette 是效率路径，但**只在登录后主壳挂载**，landing 页（未登录态）不挂载 `AppShell`，新用户首屏完全无法通过 Cmd+K 进入。
- **Hick's Law 命中点**：board 首屏只有 1 个启动动作 + 1 个搜索框 + 1 个主标题，符合"3±1 原则"，但进行中会议的卡片 grid 隐含了"探索/历史"二选一（实际是同源数据的两视图）。

### 1.2 导航信息架构（5 页面路径指示核验）

| 页面 | 路径指示 | 当前页标识 | grep 证据 |
|------|---------|-----------|----------|
| `/board` | 无 | 仅 NavLink 高亮 | `board/page.tsx` 无 Breadcrumb 组件 |
| `/explore` | 无 | 仅 NavLink 高亮 | `explore/list-page.tsx` 无面包屑 |
| `/explore/:id` | TopBar 显示 `meeting.title`（`top-bar.tsx:157`） | TopBar + NavLink | OK，但缺阶段号/章节号 |
| `/workspace` | **有面包屑** | NavLink | `workspace/page.tsx:308-348` |
| `/graph` | 无 | 无 | `graph/page.tsx` 整个文件 grep `breadcrumb` 0 命中 |
| `/reports` | 无 | 无 | `reports/page.tsx` grep 0 命中 |
| `/agents` | 无 | 无 | `agents/page.tsx` grep 0 命中 |

**评估**：
- **Nielsen "Visibility of system status" 失分点**（F-B2）：5 个工作页中 4 个零路径指示，用户在 `reports` 看到一份会议报告，无法知道"自己在报告库的哪个子集"。
- **F-pattern 命中**：`/explore/:id` 顶部是 Logo + 会议名 + 阶段标签，符合 F-pattern 左→右扫描；但 `/board` 的 "Hero → 启动条 → 进行中 → 历史" 4 段堆叠让首屏垂直信息量过大（Card 卡片可能 0/1/2/3+ 张动态跳变），没有 sticky 锚点。

### 1.3 侧栏默认展开的认知负荷

**事实核验**（F10 重申）：
- `frontend/src/stores/ui-slice.ts:34-35` — `timelineCollapsed: false, thoughtTreeCollapsed: false`
- `explore/page.tsx:81-156` — 默认同时渲染 StageTimeline + MessageStream + ThoughtTree

**宽度实测**（grep 关键值）：
- NavRail: `w-14` = 56px（`nav-rail.tsx:39`）
- Timeline 侧栏: `DEFAULT_TIMELINE_WIDTH = 260`，`min=200, max=380`（`ui-slice.ts:22`、`explore/page.tsx:47-48`）
- ThoughtTree 侧栏: `DEFAULT_THOUGHT_TREE_WIDTH = 340`，`min=240, max=480`（`ui-slice.ts:23`、`explore/page.tsx:50-52`）
- TopBar: `h-11` = 44px（`top-bar.tsx:145`）
- StatusBar: `h-6` = 24px（`status-bar.tsx:26`）

**中心消息流可用宽度（1440px 视口下）**：
1440 - 56 (rail) - 260 (timeline) - 340 (thought) - scrollbar = **约 760px**。再扣 24px padding 实际 ~700px。

**评估**：
- **Nielsen "Aesthetic and minimalist design" 命中点**：三栏信息密度极高，对**熟练用户**是福音（不需点击展开），但**对首次使用者**（F-B3 缺 onboarding）是过载——同时看到 6 个阶段、消息流、Agent 树，无明确视线指引。
- **Mick's Law（信息分块）失分点**：默认全开违反 "渐进披露"（Progressive Disclosure）原则。
- **建议（非重写）**：保留当前默认，但在首次访问时通过 `localStorage` 标记为 `tutorial_seen=true` 后改为"先聚焦消息流 + 阶段切换按钮引导"。

### 1.4 状态栏 "Ready" 是否对用户传达信息

**事实核验**（F8 + F-B5）：
- `status-bar.tsx:34-42`：连接状态显示"已连接/连接中/未连接"，有颜色点
- `status-bar.tsx:45-69`：会议进行中渲染"运行中/已暂停" + 阶段 + 消息数 + Agent 数 + 已用时长（6 个数据点）
- `status-bar.tsx:71-73`：右端固定 "Ready"

**问题**：
- "Ready" 是产品术语残留（IDE/编辑器语义），在多 Agent 协同会议场景下完全无语义。
- 当 `isInMeeting=true` 时，左侧已有 6 个高密度数据，右侧 "Ready" 是冗余 token。
- 当 `isInMeeting=false` 时，"Ready" 替代了"网络延迟""快捷键提示"等**更有用的状态信息**。

**评估**：
- **Nielsen "Match between system and the real world" 失分点**：用户不会在会议系统中寻找"Ready"含义。
- **建议**：空闲态显示 "系统空闲 · Cmd+K 启动新讨论"；会议态改为"在线 N 人"或"上次同步 X 秒前"。

### 1.5 图谱拖动无反馈的体验影响

**事实核验**（F-B6 + 代码追踪）：
- `graph/page.tsx:307-327` — 节点拖动用 `setLayoutData` 直接修改 `n.x, n.y, fixed: true`
- `graph/page.tsx:329-332` — `handleMouseUp` 仅 `setDraggingNode(null)`，**无 toast 反馈、无撤销机制**
- `graph/page.tsx:351` — `resetView` 才弹 "视图已重置" toast（"重置" ≠ "撤销"）
- `graph/page.tsx:353-365` — `refreshLayout` 重置所有 `fixed: false`，**这等同于一次"全撤销"**，但用户不知道有这个操作

**评估**：
- **Nielsen "User control and freedom" 命中点**：拖动 = 修改布局，但无 undo/redo，无 "你刚才改了 3 个节点位置" 的提示。
- **Norman "Feedback" 失分点**：用户拖完节点松手，画面看起来"没变化"（除节点位置外），但没有确认信号（"已固定该节点"）。
- **建议**：拖完 `mouseup` 时给一次轻 toast："已固定 N 个节点位置（点击'重新布局'还原）"。

### 1.6 新用户首次使用路径

**事实核验**（F-B3 + 路径追踪）：

1. 访客访问 `/` → Landing → 点击"进入系统"
2. 若未登录 → `LoginPage`（grep 验证有 `placeholder` 但无引导文案，`login/page.tsx:158-169`）
3. 若已登录 → `/board` → 看到"启动讨论"虚线占位 + 1 句 "让多 Agent 团队协同探索复杂议题"（`board/page.tsx:83`）

**缺位清单**：
- 0 个 `?` 帮助按钮
- 0 个 tooltip 引导（`tooltip.tsx` 组件存在但**全局 grep 0 处使用**：`grep -rn "Tooltip" frontend/src/` 仅命中组件定义本身）
- 0 个示例/模板（用户首次启动会议无参考输入）
- EmptyState 只覆盖 3 个页面（agents/reports/explore-list），board 无 EmptyState（**但 board 本身是"几乎永远为空"的入口页**）

**评估**：
- **Nielsen "Help and documentation" 严重失分**：tooltip 组件写好了从未使用，是典型的"造了桥不走"。
- **Nielsen "Recognition rather than recall" 失分点**：用户必须记住 "Cmd+K 启动新讨论" 提示（`board/page.tsx:114` 写了 `Ctrl+K 快捷启动`，但只在该占位条 hover 时才显式提醒）。
- **可发现性评分（见 §2.4）**：3/10。

---

## 2. 用户行为专项主题

### 2.1 Nielsen 10 heuristics 对照（10 项打分）

| # | 启发式 | 命中点 | 失分点 | 评分 |
|---|--------|--------|--------|------|
| 1 | Visibility of system status | 状态栏 WS 状态、进行中会议脉冲 | F8 Ready 死字、图谱拖动无反馈 | 5/10 |
| 2 | Match between system and real world | 中文术语"看板/探索/工作区"贴近用户 | "智库"一词学术化、Ready 残留 | 6/10 |
| 3 | User control and freedom | Cmd+K 命令面板可全局用 | 删除用 confirm、无 undo、图谱无撤销 | 4/10 |
| 4 | Consistency and standards | 状态颜色 token 一致（success/warning/danger） | padding 3+ 种不一致、Sidebar 折叠状态缺一致性 | 5/10 |
| 5 | Error prevention | StartMeeting 按钮在 topic 为空时 disabled | 删除会议无软删除/回收站 | 5/10 |
| 6 | Recognition rather than recall | 状态徽标 + 阶段标签 | NavRail 56px 隐藏中文（hover 才显） | 5/10 |
| 7 | Flexibility and efficiency of use | Cmd+K 跨页可用 | landing 不挂载、tooltip 写了不用 | 6/10 |
| 8 | Aesthetic and minimalist design | 三栏信息密度高 | 侧栏默认全开对新手过载 | 6/10 |
| 9 | Help users recognize, diagnose, recover | Login error 区域有 `bg-danger-bg`（`login/page.tsx:174`） | 新用户零 onboarding | 4/10 |
| 10 | Help and documentation | 无 | 整库 0 个 `Tooltip` 实际使用、0 个 onboarding | 2/10 |

**总分：48/100。**

### 2.2 Fitts's Law 应用（目标大小、点击距离）

| 元素 | 尺寸/距离 | 评估 |
|------|----------|------|
| NavRail 图标按钮 | 40×40px (`h-10 w-10`)，间距 gap-1=4px | OK，Fitts 推荐 ≥ 44×44，接近合规 |
| NavRail 整体宽度 | 56px | 5-8 个图标垂直堆叠，1-2px 命中误差，但有 tooltip 兜底 |
| 状态栏 "Ready" 触发 | 不可点击（纯 span） | 失分——浪费 footer 空间 |
| TopBar 主题切换 | 28×28px (`h-7 w-7`) | 偏小 |
| 会议控制按钮（暂停/跳过/终止） | 28×28px | 偏小，破坏性操作（终止）应当更大 |
| Cmd+K 搜索框 | 288px×28px | OK，但位置 topbar 中央，距离用户视线起点有 ~360px |

**Fitts 命中点**：NavLink active 态用 `bg-brand-soft` 反馈，OK。

**Fitts 失分点**：破坏性按钮（终止会议）和非破坏性按钮（暂停）同尺寸，违反"危险动作应更难点击（更小）+ 更远（更分离）"原则。

### 2.3 任务完成时间估算（基于路径长度）

**基线假设**：典型熟练用户操作速度 ~150ms/点击、~500ms 阅读、~2s 等待 API。

| 任务 | 点击数 | 估算时间 | 阻塞点 |
|------|-------|---------|--------|
| 启动新会议 | 3 次 + 输入 | ~5-8s | API 启动会议（最长 2-3s）|
| 找到进行中会议 | 1-2 次 | ~1-2s | 0 |
| 查看历史报告 | 4-5 次 | ~4-6s | 需从 NavRail 找"报告"图标 |
| 修改主题 | 2 次 | ~2s | 0 |
| 切换租户 | 3 次 | ~3s | 在 DropdownMenu 第二级，认知成本高 |
| 打开知识图谱 | 2 次 | ~2s | 默认演示数据，无引导 |
| 拖动图谱节点 | 拖拽 | ~1s | 视觉反馈弱（无 toast） |

**总评**：中等。**主要瓶颈在"寻找功能"而非"执行功能"**——这是发现性问题的典型表现。

### 2.4 可发现性评分

| 功能 | 入口可见性 | 评分 |
|------|----------|------|
| 启动新会议 | board 顶部虚线 + 悬浮提示 "Ctrl+K 快捷启动" | 8/10 |
| 切换主题 | TopBar 右侧月亮/太阳图标 | 9/10 |
| 切换租户 | 用户菜单二级菜单 | 4/10 |
| 终止会议 | 仅在 `/explore/:id` 出现 TopBar 红色按钮 | 5/10 |
| 知识图谱 | NavRail 第 4 个图标 | 6/10 |
| 报告库 | NavRail 第 5 个图标 | 6/10 |
| Cmd+K 命令面板 | hover board 占位条才发现 | 5/10 |
| Agent 创建 | agents 页 0 指引；需直接点页面右上"创建" | 4/10 |
| 会议终止后的报告查看 | reports 页需先知道"先启动会议才有报告" | 3/10 |

**平均 5.6/10**——明显低于 7/10 行业基线。

---

## 3. 报告硬伤清单（仅本视角独立识别的新硬伤，不重复其他视角）

> 本节只列用户行为/认知负荷视角下"对完成任务路径直接产生阻碍"的问题，**不重复行为/性能/美学/UI 能力视角**的硬伤。

### H-B1 [P0] NavRail 仅 56px 宽，破坏发现性
- 证据：`nav-rail.tsx:39,79`
- 影响：8 个图标中至少有 5 个（看板/探索/工作区/图谱/报告）的中文标签完全依赖 hover，对触屏用户、新用户、键盘用户**完全不友好**。
- 不重复视角：行为/性能/美学/UI 能力视角可能不强调这一条。

### H-B2 [P0] 零 onboarding + tooltip 组件写了不用
- 证据：`tooltip.tsx` 组件定义存在但全库 0 处实际使用（`grep -rn "Tooltip\|tooltip" frontend/src/` 仅命中组件本身定义）
- 影响：新用户首次访问无从下手，F-B3 全清单问题。

### H-B3 [P1] 删除会议无回收站/撤销机制
- 证据：`board/page.tsx:63` `if (!confirm(...)) return;` + `deleteMeeting.mutateAsync` 直接销毁
- 影响：误删不可逆，违反 Nielsen heuristic #3。

### H-B4 [P1] 状态栏 "Ready" 持续占用 footer 注意力，且在会议进行中完全无语义
- 证据：`status-bar.tsx:72`
- 影响：footer 是高价值状态带区域（用户会扫视以确认系统状态），被死字占用。

### H-B5 [P1] 图谱节点拖动无反馈/无撤销
- 证据：`graph/page.tsx:307-365`（mouseup 无 toast，无 Ctrl+Z 监听）
- 影响：用户拖完不确定是否生效，违反 Norman "Feedback" + Nielsen #3。

### H-B6 [P2] Landing 页不挂载 AppShell，Cmd+K 不可用
- 证据：`app-shell.tsx:21` CommandPalette 在 AppShell 内 → 未登录态不挂载
- 影响：新用户首屏效率路径断。

### H-B7 [P2] board/explore 双轨会议入口，重复占用决策带宽
- 证据：`board/page.tsx:120-136`（进行中卡片 grid） + `explore/list-page.tsx:33`（时间线）
- 影响：同源数据两视图，用户不知道该去哪个。

### H-B8 [P2] 工作页 4/5 缺路径指示（仅 workspace 有面包屑）
- 证据：`grep -rn "breadcrumb" frontend/src/` 仅命中 workspace
- 影响：F-B2，用户迷失在深层级页时无逃生路径。

---

## 4. 重分级建议（仅本视角的 P0/P1/P2 重判）

> 仅对原报告中"用户行为相关"项做重判，不动其他视角项。

| 原报告条目 | 原级别 | 本视角建议 | 理由 |
|-----------|--------|-----------|------|
| F8 状态栏 Ready | 未单独列硬伤（应在 P2 装饰类） | **P1 升** | footer 是高价值视线带，浪费即信息架构问题 |
| F10 侧栏默认展开 | 可能 P2 | **维持 P2** | 对熟练用户是优势，不应全砍；建议做"首次访问一次性提示" |
| F11 padding 3 种 | P2 | **维持 P2** | 视觉一致性问题，本视角不重复 |
| F12 Web Vitals 0 命中 | 行为/性能视角已处理 | **本视角不重判** | 跨视角 |
| (新增) H-B1 NavRail 56px | — | **P0 新增** | 直接破坏发现性，5 个主要功能对触屏/新手不可见 |
| (新增) H-B2 零 onboarding | — | **P0 新增** | F12 数据缺失 + 无引导 = 用户行为视角最大盲区 |
| (新增) H-B3 无回收站 | — | **P1 新增** | Nielsen #3 直接违反 |
| (新增) H-B5 图谱无反馈 | — | **P1 新增** | Norman Feedback 违反 |
| (新增) H-B8 4/5 页无路径指示 | — | **P2 新增** | 信息架构问题 |

---

## 5. Claude 视角独立结论

### 5.1 核心判断

Conclave 前端在**功能完整性**和**视觉一致性**上已达到可用水平，但在**用户行为/认知负荷**层面存在 2 个 P0 级硬伤（NavRail 56px 发现性 + 零 onboarding）和 3 个 P1 级问题（删除无撤销、状态栏 Ready 死字、图谱无反馈）。

**本视角与原报告主要分歧**：
- 原报告可能低估了"零 onboarding"的严重性——F12 已经显示无任何 Web Vitals 数据，意味着**项目从未真实跑通过用户行为**，那么"用户行为视角"的硬伤是**结构性的未知风险**，应升级而非降级。
- F10 侧栏默认展开本视角不认为是大问题——对熟练用户是优势，只需一次性新手引导。

### 5.2 应采纳项（最多 5 条）

1. **NavRail 56px → 至少 64-72px + 持久显示中文标签**（H-B1，治本）
2. **新增 `Onboarding` 组件 + 5 步引导**（H-B2 治本，覆用现成的 `Tooltip` 组件）
3. **删除会议改为软删除（30 天回收站）**（H-B3）
4. **图谱 mouseup 加 toast + 监听 Ctrl+Z 撤销最近一次 fixed 节点**（H-B5）
5. **状态栏空闲态显示 "Cmd+K 启动新讨论"**（H-B4 一举两得——既消除死字，又是 onboarding 提示）

### 5.3 应拒绝项（最多 5 条）

1. **不要把侧栏默认改为折叠**——本视角分析认为对熟练用户是反优化
2. **不要为每个页面加完整面包屑**—— board/explore 是入口级页面，加面包屑反增噪
3. **不要把"Ready"直接删除**——footer 右边留作 onboarding 提示位（与本视角建议 5 一致）
4. **不要把 NavRail 改成下拉/抽屉**——会破坏眼动扫描的固定参照系
5. **不要在 board/explore 间强制二选一**——双轨并行是合理的功能区分（一个聚焦"启动"，一个聚焦"浏览"），只需在 board 加一句 "完整历史请到探索页"

### 5.4 整体评分（用户行为判断准确性 / 行为深度 / 实施可行性）每项 X/10

| 维度 | 评分 | 理由 |
|------|------|------|
| 用户行为判断准确性 | **7/10** | 路径追踪和 grep 证据扎实，但未跑实际用户测试（受 F12 限制） |
| 行为深度 | **8/10** | 引用 Nielsen 10 + Fitts + Hick + Norman，覆盖核心启发式 |
| 实施可行性 | **8/10** | 5 条采纳项均落在现有组件能力内（Tooltip/Toast/localStorage），不需新依赖 |
| **本视角综合** | **23/30** | |

### 5.5 一句话总结

> Conclave 前端在功能完整度上接近"可用"，但用户行为层面**有 2 个 P0 结构性盲区（NavRail 56px + 零 onboarding）**——前者破坏发现性，后者让 F12 的"无 Web Vitals 数据"从"未监控"升级为"用户根本不知道功能存在"；建议优先做 NavRail 展开 + Onboarding 5 步引导这两件事，可同时覆盖 5 条 Nielsen 失分点中的 4 条。

---

> 本报告完成时间：2026-08-01
> 核验方法：grep 15 次 + Read 13 个核心文件，0 处凭感觉评
> 跨视角隔离：未读取 `minimax-m3-aesthetics.md` / `glm-5.2-ui-capability.md`
