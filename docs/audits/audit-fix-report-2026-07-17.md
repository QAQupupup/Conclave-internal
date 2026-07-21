# 前端 React 迁移与系统入口后端健康检查

> **日期**: 2026-07-17
> **范围**: frontend（app.html 原型 → React+TS+Vite 工程化；portal 入口后端健康检查）
> **修复状态**: 已完成，Docker 构建验证通过

## 一、变更总览

本次提交包含两项前端变更：

1. **React 工程化迁移**：将单文件 HTML 原型 `app.html`（4030 行）重构为标准 Vite + React + TypeScript 工程，旧原型保留为 `app.legacy.html` 作参照。
2. **系统入口后端健康检查**：portal 首页"进入系统"按钮增加后端 `/health` 健康检查，后端未连接时弹窗提示，不再直接进入系统或回退演示模式。

## 二、变更详情

### 1 — React 工程化迁移

- **位置**: `frontend/`（新建 `src/`、`public/`、`package.json`、`tsconfig.json`、`vite.config.ts`）
- **问题**: 原型 `app.html` 为 4030 行单文件 HTML（命令式 DOM 操作、全局变量状态），难以维护和扩展。
- **修复**:
  - 搭建 Vite + React + TS 工程，入口 `app.html`（对应 nginx `/app` 路由）。
  - 原 `<style>` 逐字移植至 `src/styles/global.css`（778 行），视觉 100% 一致。
  - mock 数据移至 `src/data/mock.ts`（18 常量 + 20 类型），报告数据/布局 spec 移至 `src/data/reportData.ts` + `reportLayouts.ts`（9 种布局）。
  - 基础库 `src/lib/`：`api.ts`（20+ 接口 + JWT 注入）、`ws.ts`（会议/系统 WS + 指数退避重连）、`auth.ts`（token 订阅）、`format.ts`（sanitize/highlight）。
  - 状态层 `src/state/AppContext.tsx`：视图/主题/认证/日志/命令面板/上下文/会议状态 + WS 接线。
  - 8 个视图组件 + 6 个外壳组件（Topbar/NavRail/MeetingToolbar/ContextPanel/CommandPalette/LogPanel/LoginModal）。
  - `Dockerfile` 改为多阶段构建（node 编译 → nginx serve dist），`nginx.conf` 无需改动（已适配）。
- **原因**: 工程化提升可维护性；多阶段构建符合项目规范 §2.1；CSS 逐字移植确保视觉一致。

### 2 — Portal 系统入口后端健康检查

- **位置**: `frontend/public/index.html`（portal 入口页）
- **问题**: "进入系统"卡片直接 `location.href='/app'`，未检测后端状态。后端未启动时用户进入系统后静默回退 mock 数据，体验误导。
- **修复**:
  - 新增 `checkBackendReady()`：fetch `/health`（5s 超时），校验响应体为真正的健康检查 JSON（含 `status` 字段），而非 SPA 回退的 HTML。
  - "进入系统"点击时先检测：后端未连接（fetch 失败 / 非 2xx / 响应非健康 JSON）→ 弹窗"后端服务未启动，请检查后端服务是否正常运行，或联系管理员"；后端已启动（`ok`/`degraded`）→ 跳转 `/app`。
  - 弹窗含"知道了"（关闭）与"重新检测"（重新检测后端，就绪后自动进入）按钮。
  - "查看演示"入口保持直接跳转 `/demo`（纯前端 mock，无需后端）。
- **原因**: 用户要求后端未就绪时明确提示而非静默使用演示模式；校验响应体可正确区分后端真实响应与 SPA 路由回退（dev/preview 环境），生产 nginx 有显式 `/health` 代理，后端宕机时返回 502。

### 3 — 健康检查响应体校验的设计决策

- **位置**: `frontend/public/index.html` — `checkBackendReady()`
- **问题**: 仅靠 HTTP 状态码判定时，Vite dev/preview 的 SPA fallback 会对 `/health` 返回 200 + index.html，导致误判后端已就绪。
- **修复**: 除 `res.ok` 外，额外解析 JSON 并校验 `typeof d.status === 'string'`；JSON 解析失败或无 `status` 字段时判定为未就绪。
- **原因**: 生产 nginx 有显式 `location /health { proxy_pass http://backend:8000; }`，后端宕机返回 502，不会触发 SPA fallback；但开发环境需兼容，响应体校验使逻辑在 dev/preview/生产 三种环境一致正确。

## 三、验证结果

- `tsc -b --noEmit` 类型检查零错误。
- `vite build` 构建成功（54 模块，产物 `dist/app.html` + assets）。
- `vite preview` 浏览器验证：
  - portal 页"进入系统"按钮调用 `checkBackendReady`，后端运行（`status: degraded`）时正确放行进入 `/app`。
  - 手动触发 `showBackendModal()` 验证弹窗渲染正确（标题"后端服务未启动"、描述"无法连接到 Conclave 后端服务…"、按钮"知道了"/"重新检测"）。
  - "重新检测"按钮在后端就绪时关闭弹窗并跳转 `/app`。
- Docker 多阶段构建已由用户在 Docker 环境确认通过。
