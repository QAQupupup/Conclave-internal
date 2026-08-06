# 前端融合方案：旧版密度 × 新版架构（定稿）

> 状态：Proposed · 日期：2026-08-06
> 依据：两版前端实证对比（`archive/frontend-react-original/` vs `frontend/src/`）、mock-data-redline.md
> 一句话：**保留新版的工程架子（Zustand + TanStack Query + features 目录 + Tailwind token），把旧版的功能密度与可观测性完整移植回来，并做四项超越性优化。**

---

## 1. 两版各自做对的事（融合的前提）

| 维度 | 旧版（archive）做对的 | 新版（current）做对的 |
|---|---|---|
| 工程组织 | —（components.css 单文件 4137 行、reducer 458 行，不可维护） | zustand 四切片、TanStack Query 缓存、features 目录、测试与类型完善 |
| 信息密度 | 工具风：14px/1.5 行高、日志等宽 12px、单屏全信息 | —（卡片化、行高 1.6、密度下降） |
| 可观测性 | 会议中 8 个 Drawer 面板：日志/Token/证据/产出物/议题/模型调度/介入/控制 | —（只剩消息流+时间线+思维树） |
| 创建流程 | 弹窗一步到位：主题+模型+附件+flow_plan | —（只有 textarea） |
| 上传 | 真实 FormData 上传（`lib/api.ts:230-238`） | —（file.text() 假上传） |
| 会议控制 | 顶栏 pause/resume/stop/delete 全套 | —（只剩 stop） |
| 设计系统 | tokens.css 语义 token 体系 | 同样 token 化（bg-bg-primary 等），可平移 |
| 视觉精致度 | 朴素 | 更现代精致（Radix 交互质量） |

**结论：不是技术栈之争。新版的问题不是 Tailwind/Radix，而是重写时丢了功能资产。方向 = 新架子 + 旧密度。**

## 2. 设计原则（六条）

1. **可观测性第一**：用户在会议中任何时候都能一键看到"系统在干什么"（日志/Token/证据/产出/调度），不需要跳页。
2. **密度回归**：正文 14px、行高 1.5、日志等宽 12px/20px 行高；卡片只用于真正的卡片场景（报告库列表），工作台场景用面板分割而非卡片堆叠。
3. **单屏会议**：会议进行中的所有信息在一个屏幕内可达（主区 + 可折叠面板），禁止把会议状态拆到多个路由。
4. **路径最短**：从"打开系统"到"会议开始跑"≤ 2 次点击、1 个弹窗。
5. **零 Mock**：全链路遵循 mock-data-redline.md，所有数据必须来自真实接口或如实三态。
6. **命名一致**：恢复"会议（meeting）"语义，废弃"探索（explore）"命名。

## 3. 信息架构（路由收敛 15 → 8）

| 路由 | 内容 | 处置 |
|---|---|---|
| `/board` | 会议看板：创建弹窗入口 + 会议列表（合并现 board/explore 两个列表） | 保留并强化 |
| `/meeting/:id` | **单屏会议视图**（现 `/explore/:id` 改造） | 核心改造 |
| `/reports` | 报告库 | 保留，补证据链渲染 |
| `/knowledge` | **知识空间**（新增，配合知识资产化改造） | 新增 |
| `/workspace` | 文件工作区 | 保留 |
| `/agents` `/teams` | 角色/团队管理 | 保留（拆分子组件） |
| `/settings` | 设置（折叠 models/admin/operations 为 Tab） | 收敛 |
| `/login` `/setup` | 认证 | 保留 |
| 删除 | `/explore`、`/explore/:id`、`/landing`（孤儿）、`/graph` 独立路由（并入会议内面板）、`/admin`、`/operations`（并入 settings Tab）、`/models`（并入 settings） | 删除 |

## 4. 单屏会议视图布局（核心）

```
┌────────────────────────────────────────────────────────────┐
│ 顶栏：面包屑 │ StageIndicator(六阶段) │ flow_plan/深度标签  │
│      │ 面板开关×8 │ pause/resume/stop/delete 全套控制        │
├────────────────────────────────────────────────────────────┤
│ ┌─ AgentGraph（可折叠拓扑，真实 /graph/overview 数据）─────┐ │
│ └────────────────────────────────────────────────────────┘ │
│ ┌─ MessageStream（消息流，含 WS 断线 REST 兜底）──────────┐ │
│ │                                                          │ │
│ └────────────────────────────────────────────────────────┘ │
│ 输入区：发送 + 真实附件上传（FormData + 进度）               │
├────────────────────────────────────────── 右侧 Drawer ─────┤
│ 8 个互斥 Drawer（mask=false 不遮挡消息区，宽 440-600px）：    │
│ ①议题聚焦 ②证据 ③产出物 ④报告 ⑤Token/成本                  │
│ ⑥模型调度 ⑦介入审批 ⑧实时日志（级别过滤/暂停/下载）          │
└────────────────────────────────────────────────────────────┘
```

数据来源全部真实：证据面板 = `state.evidence_set`（WS 事件 `evidence.attached`）；Token = CostTracker API；日志 = WS 日志流；调度 = 模型快照/调度 API；介入 = `pending_borrow_request` 事件。

## 5. 创建弹窗（一步到位）

字段：议题（textarea + 润色）│ 产出物类型（deliverable_type 下拉，8 种）│ 团队/角色选择（接 `/teams`、`/agents` 真实数据）│ 模型选择 │ flow_plan（simple/standard/full）│ 深度 │ **附件上传（拖拽 + 白名单 + 进度）**。
mutation 参数 `agents`/`deliverable_type` 后端已支持（`use-meetings.ts:189`），纯前端接线。

## 6. 组件迁移映射表

| 旧版组件 | 去向 | 数据源 |
|---|---|---|
| `LogPanel.tsx`（283 行） | 新 `drawers/LogDrawer`，移植级别过滤/暂停/下载 | WS 日志流 |
| `TokenPanel` | `drawers/TokenDrawer` | CostTracker API |
| `EvidencePanel` | `drawers/EvidenceDrawer` | evidence_set 事件 |
| `ArtifactPanel` | `drawers/ArtifactDrawer` | artifact + `/attachments` |
| `TopicPanel` | `drawers/TopicDrawer` | clarified_topic/key_questions |
| `ModelSelector` | `drawers/ModelsDrawer` | 模型中心 API |
| `MeetingControls` | 会议顶栏控制组 | `/meetings/{id}/control` |
| `AgentGraph` | 会议内可折叠图（替代独立 /graph 路由） | `/graph/overview?meeting_id=` |
| `CreateMeeting` 弹窗 | 新 `CreateMeetingDialog`（Radix Dialog） | `/meetings` POST |
| `uploadDocument()` | `lib/api.ts` 恢复 FormData 上传 | `/meetings/{id}/documents` |
| 旧 `components.css` 密度 token | 并入 Tailwind theme（14px/1.5 等） | — |

## 7. 四项超越性优化（新旧都没有的）

1. **消息可靠性**：启用 `useMeetingMessages` 做 WS 断线 REST 兜底 + 发送失败 toast + 本地重发队列。
2. **证据链渲染**：`report-layout` spec 的 `findings.sources/trace`、`conflicts.trace` 块前端补渲染（后端已产出，前端只实现了 8 种块）——报告里每个结论可点开看证据来源。
3. **知识空间页**（`/knowledge`）：文档列表/上传/检索测试/空间管理，配合知识资产化改造（见 ADR 文档）。
4. **运行中会议实时性**：board 列表对 running 状态会议加 30s 轮询或 WS 订阅；页面级 ErrorBoundary（现状全站仅 1 处）。

## 8. 观感修复清单（顺带）

- `takeover-panel.tsx:115` 硬编码深色 `bg-[#1a1a2e]` → 改 token。
- 核心页（会议视图、reports）补 `md:` 断点；侧栏折叠用 Tailwind 断点替代 JS resize 监听（`explore/page.tsx:47-69`）。
- 消灭 `messageCount ?? message_count` 双重字段兜底：normalize 单点处理。
- `svg-icons.tsx`（1161 行手写图标）→ lucide-react。

## 9. 分期实施

| 波次 | 内容 | 验收 |
|---|---|---|
| Wave 1（清场+主闭环） | mock 全清除（MR-8）；路由收敛；创建弹窗；真实上传；消息兜底/重发 | 真实会议从创建到完成全流程可用；`grep mock` 生产源码零命中 |
| Wave 2（可观测性移植） | 单屏会议视图 + 8 Drawer + 控制全套 + 会议内 AgentGraph | 会议中不跳页可查看日志/Token/证据/产出 |
| Wave 3（超越项） | 证据链渲染、/knowledge 页、board 实时刷新、ErrorBoundary | 报告结论可溯源到证据；文档可管理可检索 |
| Wave 4（观感与卫生） | 密度 token、响应式、图标库、双重字段清理 | 旧版用户体感回归；lucide 替换完成 |

## 10. 明确不做的

- 不回滚到旧版技术栈（AntD/reducer/巨型 CSS）。
- 不追求移动端完整适配（桌面工具优先，仅保证核心页不崩）。
- 不在 Wave 1-2 引入任何新功能（只做恢复与接线）。
