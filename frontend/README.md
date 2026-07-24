# Conclave Frontend

[返回项目主页](../README.md) | React 18 + TypeScript + Vite 前端应用。入口文件为 `app.html`（非 `index.html`），UI 采用自定义 CSS 组件库（无第三方 UI 框架依赖）。

## 页面结构

```
frontend/src/
├── views/                   # 页面级组件
│   ├── Board.tsx            # 会议看板（首页，会议列表与创建）
│   ├── Meeting.tsx          # 会议主界面（聊天、日志、上下文面板）
│   ├── Models.tsx           # 模型中心（LLM 配置与测试）
│   ├── Topology.tsx         # 服务联通视图（组件依赖与健康状态）
│   ├── Monitor.tsx          # 运行监控（指标与实时状态）
│   ├── DevOpsPanel.tsx      # 运维面板（Docker 主机管理）
│   ├── Report.tsx           # 报告查看页
│   ├── Settings.tsx         # 设置页
│   ├── Landing.tsx          # 落地页
│   ├── Login.tsx            # 登录页
│   └── NotFound.tsx         # 404 页
│
├── components/              # 可复用组件
│   ├── NavRail.tsx          # 左侧导航栏
│   ├── Topbar.tsx           # 顶部栏
│   ├── MeetingToolbar.tsx   # 会议控制工具栏
│   ├── ContextPanel.tsx     # 上下文面板（议题/证据/产出/Token）
│   ├── LogPanel.tsx         # 可折叠实时日志面板
│   ├── PhasedProgress.tsx   # 六阶段进度条
│   ├── ServiceViewer.tsx    # 服务状态查看器
│   ├── CommandPalette.tsx   # 命令面板
│   ├── TenantSwitcher.tsx   # 租户切换器
│   ├── RequireAuth.tsx      # 路由认证守卫
│   ├── ConfirmModal.tsx     # 确认弹窗
│   ├── SessionExpiredModal.tsx # 会话过期弹窗
│   ├── ErrorBoundary.tsx    # 错误边界
│   └── Toast.tsx            # 全局消息提示
│
├── lib/                     # 工具库
│   ├── api.ts               # REST API 客户端（fetch 封装）
│   ├── ws.ts                # WebSocket 客户端（自动重连、增量回放）
│   ├── auth.ts              # 认证状态管理
│   └── format.ts            # 格式化工具（时间、字节等）
│
├── state/                   # 全局状态
│   └── AppContext.tsx       # React Context 全局状态
│
├── types/                   # TypeScript 类型定义
│   └── meeting.ts           # 会议相关类型
│
├── data/                    # 静态数据与布局配置
│   ├── reportLayouts.ts     # 报告布局模板
│   ├── reportData.ts        # 报告示例数据
│   └── mock.ts              # Mock 数据（开发模式）
│
├── styles/                  # 全局样式
│   └── global.css           # 全局 CSS 变量与重置
│
├── test/                    # 前端测试（Vitest）
├── App.tsx                  # 路由配置
├── main.tsx                 # 应用入口
└── vite-env.d.ts            # Vite 类型声明
```

## 路由

| 路径 | 页面 | 认证要求 |
|---|---|---|
| `/login` | 登录页 | 无 |
| `/` | 会议看板 | 是 |
| `/meeting/:id` | 会议主界面 | 是 |
| `/models` | 模型中心 | 是 |
| `/topology` | 联通视图 | 是 |
| `/monitor` | 监控面板 | 是 |
| `/devops` | 运维面板 | 是 |
| `/settings` | 设置 | 是 |
| `/report/:id` | 报告页 | 是 |
| `*` | 404 | - |

## 实时通信

通过 `lib/ws.ts` 管理 WebSocket 连接：

- 连接后端 `ws://localhost:8000/ws/meetings/{id}`
- 自动重连（指数退避）
- 基于事件 seq 的增量回放（断线重连后从最后 seq 拉取错过的事件）
- 事件类型：agent_spoke、stage_transition、control_action、error、meeting_state、service_deployed 等

## 设计规范

遵循 `backend/app/skills/ui_design_system.yaml` 的 UI 设计系统：

- 品牌色：沉稳靛蓝 `#335c8e`，糖果色点缀 < 5% 面积
- 圆角：4-8px
- 阴影：极轻（opacity 0.04-0.06）
- 过渡：0.15s 颜色/透明度/transform（禁止 width/height 动画）
- 禁止：大面积渐变、3D 效果、重阴影、text-shadow、`!important`、z-index=9999
- 中英文之间加半角空格
- 列表按 `created_at DESC` 倒序

## 开发指南

### 环境准备

```bash
cd frontend
npm install
```

### 开发模式

```bash
npm run dev
```

Vite dev server 启动在 `http://localhost:5173`，API 请求自动代理到后端 `http://localhost:8000`（配置见 `vite.config.ts`）。

### 构建

```bash
npm run build
```

### 代码质量

```bash
# TypeScript 类型检查
npx tsc -b --noEmit

# ESLint
npm run lint
```

注意：ESLint 规则对现有代码较宽松（no-explicit-any、no-unused-vars 等为 warn/off），新代码请自觉遵守规范，不要为了"更干净"把规则调成 error。

### 测试

```bash
npm run test
```

### 路径别名

`@` 映射到 `src/`，例如 `import { api } from '@/lib/api'`。
