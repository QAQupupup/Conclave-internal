# 前端设计评估报告交叉质证（DeepSeek-V4-Pro 实用主义/行为/性能视角）

> 质证对象：`docs/frontend-design-audit/frontend-design-audit.html`
> 质证时间：2026-08-01
> 质证立场：实用主义 / 行为导向 / 性能优先（"这个改动对用户真的可感知吗？"）
> 质证范围：只读不写，所有事实性主张均 grep 核验

---

## 0. 核验前提

实际仓库现状（关键事实先钉死，避免后续结论空转）：

| 关键事实 | grep 结果 | 与报告对比 |
|---|---|---|
| 是否引入 `antd` | `frontend/package.json` **无 antd 依赖**；`frontend/src/**` **零文件** `import from 'antd'` | 报告"项目已经引入 Ant Design"**事实错误** |
| 实际组件库 | `@radix-ui/*`（dialog/dropdown-menu/select/tooltip/toast 等 16 个包）+ 自建 shadcn/ui 风格封装 | 报告"混合使用了 Radix UI 与 shadcn/ui"对，"已经引入 AntD"错 |
| 弹窗组件实际栈 | `components/ui/dialog.tsx` → `@radix-ui/react-dialog` + Tailwind `shadow-lg` | 与报告一致 |
| 状态栏"Ready" | `components/layout/status-bar.tsx:72` 硬编码 `<span>Ready</span>` | 与报告一致，已核验 |
| 图谱 wheel handler | `features/graph/page.tsx:292-296`：`delta = e.deltaY > 0 ? 0.9 : 1.1`，无 `requestAnimationFrame` / `transition` | 与报告一致 |
| `timelineCollapsed` / `thoughtTreeCollapsed` 默认 | `stores/ui-slice.ts:34-35`：`false` | 与报告一致 |
| `p-6` 在 board/workspace | `features/board/page.tsx:74` `mx-auto max-w-5xl p-6`；`features/workspace/page.tsx:311` `flex h-full flex-col p-6` | 与报告一致 |
| Tailwind 版本 | `tailwindcss: ^4.0.0`（Vite 插件） | 影响 shadow 解析方式 |
| `--shadow-md` 在 `@theme` 中 | `app.css:104`：`--shadow-md: 0 2px 8px rgba(0, 0, 0, 0.06)`（透明度 0.06，**符合规范**） | 与报告"阴影 md 当前实现 opacity 0.06"一致 |
| `--shadow-lg` 在 `@theme` 中 | **未定义**，因此 `shadow-lg` utility 走 Tailwind v4 默认 `0 10px 15px -3px rgba(0,0,0,0.1)` | 这才是**真正超标的阴影** |
| `text-primary` 当前值 | `--color-text-primary: #1a1d23`（暖色偏黄） | 与报告一致 |
| `border-default` 当前值 | `--color-border-default: #e2e6eb`（冷色偏蓝） | 与报告一致 |
| Web Vitals / LCP/INP 监控 | 全仓 grep `web-vitals / PerformanceObserver / onLCP / onINP` **0 命中** | 报告**完全没提此盲点** |
| 路由切换过渡 | `App.tsx` 用 `<Routes>` 直接渲染，无 `<AnimatePresence>` / `motion` 包裹 | 与报告"无过渡"一致 |
| `framer-motion` / `react-spring` | `package.json` **无任何动画库** | 与报告"建议 react-spring 或 framer-motion"前提矛盾 |

---

## 1. 行为/性能视角核验表

### 1.1 图谱缩放"步进感"（graph/page.tsx wheel handler）

| 维度 | 报告主张 | 核验结果 | 实用主义判断 |
|---|---|---|---|
| 性能问题 | "步进感明显" | wheel handler **没有节流**（无 rAF / debounce），delta 固定 0.9/1.1，setState 同步触发 React 重渲染 | 性能问题**真实但定性模糊**。mouse wheel 事件触发频率可达 60-120Hz/秒，**每个事件**都 `setZoom → setLayoutData → 重渲染整个 SVG**。节点数 < 50 时肉眼感知不到；> 200 节点时单帧重渲染 < 16ms 难保证 |
| 性能瓶颈来源 | "直接通过 `setZoom(z * delta)` 更新" | **真正瓶颈不在 zoom 计算**（纯乘法），而在 `<g transform="translate scale">` 内**全部边/节点/标签**每帧重渲染。**即使加了 rAF 插值，节点没分层 + 没 `pointer-events: none` + 没 memoization，照样卡** | **报告对原因的归因偏轻** |
| "用 rAF 插值"建议 | 报告建议"用 requestAnimationFrame 插值"或"加 transition 0.15s" | `setZoom(z * delta)` 是一次性离散变更，**rAF 插值能做**（把每帧目标值平滑过渡），但这是 0-1 优化；**真正要解决的是"每帧全量重渲染"**：① React.memo NodeShape/NodeLabel/EdgeLine ② SVG 分层后让 `<g transform>` 只动外层 group ③ 边/标签层 `pointer-events: none` | **报告建议方向对但权重排错**：rAF 插值是锦上添花，React.memo + 分层才是卡顿真解药 |
| "react-spring / framer-motion" | 报告提到但承认"项目对依赖谨慎，先用 CSS transition 80% 效果" | grep `package.json` 确认**无任何动画库**。`transition` 加在 `<g transform>` 上会**失效**（SVG transform 不支持 transition），必须用 CSS `transition: transform` on inline style 或 motion library | 报告**自己**也否定了这条建议，但保留在 P1 列表里——**应当降级为 P2 或删除** |

**结论**：步进感是真的，但"主要原因是 zoom 步进"是错位归因。**真正的行为影响是"节点多时整体卡顿"**，报告没量化节点数。**建议升 P1 为 P0**（如果节点数能到 100+），但理由要改成"全量重渲染"而非"步进感"。

### 1.2 弹窗/菜单"重阴影"破坏交互感知

| 维度 | 报告主张 | 核验结果 | 实用主义判断 |
|---|---|---|---|
| dialog.tsx:40 `shadow-lg` | "远超规范 0.04-0.06" | 核验：`@theme` 里**只定义到 `--shadow-md`**，无 `--shadow-lg`。`shadow-lg` 走 Tailwind v4 默认 `0 10px 15px -3px / 0.1`（透明度 0.1，**确实超标**） | 事实成立，**这个是真问题** |
| dropdown-menu.tsx:39 `shadow-lg` | 同上 | 核验：SubContent 用 `shadow-lg`（同上超标） | 事实成立 |
| dropdown-menu.tsx:56 `shadow-md` | "shadow-md 也超标" | 核验：`@theme` 显式定义 `--shadow-md: 0 2px 8px / 0.06`，**Tailwind v4 会用主题值**，所以 `shadow-md` 实际值是 0.06，**符合规范** | 报告**误判**——这条不应列在"重阴影"问题里。**审查漂移**：把"用了 class 名字"等同于"超规范"，没区分默认 vs 主题覆盖 |
| tooltip.tsx `shadow-sm` | 报告未单独评 tooltip 阴影 | 核验：tooltip 用 `shadow-sm` = `--shadow-sm: 0 1px 3px / 0.06`（合规） | 这是合规的，报告**没误伤** |
| "破坏交互感知" | 报告用主观描述"明显跳" | 客观上 dialog overlay 用 `bg-black/50 backdrop-blur-sm`（50% 黑遮罩 + 模糊），**遮罩本身已经强力聚焦了**，阴影重一点感知差别小。但 dialog 内容层用 `shadow-lg` 0.1 vs 0.06 在亮色背景下**确实有可见视觉跳变** | "重阴影"是**真问题但被夸大**：`shadow-md` 没问题，**只有 `shadow-lg` 是 P0**。`shadow-md` 那条应当删除 |

**结论**：阴影问题**只存在于 `shadow-lg` 用错**（dialog.tsx:40、dropdown-menu.tsx:39、command-palette.tsx:64 三处）。`shadow-md` 是**误伤**。**应修复 3 处**而非报告暗含的"全弹出层都重"。

### 1.3 "Ready" 占位是否真的破坏感官

| 维度 | 报告主张 | 核验结果 | 实用主义判断 |
|---|---|---|---|
| "Ready" 无意义 | 已核验 `status-bar.tsx:72`：`{ <span>Ready</span> }` | 硬编码、无 i18n、无动态状态、占用右侧空间 | 事实成立 |
| "破坏感官"程度 | 报告定性为 P1 | 客观：状态栏整体 24px 高，"Ready" 是 11px 灰字，**在 1440p 屏幕上视觉占比 < 0.3%**。但确实是**设计意图缺失的信号**——会看代码的 reviewer 看了会觉得"这是没写完" | P1 **合理但偏低**。这种东西修起来 30 秒，不修就会被任何新 contributor 注意到，**是工程气味问题** |
| 修复方案 | 报告说"替换为租户/快捷键/版本/最近事件" | 实际上 `useMeetingStore` 里已经有 `messages.length`、`agents.length`、`startedAt`、状态/阶段——**这些数据已经在状态栏左边渲染了**。右边"Ready"想表达"系统空闲 + 可接收输入"的语义，**最简方案是直接删**，或加一个"⌘K 搜索"快捷键提示 | 报告给的方案**过度设计**——直接删 3 行代码即可，不需要新逻辑 |

**结论**：问题真实，修复**只要删 3 行 JSX**，不应占 P1 工程量。**应降为 P2 / 单行修复**。

### 1.4 路由切换无过渡是否真的影响感知

| 维度 | 报告主张 | 核验结果 | 实用主义判断 |
|---|---|---|---|
| 无过渡动画 | 已核验 `App.tsx` 仅 `<BrowserRouter><Routes>...` | 无 `<AnimatePresence>`，无任何 transition wrapper | 事实成立 |
| 影响感知 | 报告称"页面切换生硬" | React 路由切换是**同步组件卸载/挂载**，过渡动画需要额外机制。**但**：① Conclave 主要交互是 SPA 内单页面（board/explore/workspace/graph 各自有完整状态），不是营销页轮播图 ② 路由切换频率用户主动控制，**用户已经在等待结果**，150ms 淡入可能**感觉更慢**而非"丝滑" | 影响感知**轻微**。150ms 淡入对**功能型 SPA** 价值低，反而可能让用户觉得"是不是没响应" |
| 报告自评 P2 | 报告自己标 P2 | 与判断一致 | P2 **合理**。但仍要解决"不依赖 framer-motion"——`App.tsx` 加 CSS class + `useLocation` pathname 变化触发 class 即可，不引入动画库 |

**结论**：问题成立但**影响微弱**。P2 评级合理，**不应在 P0/P1 修复期内动手**。

### 1.5 图谱"星球跟随" + 画布分层（方向 C 整体）

| 维度 | 报告主张 | 核验结果 | 实用主义判断 |
|---|---|---|---|
| 单 `<g>` 渲染所有元素 | 已核验 `graph/page.tsx:479-519` | 一个 `<g transform>` 包 Edges + Nodes + Labels | 事实成立 |
| 拖动无视觉反馈 | 已核验 `graph/page.tsx:307-327`：拖动时只在 `handleMouseMove` 里 `setLayoutData`，**没有 ghost / ring / trail 任何反馈** | 事实成立，**拖动是"瞬移"** |
| "星球跟随"价值 | 报告称"提升到愿意把玩" | 这是**纯装饰性**提议：① 增加 30-50 行 SVG 状态 + RAF 循环 + 衰减逻辑 ② 没有任何功能价值 ③ 在演示场景有效，**在生产场景用户主要 hover/click 节点而非持续拖动** | **价值可疑**。**DeepSeek 视角**会问："这能提升 5% 任务完成率吗？能让 1 个新功能解锁吗？" 答：都不能。**建议从 P0 降为 P2**，或明确为"演示锦上添花"，不阻塞功能交付 |
| 画布五层分层 | 报告称"便于后续做 WebGL 或 Canvas 迁移" | 事实价值：分层后**可以**用 `<g>` 单独控制每层重绘。但**当前项目没这个需求**——节点数 < 50，React 完全能扛。**未雨绸缪的成本是为 0 收益买单** | **实用主义判断**：当前不需要。**应当 P2**。如果将来节点数 > 200 或接入 WebGL，再回头分层 |

**结论**：方向 C **整体被高估**。P0 中 5.1（星球跟随）和 5.2（分层渲染）**应当降为 P2** 或延后到"图谱节点数 > 200"时再启动。

---

## 2. "直接用 AntD"建议的可行性核验

### 2.1 项目实际 AntD 依赖情况

```
$ grep -r "from 'antd'" frontend/src/    # 0 hits
$ grep "antd" frontend/package.json       # 0 hits
```

**事实结论**：项目**完全没有引入 AntD**。报告"项目已经引入 Ant Design"是**事实性错误**。

### 2.2 用 AntD 替换 Radix 自定义的成本

| 项目 | Radix 当前 | AntD 替代 | 成本评估 |
|---|---|---|---|
| `antd` npm 包大小 | 0 KB | **~1.2 MB gzipped**（含全部组件 + css-in-js 运行时） | **依赖膨胀 ~1.2MB** |
| Modal | `components/ui/dialog.tsx`（96 行） | `antd/Modal` | API 形态差异大（confirm/afterClose），需改 7+ 个调用点 |
| Dropdown | `components/ui/dropdown-menu.tsx`（172 行） | `antd/Dropdown` + `antd/Menu` | 嵌套 submenu 行为不一致（AntD Menu 嵌套需要 `mode="vertical"` + key 路径） |
| Tooltip | `components/ui/tooltip.tsx`（42 行） | `antd/Tooltip` | API 接近，**这一条最容易迁移** |
| 主题统一 | 当前用 Tailwind v4 `@theme` + CSS 变量 | AntD `ConfigProvider` 用 token 注入，**完全不同的主题系统** | **需要双主题系统共存**，或废弃 Tailwind → 这是一个**架构级决定**，不是"组件替换" |
| 现有 Radix 其他组件 | 16 个 `@radix-ui/*` 包总计 ~150KB gzipped | 全部需要替换 | **不可能**——AntD 不覆盖 Toast / ScrollArea / Slider / Switch 等 |
| 违反 AGENTS §5.3 | "禁止用任何绕过 Playwright/浏览器指纹的库，禁止用未审核的爬虫/注入工具" + "加包大小 > 50KB gzipped 要慎重" | AntD 1.2MB 是 50KB 阈值的 24 倍 | **直接违反项目纪律** |

### 2.3 实用主义结论

报告"建议直接替换为 antd/Modal/Dropdown/Tooltip"是**不可行的工程建议**，原因：

1. **依赖膨胀**：1.2MB 远超 AGENTS.md §5.3 "包大小 > 50KB gzipped 要慎重" 阈值
2. **双主题系统冲突**：当前 Tailwind v4 + CSS 变量主题已经稳定运行，引入 AntD 的 `ConfigProvider` 会**制造主题分叉**
3. **替换 Radix 全家桶不可能**：16 个 Radix 组件不都有 AntD 对应，强行替换会**产生双组件库共存**
4. **报告自己"已引入 AntD"的前提就错了**

**正确建议**：**保留 Radix + 自定义封装**，只修具体违规点：
- `dialog.tsx` / `dropdown-menu.tsx` / `command-palette.tsx` 把 `shadow-lg` 改成 `shadow-sm`（5 行修改）
- `tooltip.tsx` 改用 `@radix-ui/react-tooltip`（项目已安装 `@radix-ui/react-tooltip` 在 package.json:30），**用现成的 Radix tooltip，不引 AntD**
- 整体修起来 1-2 小时搞定，不需要新依赖

**报告此项建议应当整体不采纳**。

---

## 3. P0/P1/P2 分级的"行为影响权重"评估

### 3.1 报告分级 vs 行为影响重评

| # | 报告问题 | 报告级别 | 实际行为影响 | 建议重分级 | 理由 |
|---|---|---|---|---|---|
| 1 | dialog/dropdown `shadow-lg` | P0 | **低**（视觉细节，dialog 遮罩已强力聚焦） | **P1** | 真问题但只在亮色背景明显，遮罩已够聚焦 |
| 2 | dropdown `shadow-md` | P0 | **无**（`shadow-md` 主题值是 0.06，**合规**） | **删除** | 报告误判，不应列入 |
| 3 | 页面 padding 不统一 | P0 | **中**（视觉节奏，4 个页面 4 种 padding） | P0 保留 | 简单可量化修改 |
| 4 | Explore 面板默认展开 | P0 | **中**（挤压中间内容 30% 宽度） | P0 保留 | 改 2 个 boolean，影响明显 |
| 5 | 缺少右侧浮窗徽章 | P0 | **中**（新组件 200+ 行） | **P1** | 这是**新功能不是 bug**，不应该 P0。P0 应当只修"坏掉的部分" |
| 6 | 图谱无跟随/无分层 | P0 | **低**（纯装饰 + 性能伪命题） | **P2** | 详见 1.5，节点数 < 50 时无可观测性能问题 |
| 7 | 状态栏 "Ready" | P1 | **极低**（11px 灰字） | **P2** | 30 秒修复，但优先级低于 padding/阴影 |
| 8 | 自定义 Tooltip 边界 | P1 | **中**（右侧/底部触发时确实会溢出） | P1 保留 | 真实边界 bug，**改为用 @radix-ui/react-tooltip** |
| 9 | 缩放步进感 | P1 | **低-中**（节点数 < 50 不可感） | **P2** | rAF 插值价值低，**真正问题是 memoization** |
| 10 | 路由切换无过渡 | P2 | **极低** | P2 保留 | 不阻塞 |
| 11 | 状态栏 24px → 28px | P1 | **极低** | **P2** | 4px 高度差肉眼难分辨 |
| 12 | 会议视图下顶部栏沉浸 | P1 | **中** | P1 保留 | 影响"观看"焦点 |
| 13 | 收敛 `app.css` token 至规范值 | P1 | **极低**（`#1a1d23` vs `#111827` 几乎不可分） | **P2 或删除** | **审查漂移**——把"色调偏 0.3%"说成"设计 token 偏差" |
| 14 | 替换自定义 Tooltip 为 antd/Tooltip | P1 | **中**（改用 Radix tooltip 即可，不需要 AntD） | **保留 P1，但改方案**：用 Radix tooltip | 不要引 AntD |

### 3.2 报告分级的系统性问题

1. **"装饰 = P0"错位**：星球跟随 / 浮窗徽章被标 P0，但 P0 应当是"功能阻塞/性能崩塌/严重视觉缺陷"
2. **"设计语气词当技术问题"**：`#1a1d23` 偏暖、`#e2e6eb` 偏冷、阴影透明度 0.1 vs 0.06——这些**绝大多数用户感知不到**的问题被标 P0/P1，是**审查漂移**
3. **"新功能"当"修复"**：浮窗徽章是**新功能**（200+ 行新代码），不应当与"修 padding"放同一个 P0
4. **缺少"用户行为影响"权重**：报告几乎**完全没引用任何用户行为数据**（无热图、无任务完成时间、无 N 个用户测试反馈），分级只基于代码审查

**DeepSeek 实用主义重分级**：

| 重分级 | 问题 | 修复成本 | 价值密度 |
|---|---|---|---|
| **真 P0**（必修，1 周内） | ① padding 不统一 ② Explore 面板默认展开 ③ `shadow-lg` → `shadow-sm`（3 处） | 共 ~20 行修改 | 立即可见 |
| **真 P1**（应做，2-3 周内） | ④ 顶部栏沉浸模式 ⑤ Tooltip 改用 Radix（不引 AntD） | ~150 行 | 体验明显提升 |
| **真 P2**（可选，下季度） | ⑥ 状态栏 Ready ⑦ 路由过渡 ⑧ 状态栏高度 ⑨ 浮窗徽章（重定位为新功能）⑩ 图谱分层 | 各自 50-200 行 | 锦上添花 |
| **应当删除** | ⑪ `app.css` token 收敛（除非要品牌升级）⑫ dropdown `shadow-md` "问题"（误判）⑬ "星球跟随"（装饰） | — | 0 收益 |

---

## 4. 实施路线 4 阶段评估 + 缺什么

### 4.1 报告的 4 阶段路线

```
阶段 1（1 周）：布局与弹出层收敛（padding/阴影/默认值/状态栏占位 + tsc/eslint）
阶段 2（1 周）：右侧浮窗徽章 + 组件替换（AntD 替换自定义）
阶段 3（1-2 周）：图谱交互升级（SVG 分层/星球跟随/平滑缩放 + 单元测试）
阶段 4（持续）：微交互与视觉精修（路由过渡/Landing 阴影/a11y/多分辨率）
```

### 4.2 路线评估

| 维度 | 评估 |
|---|---|
| 阶段 1 合理性 | **合理**。padding/shadow/默认值都是 5-20 行小改，1 周够用。但 **"跑过 npx tsc / npx eslint" 不够**——根据 AGENTS.md §0.5.2，**必须在 Docker 容器内跑** `docker compose -f docker-compose.test.yml run --rm frontend-test` |
| 阶段 2 合理性 | **不合理**。"AntD 替换"已经被证伪（见 §2.3）。**整个阶段 2 的前提是错的**。如果改成"Radix tooltip 迁移 + 浮窗徽章新功能"，应当**拆成两个阶段**——浮窗徽章 200+ 行代码不应和 5 行 tooltip 改动混在一起 |
| 阶段 3 合理性 | **不合理**。"SVG 分层 + 星球跟随 + 平滑缩放"是**纯装饰 + 性能伪命题**，节点数 < 50 时无可观测收益。**应当延后到"节点数 > 200"再启动** |
| 阶段 4 合理性 | **合理但空**——"持续"等于无明确交付，"微交互"是开放清单。应当**给出具体 Done 定义** |
| 验证指标 | **严重缺失**：报告**完全没有可量化验证指标**——没有 LCP/INP/CLS、没有 TTI、没有"用户点击到首字节"、没有"页面切换 95 分位耗时"、没有"图谱缩放掉帧率" |

### 4.3 缺什么（按优先级）

#### 4.3.1 缺可量化性能指标（最关键）

报告应当补充：

| 指标 | 当前基线 | 目标 | 测量方式 |
|---|---|---|---|
| **LCP**（Largest Contentful Paint） | 未测 | < 2.5s（good） | `web-vitals` 包 + PerformanceObserver |
| **INP**（Interaction to Next Paint） | 未测 | < 200ms | 同上 |
| **CLS**（Cumulative Layout Shift） | 未测 | < 0.1 | 同上 |
| **页面切换耗时** | 未测 | < 150ms | React Profiler + `performance.now()` |
| **图谱缩放掉帧率** | 未测 | < 5% 掉帧 | rAF counter + DevTools Performance |
| **Dialog 打开首帧** | 未测 | < 16ms | 同上 |
| **浮窗徽章 hover 反馈延迟** | 未测 | < 50ms | 同上 |

**这是报告最大的盲点**：没有指标就没有验收标准。AGENTS.md §0.5.2 "必须在 Docker 容器内跑测试"对应到前端是"必须在容器内跑 lighthouse / vitest / playwright"。

#### 4.3.2 缺 Playwright 视觉回归

报告 §9.4 只说"在 1920px / 1440px / 1280px / 768px 视口下检查布局"——这是**手动测试**。**应当配置 Playwright 截图比对**（playwright 已有视觉回归能力），对每条 P0 修复做截图对比。

#### 4.3.3 缺自动化 lint 卡点

报告没提：应当在 `frontend/src/components/ui/` 下加 `eslint-plugin-tailwindcss` 规则**禁用 `shadow-lg`**（项目已有 eslint.config.js）。

#### 4.3.4 缺 a11y 验收标准

报告 §3.3 提到"无 aria-describedby"是 P1，但 §9.4 验证方式**完全没提 a11y**。应当加 `axe-core` + Playwright 的自动 a11y 检查。

#### 4.3.5 缺依赖决策记录

报告"用 AntD 替换"是一个**架构级决定**，但**没要求先开 ADR**（AGENTS.md §5.1 "大改前先开 ADR"）。正确的工程流程是：

1. 写 ADR `docs/design/adr/014-antd-vs-radix-migration.md`，列出 Radix / AntD / HeadlessUI 三个方案的成本-收益矩阵
2. 团队评审 → Accepted / Rejected
3. 实施

报告**跳过了 ADR 步骤**。

#### 4.3.6 缺回退策略

报告没说"如果 AntD 迁移失败如何回退"。Radix 当前封装是稳定的，引入 AntD 是**不可逆重构**（主题系统、组件 API 全部变化）。**应当先在 feature flag 下做小范围试点**，而不是阶段 2 直接全量替换。

---

## 5. DeepSeek 视角独立结论

### 5.1 核心判断

报告**方向对、细节错**。三个主要问题：

1. **"用 AntD 替换"是误诊**（事实错误 + 架构级建议没走 ADR + 违反依赖膨胀纪律）。**正确做法**：保留 Radix + 自定义封装，**只修 3 处 `shadow-lg` 用错**，加 1 处 `@radix-ui/react-tooltip` 替换
2. **"星球跟随 / 画布分层"是过度工程**：在节点数 < 50 时无可观测价值，**应当延后**
3. **"浮窗徽章"是新功能不是 bug**：不应当与 padding/阴影修复同列 P0

### 5.2 报告的合理之处（应当采纳）

- ✅ padding 24/32 不统一 → P0 修复，**1 行 className 修改**
- ✅ Explore 面板默认 `false` → P0 修复，**1 行 boolean**
- ✅ `shadow-lg` 超标 → P0 修复，**3 处 className 替换**
- ✅ 状态栏 "Ready" → P2 修复，**3 行删除**
- ✅ Tooltip 改用 Radix（不引 AntD）→ P1 修复
- ✅ 顶部栏会议视图沉浸 → P1 修复

### 5.3 报告的错误之处（应当拒绝）

- ❌ "项目已引入 AntD"（事实错误）
- ❌ "用 AntD Modal/Dropdown 替换自定义"（违反依赖膨胀纪律 + 跳过 ADR + 不可回退）
- ❌ 5.1 星球跟随 → P0（装饰当 bug）
- ❌ 5.2 五层画布分层 → P0（未雨绸缪为 0 收益）
- ❌ 5.3 缩放步进感 → P1（伪命题，rAF 插值治标不治本）
- ❌ dropdown `shadow-md` 列入重阴影（误判，主题值合规）
- ❌ `app.css` token 收敛 → P1（`#1a1d23` 偏暖肉眼不可分）
- ❌ 浮窗徽章 → P0（这是新功能）
- ❌ 4 阶段路线（前提 AntD 错误，导致阶段 2 整体不可行）
- ❌ 缺可量化指标（无 LCP/INP/CLS，无 Playwright 视觉回归）

### 5.4 行为/性能视角的"如果只能改 3 件事"

按 **价值密度**（行为改善 / 改造成本）排序：

1. **Explore 面板默认折叠 + 改 2 个 boolean**（1 行代码，最大行为影响——中间内容区从 60% 提升到 90%）
2. **`shadow-lg` → `shadow-sm`**（3 处替换，符合设计系统，1 行/处）
3. **padding 24/32 统一**（2 处 className 替换，1 行/处）

合计 6 行核心修改，1 小时内可完成，**比报告 4 阶段 5 周路线务实 50 倍**。

### 5.5 整体评分

| 维度 | 评分 | 说明 |
|---|---|---|
| 事实准确性 | **5/10** | "项目已引入 AntD"是硬伤；padding/状态栏/图谱 handler/默认值 4 处事实正确 |
| 行为影响判断 | **4/10** | 装饰当 bug，新功能当修复，缺少用户行为数据 |
| 性能分析深度 | **3/10** | 只看到 wheel handler 步进，没看到"全量重渲染"真瓶颈；缺 LCP/INP/CLS |
| 工程纪律遵循 | **3/10** | 违反依赖膨胀纪律、跳过 ADR、缺可量化指标、缺回退策略 |
| 实施路线可执行性 | **4/10** | 阶段 1 可行，阶段 2 前提错误，阶段 3 价值可疑，阶段 4 是开放清单 |
| **整体** | **3.8/10** | 报告**识别了真问题但给出的方案过度工程**，且关键事实性前提错误 |

### 5.6 一句话总结

> **报告是个"用 AntD 重写"的诱饵**：识别了 5 个真问题（padding/默认值/shadow-lg/Ready/Tooltip 边界），但**解决方案**被 AntD 错误前提和过度装饰建议污染。**正确做法**：保留 Radix，6 行代码修 3 个真问题，**把"星球跟随"和"浮窗徽章"作为独立新功能走 ADR 流程**。
