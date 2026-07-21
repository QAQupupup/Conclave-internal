# 前端细节雕琢与问题修复

> **日期**: 2026-07-17
> **范围**: frontend/src（8 文件，63 增 37 删）
> **修复状态**: 已完成，tsc + vite build + 浏览器验证通过

## 一、变更总览

对 React 前端进行细节雕琢和问题审查，修复 5 项问题：1 项数据显示 bug、1 项交互降级、1 项 UX 干扰、1 项文案不一致、1 项硬编码数据。

## 二、变更详情

### 1 — 会议视图显示原始类型 ID 而非友好标签

- **位置**: `src/views/Meeting.tsx`
- **问题**: 会议元信息栏显示 `产出类型 prd_openapi`（原始 ID），而非友好标签。原始原型显示 `产出类型 PRD文档`。
- **修复**: 导入 `REPORT_TYPES`，构建 `TYPE_LABELS` 映射表，将 `meeting.type` 映射为友好标签（如 `prd_openapi` → `PRD + OpenAPI`）。
- **原因**: 类型 ID 是内部标识，不应直接展示给用户。

### 2 — 模型中心"配置 Key"按钮使用 alert() 而非跳转

- **位置**: `src/views/Models.tsx`
- **问题**: Provider 卡片的"配置 Key"按钮调用 `alert('BYOK配置面板（原型）')`，使用浏览器原生弹窗，体验差且无实际功能。
- **修复**: 改为 `setView('settings')`，点击后跳转到设置页的 LLM API Key 配置区域。
- **原因**: 应引导用户到实际功能页，而非用 alert 占位。

### 3 — 导航到数据视图时登录弹窗自动弹出（核心 UX 问题）

- **位置**: `src/lib/api.ts`、`src/state/AppContext.tsx`、`src/views/Models.tsx`、`src/views/Monitor.tsx`、`src/views/Settings.tsx`、`src/views/Report.tsx`
- **问题**: Models/Monitor/Settings/Report 等视图挂载时调用 API 获取数据，若用户未登录（无 token 或 token 过期），API 返回 401 触发全局 `onUnauthorized` 回调，自动弹出登录弹窗。用户仅浏览视图就被打断，且视图已 try/catch 回退 mock 数据，弹窗属于多余干扰。
- **修复**:
  - `api()` 函数新增 `silent` 选项：`silent: true` 时 401 仅清除 token 并抛错，不触发 `onUnauthorized`（不弹登录窗）。
  - `apiGetProviders`、`apiGetModels`、`apiGetMetrics`、`apiGetKeys`、`apiGetPreferences`、`apiListMeetings`、`apiGetReportLayout`、`apiMe` 等后台数据加载函数新增 `silent` 参数。
  - 各视图挂载时的数据加载调用传 `silent: true`，401 静默回退 mock。
  - 用户主动操作（创建会议、保存 Key、介入引导等）保持非静默，401 仍弹登录窗。
- **原因**: 浏览视图是被动行为，不应被登录弹窗打断；用户主动操作才需要认证提示。

### 4 — 设置页深色模式按钮文案不一致

- **位置**: `src/views/Settings.tsx`
- **问题**: 深色模式开关按钮在浅色模式下显示"切换"，在深色模式下显示"切换到浅色"，文案不对称。
- **修复**: 统一为 `theme === 'dark' ? '切换到浅色' : '切换到深色'`。
- **原因**: 按钮文案应明确告知用户操作结果。

### 5 — 上下文面板使用硬编码数据而非会议实际状态

- **位置**: `src/components/ContextPanel.tsx`
- **问题**: 概览面板的议题、产出类型、当前阶段、已运行时间均为硬编码值（如"将现有单体电商平台迁移至微服务架构"、"PRD文档"、"证据校验 · 第 4 / 6 阶段"、"32分14秒"），不随会议状态变化。
- **修复**: 从 `useApp()` 获取 `meeting`、`stageName`、`statusText`，动态渲染议题标题、类型标签、当前阶段（基于 `meeting.stage`）、已运行时间（基于 `meeting.elapsed`，格式化为"X分XX秒"）、会议状态。
- **原因**: 上下文面板应反映会议实时状态，而非固定演示数据。

## 三、验证结果

- `tsc -b --noEmit` 类型检查零错误。
- `vite build` 构建成功。
- `vite preview` 浏览器验证：
  - 清除 token 后导航到 Models 视图：不再弹出登录弹窗，正常显示 mock 数据。
  - 导航到 Settings 视图：不弹窗，深色模式按钮显示"切换到深色"。
  - 会议视图元信息栏：显示"产出类型 PRD + OpenAPI"（非 `prd_openapi`）。
  - 上下文面板概览：显示动态数据（议题"微服务架构迁移方案"、类型"PRD + OpenAPI"、阶段"澄清 · 第 1 / 6 阶段"、运行"32分14秒"、状态"进行中"）。
