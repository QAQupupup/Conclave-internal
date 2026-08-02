# 前端设计评估报告交叉质证（GLM-5.2 UI 能力/状态管理/a11y/键盘交互/响应式视角）

> 质证对象：docs/frontend-design-audit/frontend-design-audit.html
> 质证时间：2026-08-01
> 质证立场：UI 组件能力 / a11y / 状态管理 / 响应式 / 错误处理
> 质证范围：只读不写，所有事实性主张均 grep 核验

## 0. 核验前提（继承 F1-F14 + 本视角新发现）

| 编号 | 事实 | grep/读来源 |
|------|------|------------|
| F1 | 实际栈不含 antd，依赖 16 个 `@radix-ui/*` + shadcn 风格自建封装 | `package.json` 第 16-30 行（无 `antd`） |
| F2 | Tooltip 自建 `<div>` 而非 `@radix-ui/react-tooltip` | `frontend/src/components/ui/tooltip.tsx:11-40` 全文无 `react-tooltip` 引用 |
| F3 | Dialog / DropdownMenu / Tabs / Toast / Select / Switch / Slot / ScrollArea / Progress / Avatar / Collapsible / Popover / Label / Separator 全部走 Radix 包装 | `grep -E '@radix-ui/(react-dialog|react-dropdown-menu|react-tabs|react-toast|...)' src/components/ui/*.tsx` 多文件命中 |
| F4 | `cmdk` 已装，Command Palette 基于 cmdk 包装在 Dialog 内 | `frontend/src/components/layout/command-palette.tsx:3-4`（`import { Command as CommandPrimitive } from 'cmdk'`） |
| F5 | `frontend/src/stores/` 共 4 个 slice：auth / meeting / ui / ws，UI 用 persist 中间件持久化 layout 偏好 | `frontend/src/stores/index.ts:1-4` 导出 + `ui-slice.ts:28` `create<UIState>()(persist(...))` |
| F6 | 路由用 `React.lazy` + `<Suspense>` + 顶层 `ErrorBoundary` 兜底 | `App.tsx:6, 23-32, 36-67` |
| F7 | Cmd/Ctrl+K 全局快捷键在 `top-bar.tsx:121-130` 内联实现，**未抽 hook**，且只在 mount 时挂一次 | `grep -E 'use-keyboard-shortcut|useHotkeys|useKey|useShortcut' src` → No matches found |
| F8 | `prefers-reduced-motion` 已在 `app.css:205-213` 全局尊重 | grep 命中 1 处 |
| F9 | **项目存在 2 处 `window.confirm` 阻塞式确认**（`board/page.tsx:63`、`admin/page.tsx:336`），未替换为 a11y 友好的 Dialog | `grep -E 'confirm\(' src` 命中 2 处 |
| F10 | 全项目 aria 属性仅 6 处（`aria-orientation`、`aria-checked`×1、若干 `role=`），**0 个 `aria-label`、0 个 `aria-describedby`、0 个 `aria-live`** | `grep -E 'aria-' src` 命中 6 行，无 label/describedby/live |
| F11 | `text-tertiary`（#6b7280 / #666）作为正文颜色，**与 `bg-primary` / `bg-secondary` 对比度未经验证** | `app.css:13-14` + `:137-139` |
| F12 | Tooltip `aria-describedby` 缺失，仅靠 `role="tooltip"` 不形成 trigger-content 关联，屏幕阅读器无法朗读 | `tooltip.tsx:14-39` 全文 |
| F13 | **2 处 `window.confirm` 不在 Dialog 体系内**，无法被 Esc 取消、不聚焦对话框，破坏键盘流 | 同 F9 |
| F14 | `use-toast`（`/hooks/use-toast`）和 `use-toast` 返回 `{toast}` 命名解构并存，前者 `useToast` 后者 `toast` 函数 | `top-bar.tsx:39, 67` 与 `command-palette.tsx:25` 调用差异 |

## 1. UI 能力视角核验表（6 个核心问题）

### 1.1 Tooltip 自建 vs Radix 对比（F2 / F12）

**grep/读证据**：
- `Read frontend/src/components/ui/tooltip.tsx` 全文 42 行，**0 处**引用 `@radix-ui/react-tooltip`
- `grep -E '@radix-ui/react-tooltip' src` → No matches found
- `package.json:30` 声明依赖，但**生产代码 0 引用**（依赖装而不用 = 死依赖 + bundle 体积税）
- 自建实现 `setShow` 受 `onMouseEnter/Leave` + `onFocus/Blur` 驱动，**缺少键盘 Esc 关闭、缺少 hover 延迟（immediate show/hide，触发闪烁）**，也未对齐 Radix 的 `delayDuration` / `skipDelayDuration`
- `aria-describedby` 完全缺失，**触发的 `children` 没有任何 `aria` 属性将自身与 tooltip 关联**，屏幕阅读器对盲用户来说 tooltip 内容是孤儿

**评估**：报告原文把 Tooltip 列在方向 D 的 P1 替换表（`antd/Tooltip`）。本视角**认可 P1** 替换方向，但更精确地说**应该用 `@radix-ui/react-tooltip`**（已装），而不是 antd 的（antd 未引入），否则属于"解决 A 引入 B"的方向错位。**额外硬伤**是当前实现有 a11y 阻断（无 `aria-describedby` 关联），F12 列入 P0。

### 1.2 Dialog 焦点管理与 a11y

**grep/读证据**：
- `dialog.tsx:1-110`：基于 `@radix-ui/react-dialog`，**自动获得焦点陷阱、Esc 关闭、初始焦点、焦点返回、aria-modal、aria-labelledby/describedby 关联**（来自 Radix 实现）
- 仅自定义了视觉（`fixed left-[50%] top-[50%] z-[var(--z-modal)] grid ...`）和 Close 按钮的 `sr-only` "Close"（`dialog.tsx:54`）
- `command-palette.tsx:63-64`：将 Dialog 用作命令面板容器，复用 Radix 的 a11y 行为
- `onOpenChange={(v) => !v && close()}`（`command-palette.tsx:63`）允许外部通过受控方式关闭

**评估**：Dialog 自身**无 a11y 问题**，是项目里 a11y 实现最干净的组件（**全靠 Radix**）。原报告把 dialog 阴影/圆角/动画偏离设计规范归为 P0，**本视角不重复该视觉结论**，但补充：**Dialog 应当成为 `window.confirm` 替换目标**（见 1.6 与硬伤 §3）。

### 1.3 Dropdown 键盘导航

**grep/读证据**：
- `dropdown-menu.tsx:1-172`：**全程 Radix 包装**，键盘导航（↑↓ Home End / Esc / 字符跳转 / type-ahead / SubMenu 自动展开）由 Radix 内置实现
- `SubTrigger` / `SubContent` / `CheckboxItem` / `RadioItem` / `Label` / `Separator` / `Shortcut` 全部对接 `DropdownMenuPrimitive.*`
- **唯一 a11y 缺陷**：`DropdownMenuShortcut`（`dropdown-menu.tsx:151-154`）是纯视觉 `<span>`，没有 `aria-keyshortcuts` 关联触发器；项目多处用它显示快捷键提示（如 command-palette `kbd`），**但屏幕阅读器读不出快捷键**

**评估**：键盘导航完整且无需手写；**短板在 `DropdownMenuShortcut` 缺 aria 关联**，建议追加 `aria-keyshortcuts` 或在 Trigger 上加 `aria-keyshortcuts="Mod+k"` 之类。优先级 P2（不阻断功能，但降低 a11y 完整性）。

### 1.4 Command Palette 键盘交互

**grep/读证据**：
- `command-palette.tsx:62-150`：基于 `cmdk` + Radix Dialog + cmdk `<Command>` `loop` 属性（`command-palette.tsx:71` `loop`）实现 ⌘K
- 触发器：`<Dialog open={open} onOpenChange={...}>`（63-64 行）→ 受 `useUIStore` 中 `commandPaletteOpen` 控制
- `cmdk` 自带模糊搜索、`↑↓` 选择、`↵` 执行、类型跳转；底部有 `kbd` 提示（`command-palette.tsx:139-145`）
- **Input `autoFocus` 已设**（`command-palette.tsx:78`）→ Dialog 打开时自动聚焦搜索框
- **Esc 关闭**：由 Radix Dialog 默认行为提供（未显式 `onEscapeKeyDown`）
- `CommandItem`（`command-palette.tsx:153-178`）自定义包装层，**data-[selected=true]:bg-bg-tertiary** 视觉态但**缺少 `aria-selected={selected}` 显式属性**（cmdk 内部可能自动加，外部 `<CommandPrimitive.Item>` 上是受控选中态，组件未补 aria）

**评估**：实现质量**在 6 个核心 UI 组件中得分最高**：键盘交互齐全、可发现性（底部 kbd 提示）、模糊搜索、Admin 角色门控（`isAdmin` 显隐 `/admin`）。**唯一可改进**：① `handleNewMeeting`（`command-palette.tsx:51-60`）`catch (e: any)` 走 `e.message` 兜底但**没有任何 a11y 提示**（toast 是视觉的，无 `aria-live` 朗读），② Esc 后 `setQuery('')` 时机依赖 `useEffect`（`command-palette.tsx:47-49`）——关闭时已 `runCommand` 内 setQuery，但 effect 二次清空有冗余，无 bug。综合：**A-** 级别。

### 1.5 Zustand store 划分与持久化

**grep/读证据**：
- `frontend/src/stores/index.ts:1-4` 导出 4 个 store：`useAuthStore / useUIStore / useWSStore / useMeetingStore`
- `useAuthStore`（`auth-slice.ts:15-89`）：`persist` + `partialize: ({token}) => {token}` —— **只持久化 token**，user/isAuthenticated/isLoading 每次 rehydrate 后通过 `onRehydrateStorage` 调 `fetchUser()` 重新拉取
- `useUIStore`（`ui-slice.ts:28-73`）：`persist` + `partialize` 持久化 5 个 layout 字段（`theme/timelineWidth/thoughtTreeWidth/timelineCollapsed/thoughtTreeCollapsed`），**`commandPaletteOpen` 不持久**（正确，避免重启后弹命令面板）
- `useMeetingStore`（`meeting-slice.ts:54-193`）：**无 persist** —— 会议运行态不应跨刷新存在，重连后由后端 push 重放
- `useWSStore`（`ws-slice.ts:16-25`）：**无 persist** —— 连接态也属"会话级"

**评估**：
- **划分合理**：4 个 store 按"业务域"切分（auth/ui/meeting/ws），与 ui-slice.ts:6-20 的 `UIState` 接口设计自洽
- **持久化策略正确**：只持久化"用户偏好"和"token"，不持久化"运行态"
- **唯一可改进点**：`useAuthStore` 的 `partialize` 只持久 `token`，但 **没有 `version` 字段**（`ui-slice.ts:46-80` 同样没有 `version`）。一旦后端 token 格式变更或加新字段，**老用户会被持久化旧 token 卡死**直到手动 `localStorage.clear()`。建议追加 `version: 1` + `migrate` 回调。`ui-slice.ts:46-80` 的 LEGACY_THEME_KEY 迁移（`ui-slice.ts:54-71`）是手动方案，可读性 OK 但缺版本号升级路径
- **`hasError` 状态不持久**（auth-slice.ts + meeting-slice.ts 内部错误处理）—— 正确
- **类型安全**：`useAuthStore` `extends AuthState`（`auth-slice.ts:6`）但 `AuthState` 类型未在 stores 文件内定义而是 `@/types`（已 grep 验证 import 存在），跨文件耦合可接受

**结论**：store 划分**A**，持久化策略**B+**（缺 version 字段为 P2 隐患）。

### 1.6 响应式断点适配

**grep/读证据**：
- `grep -E 'md:hidden|md:flex|md:block|sm:flex|sm:hidden|sm:block|md:w-|md:p-|md:grid|sm:grid|lg:grid'` → 命中 9 行，**全部集中在 features 页面（operations/board/agents/admin）和 dialog/toast 组件**
- 业务页（board/explore/workspace/graph）**没有专属移动端断点**：
  - `frontend/src/features/board/page.tsx`：`mx-auto max-w-5xl p-6`（`board/page.tsx:74`）—— 固定 1024px max，**小屏不收缩到 1 列**
  - `frontend/src/features/explore/page.tsx:78-156`：`flex h-full w-full` 三栏（timeline | stream | thoughtTree）—— **窄屏（<1024px）三栏挤压中央 MessageStream 至几乎不可读**
  - 没有 `lg:hidden` / `md:flex-col` 等切换
- `package.json` **未引入 `react-responsive` / `tailwindcss-rp`**，全部走 Tailwind 默认断点
- `@media (max-width: 768px)` 在源码 0 命中（`grep -E 'max-width:\s*768px'` → No matches found）

**评估**：
- 项目**事实上没有"平板/移动端"适配**——Explore 三栏在 1024px 以下必然挤压
- 报告原文未提此点，**本视角独立识别 P1**：Explore / Board / Workspace 在 `< 1024px` 下不可用
- 与 F13（cmd+k 触发器在 `top-bar.tsx:202-213` `w-72` 固定 288px）叠加：移动端搜索框会**挤出 brand 和头像**
- 但报告里"侧边栏默认折叠"是面向桌面端优化的论点，**与本视角的"窄屏未适配"不冲突**——可作为补充

## 2. UI 能力专项主题

### 2.1 a11y 评估（aria 属性覆盖率、键盘可达性、对比度）

**grep/读证据**：
- `grep -E 'aria-` src` 命中 6 行（4 个 `aria-` 属性 + 2 个 `aria-orientation`/`aria-checked` 散落）+ 8 处 `role=` 散落（业务页用 `role={agentRole}` 当语义标记，**这与 `aria-role` 同名但语义不同，** 实际等于给 div 加了 HTML role 但无对应 ARIA 角色规范，存在 ARIA misuse 风险）
- **`aria-label: 0 命中`**、`aria-describedby: 0`、`aria-live: 0`、`aria-modal: 0`（Radix Dialog 内部用了，但 grep src 不到用户代码）
- `sr-only` 仅 1 处（`dialog.tsx:54` "Close"）
- **skip-link: 0 命中** —— 键盘用户进入首页后**必须 Tab 完整页才能到主要内容**，无 skip-to-content 链接

**键盘可达性细分**：
- ✅ 全局 ⌘K（`top-bar.tsx:121-130`）
- ✅ Enter 发送（`message-stream.tsx:103-108`）
- ✅ Enter 提交（`workspace/page.tsx:578-579`、`agents/page.tsx:891`）
- ❌ **关闭确认：2 处 `window.confirm`**（`board/page.tsx:63`、`admin/page.tsx:336`）—— 不可被键盘/屏幕阅读器友好处理
- ❌ **无 help dialog** 列出所有快捷键，**唯一可发现性来自 top-bar 中央的搜索框 `kbd` 提示**（top-bar.tsx:209-211），但 pause/skip/stop 等会议内快捷键（`top-bar.tsx:163-191`）**完全无键盘提示**
- ❌ Tooltip `aria-describedby` 缺失（F12）
- ❌ `top-bar.tsx:121-130` Cmd+K handler **没在 unmount 时清理 onBlur/focus 焦点**——若在 input 元素 focus 时按 Cmd+K，会**先被浏览器 default 行为抢**（某些浏览器在 input 中 Ctrl+K 触发搜索栏）

**对比度**：
- 主文本 `text-primary`（`app.css` 内 `--color-text-primary: #111827` 亮色 / `#e8e6e0` 暗色）→ 对 `bg-primary`（#ffffff / #0a0a0b）对比度 **≥ 15:1**，通过 WCAG AAA
- `text-tertiary`（`#6b7280` 亮色 / `#666` 暗色）→ 在 `bg-primary`（#ffffff）上 **#6b7280 vs #ffffff 对比度 4.83:1**（**WCAG AA 通过，AAA 失败**），在暗色 `#666` vs `#0a0a0b` 大约 **4.5:1**（**AA 临界**）
- 报告原文未评估对比度，**本视角独立 P2**：所有 `text-tertiary` 用作正文/标签场景需做对比度提升

### 2.2 状态管理评估（store 划分、persist、类型安全）

见 §1.5，结论 store 划分 A、persist B+。补充：
- `useMeetingStore.appendMessageDelta`（`meeting-slice.ts:87-109`）流式 delta 合并逻辑有 `findIndex` 找不到时**自动新建占位消息**——但**没有去重**：相同 `messageId` 短时间内多次 append 不会重复（findIndex 命中后走 else 分支更新），**正确**
- `useAuthStore.fetchUser`（`auth-slice.ts:25-58`）的 `Promise.race` + 10s 超时（`auth-slice.ts:32-37`）—— 健壮
- 缺失 **`useShallow` / `shallow` 比较器**（zustand v5 默认严格相等），在 useMeetingStore 全量订阅（`top-bar.tsx:116` `const meeting = useMeetingStore();`）下，**任何字段变化都会重渲 top-bar**——这是性能/UI 一致性的小问题（P2 性能）
- 缺失**derived selectors** 封装（如 `useMeetingActions()` 把 10 个 setter 合并），业务页如 `top-bar.tsx` 用 `useMeetingStore()` 一次性订阅全量（`top-bar.tsx:116`），**重渲成本高**（P2 性能）

### 2.3 错误处理（Error Boundary、空状态、loading 态）

**grep/读证据**：
- `ErrorBoundary`（`frontend/src/components/error-boundary.tsx`）：class 组件，捕获后显示"页面发生错误"+ DEV 模式 `error.message` + "刷新页面" / "返回首页" 两个按钮
- **唯一一处 ErrorBoundary**（`App.tsx:6, 37` 包裹整个 `<BrowserRouter>`）—— **粗粒度兜底**，子组件错误会冒泡到顶层 → **整页白屏替换**为错误页（不是局部降级）
- **子组件无独立 ErrorBoundary** —— 如果 board 列表渲染崩了，**整个 App 跳到错误页**，原本可用的左侧 nav 也没了（用户体验断层）
- 加载态：`isLoading` 在 board/explore/reports/workspace 等多处正确使用（`board/page.tsx:141-143`、`explore/page.tsx:58-66`、`reports/page.tsx:622-625` 用 Skeleton）
- 空状态：**实现充分**，19 处 `length === 0` 都有自定义空态（`agents/page.tsx:554` EmptyState、`board/page.tsx:146-148`、`reports/page.tsx:301-325` EmptyState 等）
- **try/catch 中吞异常**：5 处 `catch` 静默（`auth-slice.ts:53`、`api.ts:301` 等），需 `console.error` 补齐

**评估**：
- 顶层 ErrorBoundary = A（必要）
- 子组件 ErrorBoundary = **缺失，P1**：报告未识别，**本视角独立硬伤**
- 空状态 = A（充分）
- 加载态 = A（Skeleton + spinner 都有）
- 异常静默吞 = P2（5 处 `catch` 无 `console.error`）

## 3. 报告硬伤清单（仅本视角独立识别的新硬伤）

| 编号 | 硬伤 | 等级 | grep/读证据 |
|------|------|------|------------|
| B-1 | **Tooltip 完全无 `aria-describedby` 关联**（自建 div + 缺 ARIA） | P0 | `tooltip.tsx:14-39` 全文无 `aria-describedby`，无 `id` 给 trigger 引用 |
| B-2 | **2 处 `window.confirm` 阻塞式确认**（board 删除会议、admin 删除用户） | P0 | `board/page.tsx:63` + `admin/page.tsx:336` |
| B-3 | **Explore 三栏在窄屏（<1024px）无响应式适配**，中央内容被挤压至不可读 | P1 | `explore/page.tsx:78-156` 全文无 `md:` / `lg:` 切换；`grep -E 'max-width:\s*768px' src` → 0 命中 |
| B-4 | **业务页（board/workspace/reports）无移动端断点适配**，固定 `max-w-5xl` 在 320px 设备溢出 | P1 | `board/page.tsx:74` `max-w-5xl p-6`，无 `sm:` 切换 |
| B-5 | **顶层 ErrorBoundary 粒度过粗**（单一 wrapper 包裹整个 BrowserRouter），子组件崩溃会替换整页 | P1 | `App.tsx:37` 唯一 ErrorBoundary |
| B-6 | **`@radix-ui/react-tooltip` 依赖已装但全项目 0 引用**（死依赖，bundle 税 + 误导性技术债） | P1 | `package.json:30` + `grep -E '@radix-ui/react-tooltip' src` → 0 命中 |
| B-7 | **Zustand store 缺 `version` 字段**，未来 token 格式或 UI 状态 schema 升级会卡老用户 | P2 | `ui-slice.ts:46-80` 与 `auth-slice.ts:76-88` 持久化配置均无 `version` |
| B-8 | **`useMeetingStore` 全量订阅**（`top-bar.tsx:116` `const meeting = useMeetingStore();`），任何字段变化都重渲 top-bar | P2 | `top-bar.tsx:116`；与 §1.5 的 store 划分结论关联 |
| B-9 | **`text-tertiary`（#6b7280 / #666）作正文/标签**在 `bg-primary` 上对比度 4.5~4.83:1，WCAG AA 临界 | P2 | `app.css:13-14, 137-139`；未在任何 UI 测试中验证 |
| B-10 | **5 处 `catch` 静默吞异常**（无 `console.error`），错误排查无迹可循 | P2 | `auth-slice.ts:53, 70` + `api.ts:301` 等 |
| B-11 | **`aria-label: 0 命中`** —— 所有 icon-only 按钮（搜索、删除、关闭、暂停、跳过、停止、设置、用户菜单）**无 accessible name** | P1 | `grep -E 'aria-label' src` → 0 命中；`board/page.tsx:231-237` 删除按钮仅 `title="删除"` |
| B-12 | **skip-link 缺失** —— 键盘用户从顶部 Tab 到主内容需遍历整个 nav | P2 | `grep -E 'skip-link|SkipLink|skip to main' src` → 0 命中 |

## 4. 重分级建议（仅本视角的 P0/P1/P2 重判）

| 原报告判断 | 本视角重判 | 理由 |
|-----------|-----------|------|
| 方向 D 表格中 Tooltip 标 **P1 替换为 antd/Tooltip** | **方向错误** —— 应该替换为 `@radix-ui/react-tooltip`（已装），引入 antd 违背 F1 | grep 验证依赖已装但未用 |
| 方向 D 表格中 Dialog 标 **P0 替换为 antd/Modal** | **不认可** —— 当前 Dialog 基于 Radix，a11y 满分（焦点陷阱、Esc、初始焦点、aria-modal 全内置） | `dialog.tsx` 全文 110 行只有视觉层覆盖 |
| 报告未提 a11y 整体 | **新增 P0**：B-1（Tooltip 缺 aria-describedby）、B-2（window.confirm 阻塞）、B-11（icon-only 按钮无 aria-label） | grep 全量核验 |
| 报告未提响应式 | **新增 P1**：B-3（Explore 窄屏挤压）、B-4（业务页无断点） | `explore/page.tsx` 全文 156 行无 `md:` / `lg:` |
| 报告未提 ErrorBoundary 粒度 | **新增 P1**：B-5（顶层单点） | `App.tsx:37` 唯一 |
| 报告 §6.1 把 Dialog 列为 P0 替换 | **降为 P3（暂不替换）** | 当前实现是项目最干净组件 |
| §7.1 侧边栏默认折叠（建议改 `timelineCollapsed/thoughtTreeCollapsed` 默认值为 true） | **认可 P0**（来自 F10 + 项目本视角核验） | `ui-slice.ts:34-35` 已 grep 确认默认值 |
| §7.4 路由切换过渡（P2 fade-in） | **降为 P3** —— 项目已尊重 `prefers-reduced-motion`（`app.css:205-213`），且 `React.lazy + Suspense` 已有 LoadingFallback，肉眼感知差异小 | 优先级排序靠后 |

## 5. GLM-5.2 视角独立结论

### 5.1 核心判断

报告在 UI 组件能力 / 状态管理 / a11y / 响应式 / 错误处理 5 个维度的覆盖**严重不均**：
- ✅ **a11y 框架层**（Dialog / Dropdown / Tabs）做得好（靠 Radix）
- ❌ **a11y 应用层**（自建 Tooltip、icon-only 按钮、确认弹窗）**几近为零**
- ❌ **响应式**完全缺失覆盖，Explore 三栏在 1024px 以下必然挤压
- ❌ **错误处理粒度**过粗，单一顶层 ErrorBoundary
- ❌ **a11y 属性覆盖率**全项目仅 6 处，**0 个 aria-label**
- ✅ **状态管理** 4 个 slice 划分合理、持久化策略正确
- ✅ **空状态 / loading 态** 覆盖充分

报告把 Dialog / Dropdown 列为 P0 替换为 antd 是**方向错位**（应当用 Radix）；Tooltip 替换为 antd 同样错位（应当用 Radix 自家 `@radix-ui/react-tooltip`）。报告对 a11y / 响应式 / 错误粒度的覆盖**严重不足**，本视角补 12 条独立硬伤。

### 5.2 应采纳项（最多 5 条）

1. **§7.1 侧边栏默认折叠**（P0）—— `timelineCollapsed/thoughtTreeCollapsed` 默认改 `true`，本视角 grep 确认 `ui-slice.ts:34-35` 当前确实 `false`
2. **§6.1 Tooltip 替换方向** —— 但**改为替换为 `@radix-ui/react-tooltip`（已装）**，移除自建 `tooltip.tsx`，同时补 `aria-describedby` 关联
3. **§3 报告原文 §3 各条阴影/Padding 收敛** —— 与本视角独立，但本视角不重复评
4. **§9.1 P0 清单中 "评估 AntD Modal / Dropdown 替换自定义弹窗/菜单的可行性"** —— 应改为"评估 Radix Tooltip 替换可行性" + **取消 Dialog 替换**（已合格）
5. **本视角新增 P0**：`window.confirm` 替换为 Radix Dialog 确认弹窗（2 处：board 删除、admin 删除用户）

### 5.3 应拒绝项（最多 5 条）

1. **§6.1 把 Dialog 标 P0 替换为 antd/Modal** —— 现状已合格，替换是倒退
2. **§6.1 把 DropdownMenu 标 P0 替换为 antd/Dropdown** —— 现状键盘导航、ARIA 全靠 Radix，替换是倒退
3. **§9.1 P0 "评估 AntD Modal / Dropdown / Tooltip 替换"** —— 方向错，引入 antd 违背 F1
4. **§7.4 路由切换过渡 fade-in 标 P2** —— 应降至 P3，prefers-reduced-motion 已处理，肉眼差异小
5. **§6.1 tooltip 用 `antd/Tooltip` 替换** —— 方向错（见 §5.2 第 2 条）

### 5.4 整体评分（UI 能力判断准确性 / a11y 深度 / 实施可行性）每项 X/10

| 维度 | 评分 | 说明 |
|------|------|------|
| **UI 能力判断准确性** | 6/10 | 方向 D 替换建议对了一半（Tooltip 该换但换错目标；Dialog/Dropdown 不该换）；忽略了"Radix 已自带 a11y"的核心价值 |
| **a11y 深度** | 3/10 | 报告**完全未评估 aria 属性覆盖率**、**未评估 icon-only 按钮无 aria-label**、**未评估 window.confirm 阻断键盘流**、**未评估 skip-link 缺失**、**未评估对比度**——a11y 维度实质性缺失 |
| **实施可行性** | 7/10 | 方向 A/B/C 的视觉/布局建议落地成本低（改 padding、改默认值）；方向 D 替换 antd 不建议，**方向 E 浮窗徽章需新组件**（P0 必要但成本中等） |
| **整体（综合）** | 5.5/10 | 视觉/美学维度可信（其他视角评），UI 能力/a11y 维度实质性欠缺，建议补 12 条独立硬伤后采纳 |

### 5.5 一句话总结

> 报告在视觉与布局维度上对，但把"Radix 自建 = 该换"误读为"该换 antd"，且**完全漏掉 a11y 应用层（aria-label/aria-describedby/window.confirm/skip-link/对比度）和响应式断点 2 个独立 P1 板块**——本视角补 12 条硬伤、3 个反建议、2 个 P0 重判，整体 UI 能力判断准确性 6/10。
